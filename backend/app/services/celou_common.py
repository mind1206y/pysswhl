"""测漏成果公共逻辑:统一筛选、计算字段、字典与统计聚合。

旧系统把筛选条件存在 TempData["tmpceloutb"] 里,列表/图表/导出隐式共享。
新系统改为显式筛选 DTO(所有接口都回传同一组 query 参数),避免口径漂移。
"""

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from fastapi import Query
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.celou import CelouTb, CLdui, COORDINATE_TYPES, EXPORT_COLUMNS
from app.models.user import Department, User

MOHU_FIELDS = ("didian", "gongdan", "guanjing", "yy", "dingliang", "dwwucha", "guancai")
ZERO = Decimal("0")


def celou_params(
    page: int = Query(1, ge=1),
    rows: int = Query(20, ge=1, le=500),
    bumen: Optional[str] = Query(None, description="部门 id(新 departments.id)"),
    filterUsername: Optional[str] = Query(None),
    yudingliangFlag: Optional[bool] = Query(None),
    showDuplicate: Optional[bool] = Query(None),
    mohu: Optional[str] = Query(None),
    nd: Optional[int] = Query(None, description="年度,0/空=不限"),
    mon: Optional[str] = Query(None, description="月份,-1/空=不限"),
    celoudw: Optional[str] = Query(None, description="测漏单位"),
    gjdayu: Optional[str] = Query(None, description="管径≥"),
    gjxiaoyu: Optional[str] = Query(None, description="管径≤"),
    guanjing: Optional[str] = Query(None, description="管径精确/包含"),
    xiaolouliang: Optional[str] = Query(None),
    dalouliang: Optional[str] = Query(None),
    px: Optional[bool] = Query(None, description="排除配合定点及管线探测"),
    px2: Optional[bool] = Query(None, description="仅配合定点及管线探测"),
) -> dict:
    """列表/图表/导出/热力图共用的筛选参数(命名照旧 gettable)。"""
    return {
        "page": page, "rows": rows, "bumen": bumen,
        "filterUsername": filterUsername, "yudingliangFlag": yudingliangFlag,
        "showDuplicate": showDuplicate, "mohu": (mohu or "").strip(),
        "nd": nd or 0, "mon": mon, "celoudw": celoudw,
        "gjdayu": gjdayu, "gjxiaoyu": gjxiaoyu, "guanjing": guanjing,
        "xiaolouliang": xiaolouliang, "dalouliang": dalouliang,
        "px": bool(px), "px2": bool(px2),
    }


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _dec(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (TypeError, ValueError, ArithmeticError):
        return None


def build_query(db: Session, p: dict, user: User):
    """照 celouTbService.LoadSearchEntities 逐条复刻,并补新系统部门数据权限。"""
    q = db.query(CelouTb)
    if p.get("nd"):
        q = q.filter(CelouTb.nian == p["nd"])

    # 数据权限:普通用户只能看本人部门子树下的记录
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(CelouTb.bmid.in_(scope))

    if p.get("mohu"):
        kw = f"%{p['mohu']}%"
        q = q.filter(or_(*[getattr(CelouTb, f).like(kw) for f in MOHU_FIELDS]))

    bid = _int(p.get("bumen"))
    if bid:
        q = q.filter(CelouTb.bmid == bid)

    gj = _int(p.get("gjdayu"))
    if gj is not None:
        q = q.filter(or_(CelouTb.gjsmall >= gj, CelouTb.gjbig >= gj))
    gjxy = _int(p.get("gjxiaoyu"))
    if gjxy is not None:
        q = q.filter(or_(CelouTb.gjsmall <= gjxy, CelouTb.gjbig <= gjxy))

    if p.get("celoudw"):
        q = q.filter(CelouTb.celoudw == p["celoudw"])
    if p.get("guanjing"):
        q = q.filter(CelouTb.guanjing.like(f"%{p['guanjing']}%"))

    xiao = _dec(p.get("xiaolouliang"))
    if xiao is not None:
        q = q.filter(CelouTb.louliang >= xiao)
    da = _dec(p.get("dalouliang"))
    if da is not None:
        q = q.filter(CelouTb.louliang <= da)

    mon = p.get("mon")
    if mon and str(mon) not in ("", "-1", "0"):
        m = _int(mon)
        if m:
            q = q.filter(CelouTb.yue == m)

    if p.get("px"):
        q = q.filter(~CelouTb.yy.like("%定点%"), ~CelouTb.yy.like("%管线%"))
    if p.get("px2"):
        q = q.filter(or_(CelouTb.yy.like("%定点%"), CelouTb.yy.like("%管线%")))
    if p.get("filterUsername"):
        q = q.filter(CelouTb.username == p["filterUsername"])
    if p.get("yudingliangFlag"):
        q = q.filter(CelouTb.yudingliang.is_(True))

    if p.get("showDuplicate"):
        dup = (q.with_entities(CelouTb.gongdan)
               .filter(CelouTb.gongdan.isnot(None), CelouTb.gongdan != "")
               .group_by(CelouTb.gongdan)
               .having(func.count() > 1))
        q = q.filter(CelouTb.gongdan.in_(dup))

    return q


def sorted_query(q, duplicate: bool = False):
    if duplicate:
        return q.order_by(CelouTb.gongdan.asc(), CelouTb.nian.desc(),
                          CelouTb.yue.desc(), CelouTb.id.desc())
    return q.order_by(CelouTb.nian.desc(), CelouTb.yue.desc(), CelouTb.id.desc())


def qjll_days(louliang) -> int:
    """≥8 m³/h 按 60 天,0.5~8 按 90 天,<0.5 不计量。"""
    return 60 if Decimal(str(louliang)) >= Decimal("8") else 90


def calc_qjll(louliang):
    if louliang is None:
        return None
    v = Decimal(str(louliang))
    if v < Decimal("0.5"):
        return None
    days = qjll_days(v)
    return (v * 24 * days * Decimal("0.6")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def calc_qjll_process(louliang):
    if louliang is None:
        return ""
    v = Decimal(str(louliang))
    if v < Decimal("0.5"):
        return ""
    days = qjll_days(v)
    return f"{v:.2f}×24×{days}×0.6={calc_qjll(v):.2f}"


def footer(q) -> dict:
    """全量合计(分页之前),照旧 gzsh.tongjijine / tongjiQjll。"""
    total_louliang = q.with_entities(func.coalesce(func.sum(CelouTb.louliang), 0)).scalar()
    expr = case(
        (CelouTb.louliang >= 8, func.round(CelouTb.louliang * 24 * 60 * Decimal("0.6"), 2)),
        (CelouTb.louliang >= Decimal("0.5"), func.round(CelouTb.louliang * 24 * 90 * Decimal("0.6"), 2)),
        else_=0,
    )
    total_qjll = q.with_entities(func.coalesce(func.sum(expr), 0)).scalar()
    return {
        "louliang": round(float(total_louliang or 0), 2),
        "qjll": round(float(total_qjll or 0), 2),
    }


def row_to_dict(row: CelouTb, dept_names: dict) -> dict:
    d = row.to_dict()
    d["xsbm"] = dept_names.get(row.bmid) or row.bm or ""
    d["qjll"] = float(calc_qjll(row.louliang)) if calc_qjll(row.louliang) is not None else None
    d["qjllProcess"] = calc_qjll_process(row.louliang)
    return d


def dicts(db: Session, user: User) -> dict:
    """首页下拉数据:部门/年度/月份/管径/队伍/上传人/坐标类型。"""
    scope = dept_scope_ids(db, user)
    dq = db.query(Department.id, Department.name)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    depts = [{"id": i, "name": n} for i, n in dq.order_by(Department.id).all()]

    years = [r[0] for r in db.query(CelouTb.nian).filter(CelouTb.nian.isnot(None))
             .distinct().order_by(CelouTb.nian.desc()).all()]
    diameters = [r[0] for r in db.query(CelouTb.gjsmall).filter(CelouTb.gjsmall.isnot(None))
                 .distinct().order_by(CelouTb.gjsmall.desc()).all()]
    teams = [r[0] for r in db.query(CLdui.coname).order_by(CLdui.id).all()]
    usernames = [r[0] for r in db.query(CelouTb.username)
                 .filter(CelouTb.username.isnot(None), CelouTb.username != "")
                 .distinct().order_by(CelouTb.username).all()]
    return {
        "departments": depts,
        "years": years,
        "current_year": years[0] if years else None,
        "diameters": diameters,
        "teams": teams,
        "usernames": usernames,
        "coordinate_types": COORDINATE_TYPES,
        "months_of_year": {y: [r[0] for r in db.query(CelouTb.yue)
                               .filter(CelouTb.nian == y, CelouTb.yue.isnot(None))
                               .distinct().order_by(CelouTb.yue).all()] for y in years},
        "export_columns": EXPORT_COLUMNS,
    }


def get_months(db: Session, year: int) -> list:
    if not year:
        return [{"value": -1, "label": "==请选择月份=="}] + [
            {"value": m, "label": f"{m}月"} for m in range(1, 13)]
    rows = (db.query(CelouTb.yue).filter(CelouTb.nian == year, CelouTb.yue.isnot(None))
            .distinct().order_by(CelouTb.yue).all())
    return [{"value": -1, "label": "==请选择月份=="}] + [
        {"value": r[0], "label": f"{r[0]}月"} for r in rows]


def tbp(now, prev):
    """同比/环比:旧 Tbp(nw,pw) —— pw=0 时返回 100。"""
    n, p = float(now or 0), float(prev or 0)
    if n == 0:
        return 0.0
    if p == 0:
        return 100.0
    return round((n - p) / p * 100, 2)


def chart_tb(db: Session, p: dict, user: User, year: int) -> dict:
    """测定漏量/测漏点数的同比环比(照 GetTBchart 的 viewHf)。"""
    def yearly(y):
        pp = dict(p, nd=y)
        q = build_query(db, pp, user)
        sums = dict((r[0], float(r[1] or 0)) for r in
                    q.with_entities(CelouTb.yue, func.sum(CelouTb.louliang))
                    .group_by(CelouTb.yue).all())
        counts = dict((r[0], int(r[1])) for r in
                      q.with_entities(CelouTb.yue, func.count())
                      .group_by(CelouTb.yue).all())
        return sums, counts

    cur_s, cur_c = yearly(year)
    prev_s, prev_c = yearly(year - 1)
    out = {"nian": year, "qnian": year - 1}
    for m in range(1, 13):
        out[f"yue{m}"] = round(cur_s.get(m, 0), 2)
        out[f"qyue{m}"] = round(prev_s.get(m, 0), 2)
        out[f"dyue{m}"] = cur_c.get(m, 0)
        out[f"dqyue{m}"] = prev_c.get(m, 0)
        out[f"tbyue{m}"] = tbp(cur_s.get(m, 0), prev_s.get(m, 0))
        out[f"dtbyue{m}"] = tbp(cur_c.get(m, 0), prev_c.get(m, 0))
        out[f"hbyue{m}"] = tbp(cur_s.get(m, 0), prev_s.get(12, 0) if m == 1 else cur_s.get(m - 1, 0))
        out[f"dhbyue{m}"] = tbp(cur_c.get(m, 0), prev_c.get(12, 0) if m == 1 else cur_c.get(m - 1, 0))
    out.update({
        "zong": round(sum(cur_s.values()), 2), "qzong": round(sum(prev_s.values()), 2),
        "dzong": sum(cur_c.values()), "dqzong": sum(prev_c.values()),
        "tbzong": tbp(sum(cur_s.values()), sum(prev_s.values())),
        "dtbzong": tbp(sum(cur_c.values()), sum(prev_c.values())),
    })
    return out


def normalize_guancai(value: str) -> str:
    s = (value or "").strip()
    if s in ("铸铁", "球墨"):
        return "球墨铸铁"
    if s in ("镀锌", "钢"):
        return "镀锌钢"
    return s.upper() or "未知管材"


def chart_pie(db: Session, p: dict, user: User, kind: str, year: int) -> list:
    pp = dict(p, nd=year)
    if kind in ("bumen", "duiwu"):
        pp = dict(pp, bumen=None)  # 旧系统饼图清掉部门筛选,否则只有一个扇区
    if kind == "duiwu":
        pp = dict(pp, celoudw=None)
    q = build_query(db, pp, user)

    if kind == "bumen":
        names = dict(db.query(Department.id, Department.name).all())
        rows = (q.with_entities(CelouTb.bmid, func.sum(CelouTb.louliang), func.count())
                .group_by(CelouTb.bmid).all())
        data = [{"name": names.get(b) or "未分配部门",
                 "louliang": round(float(v or 0), 2), "count": n} for b, v, n in rows]
    elif kind == "guanjing":
        rows = (q.with_entities(CelouTb.gjsmall, func.sum(CelouTb.louliang), func.count())
                .group_by(CelouTb.gjsmall).all())
        data = [{"name": f"DN{v}" if v is not None else "未知管径",
                 "louliang": round(float(s or 0), 2), "count": n} for v, s, n in rows]
    elif kind == "guancai":
        rows = (q.with_entities(CelouTb.guancai, func.sum(CelouTb.louliang), func.count())
                .group_by(CelouTb.guancai).all())
        merged = {}
        for v, s, n in rows:
            key = normalize_guancai(v)
            cur = merged.setdefault(key, {"name": key, "louliang": 0.0, "count": 0})
            cur["louliang"] += float(s or 0)
            cur["count"] += n
        data = [{**v, "louliang": round(v["louliang"], 2)} for v in merged.values()]
    else:  # duiwu
        rows = (q.with_entities(CelouTb.celoudw, func.sum(CelouTb.louliang), func.count())
                .group_by(CelouTb.celoudw).all())
        data = [{"name": v or "未记录队伍", "louliang": round(float(s or 0), 2),
                 "count": n} for v, s, n in rows]
    return sorted(data, key=lambda x: -x["louliang"])


def chart_bar(db: Session, p: dict, user: User, kind: str, value: float) -> dict:
    """按年度求平均漏量(照 GetGuanjingBarChart / GetLouliangBarChart)。"""
    pp = dict(p, nd=0)  # 旧系统柱状图查全表,不限年度
    q = build_query(db, pp, user)
    if kind == "guanjing":
        q = q.filter(CelouTb.gjsmall <= int(value))
    else:
        q = q.filter(CelouTb.louliang <= value)
    rows = (q.with_entities(CelouTb.nian, func.avg(CelouTb.louliang), func.count())
            .group_by(CelouTb.nian).order_by(CelouTb.nian).all())
    return {
        "years": [r[0] for r in rows],
        "avgs": [round(float(r[1] or 0), 2) for r in rows],
        "counts": [r[2] for r in rows],
        "total": sum(r[2] for r in rows),
    }


def export_row(row: CelouTb, idx: int, dept_names: dict) -> list:
    q = calc_qjll(row.louliang)
    return [
        idx, row.gongdan or "",
        row.bgdate.strftime("%Y/%m/%d") if row.bgdate else "",
        row.xiufudate.strftime("%Y/%m/%d") if row.xiufudate else "",
        row.didian or "", row.guanjing or "", row.guancai or "", row.yy or "",
        row.dwwucha or "", row.dingliang or "", float(row.louliang or 0),
        dept_names.get(row.bmid) or row.bm or "", row.celoudw or "",
        row.username or "", row.nian, row.yue,
        float(q) if q is not None else "", row.zuobiao_leibie or "",
        float(row.zuobiao_jingdu) if row.zuobiao_jingdu is not None else "",
        float(row.zuobiao_weidu) if row.zuobiao_weidu is not None else "",
        calc_qjll_process(row.louliang),
    ]
