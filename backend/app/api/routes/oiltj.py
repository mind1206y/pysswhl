"""车辆油量统计报表(照旧 oiltjController 1:1 复刻)。

数据源(与旧系统保持一致,不同统计各用各的表,不混用):
- 列表月/年加油量、加油明细、财务导出 → PlusOil(ptime)
- 列表里程(本/上月底公里数、年里程、用车次数) → yongcherc(jsdate/ksdate)
- 子表格 12 月油量、油量图、里程图、部门年度油量图、月度/年度导出 → tboil(nian/yue/oilnum/glnum)
- 油卡余额 → OilCard(zt=正常, 优先 carid 匹配,回退旧冗余 chehao 列)

部门数据权限:dept_scope_ids 子树语义(照旧 bmcj 前缀匹配);
筛选部门下拉按所选部门子树过滤(照旧 StartsWith(bmcj))。

权限:oiltj:view(车辆业务,init_db 登记)。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, or_

from app.api.deps import dept_scope_ids, get_current_user, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, OilCard, PlusOil, Tboil, Yongcherc
from app.services.oiltj_export import (
    build_finance_excel, build_month_excel, build_year_excel, finance_filename,
)
from app.services.vehicle_export import content_disposition

router = APIRouter()


def _n(v):
    return float(v) if isinstance(v, Decimal) else (v or 0)


def _round2(v):
    return round(_n(v), 2)


def _user_scope(db, user) -> Optional[set]:
    """用户可见部门集合;超管/未挂部门 → None 不限定(照旧超管看全部)。"""
    return dept_scope_ids(db, user)


def _subtree_ids(db, root: int) -> set:
    """指定部门的完整子树 id(照旧 StartsWith(bmcj) 层级语义)。"""
    ids = {root}
    while True:
        children = (
            db.query(Department.id)
            .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids))
            .all()
        )
        if not children:
            break
        ids |= {c[0] for c in children}
    return ids


def _visible_cars(db, user, bmid: Optional[int] = None):
    """部门作用域内的车辆查询(照旧 delf!=0 全量,px 开关再筛正常)。"""
    q = db.query(ClChe).filter(ClChe.delf != 0)
    scope = _user_scope(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    if bmid:
        q = q.filter(ClChe.bmid.in_(_subtree_ids(db, bmid)))
    return q


def _oilcard_map(db, cars: list) -> dict:
    """车 → 油卡余额(zt=正常,优先 carid 匹配,回退旧冗余 chehao 列;ye+bfj)。"""
    if not cars:
        return {}
    ids = [c.id for c in cars]
    chehaos = [c.chehao for c in cars if c.chehao]
    cards = (
        db.query(OilCard)
        .filter(OilCard.zt == "正常",
                or_(OilCard.carid.in_(ids), OilCard.chehao.in_(chehaos)))
        .all()
    )
    by_carid = {o.carid: o for o in cards if o.carid}
    by_chehao = {o.chehao: o for o in cards if o.chehao}
    out = {}
    for c in cars:
        card = by_carid.get(c.id) or by_chehao.get(c.chehao)
        if card:
            out[c.id] = _round2((_n(card.ye) or 0) + (_n(card.bfj) or 0))
    return out


def _month_stats(db, cars: list, nian: int, yue: int) -> dict:
    """车 → 月加油量(PlusOil,照旧 ptime 年月)。"""
    if not cars:
        return {}
    ids = [c.id for c in cars]
    start = datetime(nian, yue, 1)
    end = datetime(nian + 1, 1, 1) if yue == 12 else datetime(nian, yue + 1, 1)
    rows = (
        db.query(PlusOil.cheid, func.sum(PlusOil.oill))
        .filter(PlusOil.cheid.in_(ids), PlusOil.ptime >= start, PlusOil.ptime < end)
        .group_by(PlusOil.cheid).all()
    )
    return {cid: _round2(v) for cid, v in rows}


def _year_oil(db, cars: list, nian: int) -> dict:
    """车 → 年加油量(PlusOil)。"""
    if not cars:
        return {}
    ids = [c.id for c in cars]
    rows = (
        db.query(PlusOil.cheid, func.sum(PlusOil.oill))
        .filter(PlusOil.cheid.in_(ids),
                PlusOil.ptime >= datetime(nian, 1, 1),
                PlusOil.ptime < datetime(nian + 1, 1, 1))
        .group_by(PlusOil.cheid).all()
    )
    return {cid: _round2(v) for cid, v in rows}


def _mileage_stats(db, cars: list, nian: int, yue: int) -> dict:
    """车 → 本月底/上月底公里数、年里程、用车次数(yongcherc,口径照旧 Get)。

    - 本月底公里数 = 当月 jsdate 的 jsgl 最大值
    - 上月底公里数 = 上月(跨年取 12 月)jsgl 最大值
    - 年最大里程 = 年内 jsgl!=0 的最后一条记录(按 jsdate 倒序)
    - 上年最大里程 = 上年同口径
    - 用车次数 = 当年 ksdate 计数
    """
    if not cars:
        return {}
    ids = [c.id for c in cars]

    def _month_max(y, m):
        start = datetime(y, m, 1)
        end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        rows = (
            db.query(Yongcherc.cheid, func.max(Yongcherc.jsgl))
            .filter(Yongcherc.cheid.in_(ids), Yongcherc.jsdate >= start,
                    Yongcherc.jsdate < end)
            .group_by(Yongcherc.cheid).all()
        )
        return {cid: int(v or 0) for cid, v in rows}

    def _year_last(y):
        recs = (
            db.query(Yongcherc.cheid, Yongcherc.jsgl)
            .filter(Yongcherc.cheid.in_(ids), Yongcherc.jsdate >= datetime(y, 1, 1),
                    Yongcherc.jsdate < datetime(y + 1, 1, 1), Yongcherc.jsgl != 0)
            .order_by(Yongcherc.jsdate.desc())
            .all()
        )
        out = {}
        for cid, jsgl in recs:  # 倒序遍历,首个即年内最后一条
            if cid not in out:
                out[cid] = int(jsgl or 0)
        return out

    cur_max = _month_max(nian, yue)
    if yue == 1:
        prev_max = _month_max(nian - 1, 12)
    else:
        prev_max = _month_max(nian, yue - 1)
    year_last = _year_last(nian)
    prev_year_last = _year_last(nian - 1)

    times_rows = (
        db.query(Yongcherc.cheid, func.count())
        .filter(Yongcherc.cheid.in_(ids),
                Yongcherc.ksdate >= datetime(nian, 1, 1),
                Yongcherc.ksdate < datetime(nian + 1, 1, 1))
        .group_by(Yongcherc.cheid).all()
    )
    times = {cid: int(n) for cid, n in times_rows}

    out = {}
    for c in cars:
        cid = c.id
        curm = cur_max.get(cid, 0)
        prevm = prev_max.get(cid, 0)
        month_mile = curm - prevm
        month_oil = 0  # 由调用方合并月油量后回填计算月百公里油耗
        yl = year_last.get(cid, 0)
        pyl = prev_year_last.get(cid, 0)
        out[cid] = {
            "bydgls": curm, "sydgls": prevm, "yssgls": month_mile,
            "ngls": yl - pyl, "jnzdgls": yl, "snzdgls": pyl,
            "times": times.get(cid, 0), "_month_mile": month_mile,
            "_month_oil": month_oil,
        }
    return out


# ==================== 下拉数据 ====================
@router.get("/dicts")
def dicts(db=Depends(get_db), current: User = Depends(require_permission("oiltj:view"))):
    """年度/车辆类型/部门/车辆下拉(照旧 Index 预载;车辆下拉只含正常车 delf==1)。"""
    scope = _user_scope(db, current)
    base = db.query(ClChe).filter(ClChe.delf == 1)
    if scope is not None:
        base = base.filter(ClChe.bmid.in_(scope))
    cars = base.order_by(ClChe.bmid, ClChe.chehao).all()
    dept_names = {d.id: d.name for d in db.query(Department).all()}

    # 年度:tboil 里作用域内车辆出现过的年份,倒序(照旧 getnd)
    ids = [c.id for c in cars]
    years = []
    if ids:
        years = [int(y) for (y,) in (
            db.query(Tboil.nian).filter(Tboil.cheid.in_(ids)).distinct()
            .order_by(Tboil.nian.desc()).all()
        )]

    lx_used = [r[0] for r in (
        db.query(ClChe.lx).filter(ClChe.delf != 0, ClChe.lx != "")
        .distinct().order_by(ClChe.lx).all()
    )]

    dq = db.query(Department).order_by(Department.id)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.all()]

    vehicles = [{
        "id": c.id,
        "label": f"{c.chehao} →{dept_names.get(c.bmid) or c.bm or ''}",
    } for c in cars]

    if current.departments:
        my_dept = dept_names.get(sorted({d.id for d in current.departments})[0])
    else:
        my_dept = "全部部门"

    return {
        "years": years,
        "current_year": date.today().year,
        "current_month": date.today().month,
        "lx_used": lx_used,
        "departments": departments,
        "vehicles": vehicles,
        "my_dept": my_dept,
    }


@router.get("/months")
def months(year: int = 0, db=Depends(get_db),
           current: User = Depends(require_permission("oiltj:view"))):
    """按年份取月份下拉(照旧 getmons:tboil 该年出现过的月份,升序,首项上月占位)。"""
    if year == 0:
        year = date.today().year
    ids = [c.id for c in _visible_cars(db, current)]
    ms = []
    if ids:
        ms = [int(m) for (m,) in (
            db.query(Tboil.yue).filter(Tboil.cheid.in_(ids), Tboil.nian == year)
            .distinct().order_by(Tboil.yue).all()
        )]
    return {"months": ms}


@router.get("/cars")
def cars(bmid: Optional[int] = None, db=Depends(get_db),
         current: User = Depends(require_permission("oiltj:view"))):
    """车号下拉联动(照旧 getss:按部门子树过滤,部门名拼接展示)。"""
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    q = db.query(ClChe).filter(ClChe.delf == 1)
    scope = _user_scope(db, current)
    if bmid:
        q = q.filter(ClChe.bmid.in_(_subtree_ids(db, bmid)))
    elif scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    rows = q.order_by(ClChe.bmid, ClChe.chehao).all()
    return [{"value": c.id,
             "text": f"{c.chehao} →{dept_names.get(c.bmid) or c.bm or ''}"}
            for c in rows]


# ==================== 主列表(照旧 Get) ====================
def _build_list(db, user, *, bmid, clx, cheid, sousou, nian, yue,
                px, nooilcard, oillie):
    """照旧 Get 的车辆过滤 + 排序(部门、用途倒序),返回未分页车辆列表。"""
    q = _visible_cars(db, user, bmid=bmid)
    if nooilcard:
        q = q.filter(ClChe.yongtu != "油卡")
    if oillie:
        q = q.filter(ClChe.oil == "0#")
    if not px:
        q = q.filter(ClChe.delf == 1)
    if cheid:
        q = q.filter(ClChe.id == cheid)
    if sousou:
        q = q.filter(ClChe.chehao.like(f"%{sousou}%"))
    if clx:
        q = q.filter(ClChe.lx == clx)
    return q.order_by(ClChe.bmid.asc(), ClChe.yongtu.desc()).all()


def _attach_stats(db, cars: list, nian: int, yue: int, year_oil: dict = None) -> list:
    """照旧 Get 逐行统计(批量聚合避免 N+1)。"""
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    month_oil = _month_stats(db, cars, nian, yue)
    year = year_oil if year_oil is not None else _year_oil(db, cars, nian)
    mileage = _mileage_stats(db, cars, nian, yue)
    ye_map = _oilcard_map(db, cars)

    rows = []
    for i, c in enumerate(cars, start=1):
        m = mileage.get(c.id, {"bydgls": 0, "sydgls": 0, "yssgls": 0, "ngls": 0,
                               "jnzdgls": 0, "snzdgls": 0, "times": 0,
                               "_month_mile": 0})
        mo = month_oil.get(c.id, 0)
        yo = year.get(c.id, 0)
        month_mile = m["_month_mile"]
        month_lpkm = 0 if (month_mile == 0 or mo == 0) else round(mo / month_mile * 100, 2)
        lpkm = 0 if m["ngls"] == 0 else round(yo / m["ngls"] * 100, 2)
        rows.append({
            "ID": i,
            "cheid": c.id,
            "chehao": c.chehao or "",
            "bumen": dept_names.get(c.bmid) or c.bm or "",
            "cheyt": c.yongtu or "",
            "lx": c.lx or "",
            "oil": c.oil or "",
            "delf": c.delf,
            "niand": nian,
            "yuef": yue,
            "yoil": mo,
            "monthLpkm": month_lpkm,
            "noil": yo,
            "lpkm": lpkm,
            "ngls": m["ngls"],
            "bydgls": m["bydgls"],
            "sydgls": m["sydgls"],
            "yssgls": m["yssgls"],
            "times": m["times"],
            "ye": ye_map.get(c.id, 0),
            "chuchang": c.chuchang.strftime("%Y-%m-%d") if c.chuchang else "",
            "pailiang": c.pailiang or "",
            "jnzdgls": m["jnzdgls"],
            "snzdgls": m["snzdgls"],
            "bz": c.lx or "",  # 照旧 viewoiltj.bz=lx(表格"类型"列)
        })
    return rows


def _list_params(bmid: Optional[int], clx: str, cheid: Optional[int], sousou: str,
                 nian: Optional[int], yue: Optional[int], px: bool,
                 nooilcard: bool, oillie: bool):
    """默认口径照旧:nian=今年,yue=上月(px=False 只看正常车)。"""
    nian = nian or date.today().year
    yue = yue if (yue and yue > 0) else (date.today().month - 1 or 12)
    return dict(bmid=bmid, clx=clx, cheid=cheid, sousou=sousou,
                nian=nian, yue=yue, px=px, nooilcard=nooilcard, oillie=oillie)


@router.get("")
def get_list(
    page: int = 1,
    size: int = 20,
    bmid: Optional[int] = None,
    clx: str = "",
    cheid: Optional[int] = None,
    sousou: str = "",
    nian: Optional[int] = None,
    yue: Optional[int] = None,
    px: bool = False,
    nooilcard: bool = False,
    oillie: bool = False,
    sort: str = "",
    order: str = "asc",
    db=Depends(get_db),
    current: User = Depends(require_permission("oiltj:view")),
):
    p = _list_params(bmid, clx, cheid, sousou, nian, yue, px, nooilcard, oillie)
    cars = _build_list(db, current, **p)
    total = len(cars)
    page_cars = cars[(page - 1) * size: page * size]
    rows = _attach_stats(db, page_cars, p["nian"], p["yue"])
    if sort and rows:
        reverse = order.lower() == "desc"
        rows.sort(key=lambda r: (r.get(sort) is None, r.get(sort)), reverse=reverse)
    return {"total": total, "rows": rows}


# ==================== 子表格 / 图表(tboil) ====================
def _check_car_visible(db, user, cheid: int) -> ClChe:
    car = db.get(ClChe, cheid)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = _user_scope(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有查看该车辆的权限")
    return car


@router.get("/{cheid}/youliang")
def get_youliang(cheid: int, year: int, db=Depends(get_db),
                 current: User = Depends(require_permission("oiltj:view"))):
    """行展开子表:tboil 该车该年 12 个月油量合计(照旧 getyouliang)。"""
    car = _check_car_visible(db, current, cheid)
    sums = dict(db.query(Tboil.yue, func.sum(Tboil.oilnum))
                .filter(Tboil.cheid == cheid, Tboil.nian == year)
                .group_by(Tboil.yue).all())
    row = {"chehao": car.chehao or "", "nian": year}
    for m in range(1, 13):
        row[f"yue{m}"] = _round2(sums.get(m))
    return {"rows": [row], "total": 1}


@router.get("/{cheid}/chart")
def get_chart(cheid: int, year: int, db=Depends(get_db),
              current: User = Depends(require_permission("oiltj:view"))):
    """油量柱状图数据(照旧 getchart)。"""
    car = _check_car_visible(db, current, cheid)
    sums = dict(db.query(Tboil.yue, func.sum(Tboil.oilnum))
                .filter(Tboil.cheid == cheid, Tboil.nian == year)
                .group_by(Tboil.yue).all())
    data = {"chehao": car.chehao or "", "nian": year}
    for m in range(1, 13):
        data[f"yue{m}"] = _round2(sums.get(m))
    return data


@router.get("/{cheid}/glchart")
def get_glchart(cheid: int, year: int, db=Depends(get_db),
                current: User = Depends(require_permission("oiltj:view"))):
    """里程柱状图数据:tboil 月最大 glnum 差值(照旧 getGlchart,1 月扣上年 12 月)。"""
    _check_car_visible(db, current, cheid)
    data = {"chehao": "", "nian": year}
    maxs = dict(db.query(Tboil.yue, func.max(Tboil.glnum))
                .filter(Tboil.cheid == cheid, Tboil.nian == year)
                .group_by(Tboil.yue).all())
    prev_dec = db.query(func.max(Tboil.glnum)).filter(
        Tboil.cheid == cheid, Tboil.nian == year - 1, Tboil.yue == 12).scalar()
    prev = int(prev_dec or 0)
    has_any = bool(maxs)
    if has_any:
        car = db.get(ClChe, cheid)
        data["chehao"] = car.chehao or ""
        for m in range(1, 13):
            zd = int(maxs.get(m) or 0)
            data[f"yue{m}"] = zd - prev if zd != 0 else 0
            prev = zd if zd != 0 else prev
    return data


@router.get("/zchart")
def get_zchart(bmid: Optional[int] = None, year: int = 0, db=Depends(get_db),
               current: User = Depends(require_permission("oiltj:view"))):
    """部门年度油量/金额按油类堆叠图(照旧 GetZchart,tboil)。"""
    if year == 0:
        year = date.today().year
    q = db.query(Tboil).join(ClChe, Tboil.cheid == ClChe.id)
    if bmid:
        q = q.filter(ClChe.bmid.in_(_subtree_ids(db, bmid)))
    else:
        scope = _user_scope(db, current)
        if scope is not None:
            q = q.filter(ClChe.bmid.in_(scope))
    ls = q.filter(Tboil.nian == year).all()

    if bmid:
        label = db.get(Department, bmid)
        label = label.name if label else ""
    elif current.departments:
        label = (db.get(Department, sorted({d.id for d in current.departments})[0])).name
    else:
        label = "全部部门"

    def _sum_num(pred=None):
        vs = [t.oilnum for t in ls if (pred is None or pred(t))]
        return round(float(sum(v for v in vs if v is not None)), 2)

    def _sum_je(pred=None):
        vs = [t.oiljine for t in ls if (pred is None or pred(t))]
        return round(float(sum(v for v in vs if v is not None)), 2)

    data = {
        "kahao": label, "nian": year,
        "zong": _sum_num(), "zong_je": _sum_je(),
        "zong0": _sum_num(lambda t: t.lei == "0#"),
        "zong92": _sum_num(lambda t: t.lei == "92#"),
        "zong95": _sum_num(lambda t: t.lei == "95#"),
        "zong0_je": _sum_je(lambda t: t.lei == "0#"),
        "zong92_je": _sum_je(lambda t: t.lei == "92#"),
        "zong95_je": _sum_je(lambda t: t.lei == "95#"),
    }
    for m in range(1, 13):
        data[f"yue{m}"] = _sum_num(lambda t, mm=m: t.yue == mm)
        for lei, tag in (("0#", "0"), ("92#", "92"), ("95#", "95")):
            data[f"yue{m}_{tag}"] = _sum_num(lambda t, mm=m, L=lei: t.yue == mm and t.lei == L)
            data[f"yue{m}_{tag}_je"] = _sum_je(lambda t, mm=m, L=lei: t.yue == mm and t.lei == L)
    return data


# ==================== 月度加油统计(照旧 GetOilMonthStat) ====================
@router.get("/month-stat")
def month_stat(cheid: int, year: int = 0, db=Depends(get_db),
               current: User = Depends(require_permission("oiltj:view"))):
    """指定车辆指定年份的月度加油量/金额 + 派车次数(悬停卡片与明细弹窗共用)。"""
    car = _check_car_visible(db, current, cheid)
    year = year or date.today().year
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    oil_rows = dict(
        (m, (_n(v1), _n(v2)))
        for m, v1, v2 in (
            db.query(func.month(PlusOil.ptime),
                     func.sum(PlusOil.oill), func.sum(PlusOil.jine))
            .filter(PlusOil.cheid == cheid, PlusOil.ptime >= start, PlusOil.ptime < end)
            .group_by(func.month(PlusOil.ptime)).all()
        )
    )
    use_rows = dict(
        (m, int(n)) for m, n in (
            db.query(func.month(Yongcherc.ksdate), func.count())
            .filter(Yongcherc.cheid == cheid, Yongcherc.ksdate >= start,
                    Yongcherc.ksdate < end)
            .group_by(func.month(Yongcherc.ksdate)).all()
        )
    )
    months = []
    for m in range(1, 13):
        oil, amount = oil_rows.get(m, (0, 0))
        months.append({
            "month": m, "oil": round(oil, 2), "amount": round(amount, 2),
            "useCount": use_rows.get(m, 0),
        })
    return {"chehao": car.chehao or "", "year": year, "months": months}


# ==================== 导出 ====================
def _finance_details(db, user, p) -> list:
    """财务导出明细:PlusOil 本期记录 + 部门名/卡号/车号。

    照旧 pls.LoadSearchEntitiesTJnopage:只按用户部门作用域过滤(不吃部门下拉筛选),
    按部门、车辆、时间排序。
    """
    q = db.query(PlusOil).filter(
        PlusOil.ptime >= datetime(p["nian"], p["yue"], 1),
        PlusOil.ptime < (datetime(p["nian"] + 1, 1, 1) if p["yue"] == 12
                         else datetime(p["nian"], p["yue"] + 1, 1)))
    ids = [c.id for c in _visible_cars(db, user)]
    if ids:
        q = q.filter(PlusOil.cheid.in_(ids))
    else:
        return []
    ls = q.order_by(PlusOil.bmid, PlusOil.cheid, PlusOil.ptime).all()

    dept_names = {d.id: d.name for d in db.query(Department).all()}
    cars = {c.id: c for c in db.query(ClChe).all()}
    cards = {o.id: o for o in db.query(OilCard).all()}
    out = []
    for o in ls:
        car = cars.get(o.cheid)
        card = cards.get(o.kaid)
        out.append({
            "bumen": dept_names.get(o.bmid) or (car.bm if car else "") or "",
            "kanum": card.kanum if card else "",
            "chehao": car.chehao if car else "",
            "ptime": o.ptime.strftime("%Y-%m-%d %H:%M:%S") if o.ptime else "",
            "oill": _n(o.oill), "jine": _n(o.jine), "lei": o.lei or "",
        })
    return out


@router.get("/export-month")
def export_month(
    bmid: Optional[int] = None, clx: str = "", cheid: Optional[int] = None,
    sousou: str = "", nian: Optional[int] = None, yue: Optional[int] = None,
    px: bool = False, nooilcard: bool = False, oillie: bool = False,
    db=Depends(get_db), current: User = Depends(require_permission("oiltj:view")),
):
    """月度报表(照旧 loadexcel:tboil 月油量/月里程差口径)。"""
    p = _list_params(bmid, clx, cheid, sousou, nian, yue, px, nooilcard, oillie)
    cars = _build_list(db, current, **p)
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = []
    for i, c in enumerate(cars, start=1):
        # 月油量:tboil(照旧 loadExcel)
        oil = db.query(func.sum(Tboil.oilnum)).filter(
            Tboil.cheid == c.id, Tboil.nian == p["nian"], Tboil.yue == p["yue"]).scalar()
        # 上月底:tboil 上月 Max(1 月取当月 Min,照旧)
        if p["yue"] == 1:
            prev = db.query(func.min(Tboil.glnum)).filter(
                Tboil.cheid == c.id, Tboil.nian == p["nian"], Tboil.yue == 1).scalar()
        else:
            prev = db.query(func.max(Tboil.glnum)).filter(
                Tboil.cheid == c.id, Tboil.nian == p["nian"], Tboil.yue == p["yue"] - 1).scalar()
        cur = db.query(func.max(Tboil.glnum)).filter(
            Tboil.cheid == c.id, Tboil.nian == p["nian"], Tboil.yue == p["yue"]).scalar()
        cur, prev = int(cur or 0), int(prev or 0)
        is_gen = c.lx in ("汽油发电机", "柴油发电机", "柴、汽油发电机")
        rows.append({
            "bumen": dept_names.get(c.bmid) or c.bm or "",
            "chehao": c.chehao or "",
            "bydgls": cur, "sydgls": prev, "yssgls": cur - prev,
            "yoil": _round2(oil), "bz": c.lx if is_gen else "",
            "lx": c.lx or "", "cheyt": c.yongtu or "", "oil": c.oil or "",
        })
    dept_name = (dept_names.get(bmid) if bmid else None) or _user_dept_name(db, current)
    buf = build_month_excel(rows, dept_name, p["nian"], p["yue"])
    fn = f"{dept_name}{p['nian']}加油统计表({datetime.now():%Y-%m-%d}).xlsx"
    return Response(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": content_disposition(fn)})


def _user_dept_name(db, user) -> str:
    if user.departments:
        d = db.get(Department, sorted({x.id for x in user.departments})[0])
        return d.name if d else ""
    return "全部部门"


@router.get("/export-year")
def export_year(
    bmid: Optional[int] = None, clx: str = "", cheid: Optional[int] = None,
    sousou: str = "", nian: Optional[int] = None, yue: Optional[int] = None,
    px: bool = False, nooilcard: bool = False, oillie: bool = False,
    db=Depends(get_db), current: User = Depends(require_permission("oiltj:view")),
):
    """年度报表(照旧 loadexcelnd:tboil 年油量/年里程;金额取 PlusOil)。"""
    p = _list_params(bmid, clx, cheid, sousou, nian, yue, px, nooilcard, oillie)
    cars = _build_list(db, current, **p)
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    year_money = _year_je(db, [c.id for c in cars], p["nian"])
    rows = []
    for c in cars:
        max_cur = db.query(func.max(Tboil.glnum)).filter(
            Tboil.cheid == c.id, Tboil.nian == p["nian"]).scalar()
        max_prev = db.query(func.max(Tboil.glnum)).filter(
            Tboil.cheid == c.id, Tboil.nian == p["nian"] - 1).scalar()
        ngls = int(max_cur or 0) - int(max_prev or 0)
        noil = _round2(db.query(func.sum(Tboil.oilnum)).filter(
            Tboil.cheid == c.id, Tboil.nian == p["nian"]).scalar())
        # 照旧:年公里为 0 时百公里油耗直接填年油量(旧代码原样保留)
        lpkm = noil if ngls == 0 else round(noil / ngls * 100, 2)
        is_gen = c.lx in ("汽油发电机", "柴油发电机", "柴、汽油发电机")
        rows.append({
            "bumen": dept_names.get(c.bmid) or c.bm or "",
            "chehao": c.chehao or "", "ngls": ngls, "noil": noil,
            "lpkm_tboil": lpkm, "bz": c.lx if is_gen else "",
            "lx": c.lx or "", "cheyt": c.yongtu or "", "delf": c.delf,
            "snzdgls": int(max_prev or 0), "jnzdgls": int(max_cur or 0),
            "oil": c.oil or "",
            "chuchang": c.chuchang.strftime("%Y-%m-%d") if c.chuchang else "",
            "yoil_je": year_money.get(c.id, 0), "pailiang": c.pailiang or "",
        })
    dept_name = (dept_names.get(bmid) if bmid else None) or _user_dept_name(db, current)
    buf = build_year_excel(rows, dept_name, p["nian"])
    fn = f"{dept_name}{p['nian']}加油年度统计表({datetime.now():%Y-%m-%d}).xlsx"
    return Response(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": content_disposition(fn)})


def _year_je(db, ids, nian) -> dict:
    if not ids:
        return {}
    rows = (
        db.query(PlusOil.cheid, func.sum(PlusOil.jine))
        .filter(PlusOil.cheid.in_(ids),
                PlusOil.ptime >= datetime(nian, 1, 1),
                PlusOil.ptime < datetime(nian + 1, 1, 1))
        .group_by(PlusOil.cheid).all()
    )
    return {cid: _round2(v) for cid, v in rows}


@router.get("/export-finance")
def export_finance(
    bmid: Optional[int] = None, clx: str = "", cheid: Optional[int] = None,
    sousou: str = "", nian: Optional[int] = None, yue: Optional[int] = None,
    px: bool = False, nooilcard: bool = False, oillie: bool = False,
    db=Depends(get_db), current: User = Depends(require_permission("oiltj:view")),
):
    """财务报表(照旧 loadexcelcw:PlusOil 当期明细,双 sheet)。"""
    p = _list_params(bmid, clx, cheid, sousou, nian, yue, px, nooilcard, oillie)
    details = _finance_details(db, current, p)
    dept_name = (db.get(Department, bmid).name if bmid else None) or _user_dept_name(db, current)
    buf = build_finance_excel(details, p["nian"], p["yue"], dept_name)
    fn = finance_filename(p["nian"], p["yue"], dept_name)
    return Response(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": content_disposition(fn)})
