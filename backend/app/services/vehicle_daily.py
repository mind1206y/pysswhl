"""日常用车公共逻辑(照旧 yongcherichangController / yongchercService)。

- 查询筛选:按车辆部门子树、车号、司机、日期区间、模糊关键字
- 列表行组装:补车号/类型/部门/图片/里程数
- 异常里程检测:完全沿用旧系统分段 + 自校验 + 段内连续性算法
- 导出辅助:重叠里程、空挡里程的行筛选
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.user import Department
from app.models.vehicle import ClChe, Tboil, Yongcherc, YongchercTP


# ===== 部门作用域 =====
def dept_subtree_ids(db: Session, dept_id: int) -> set:
    """某部门及其全部子部门 id(照旧 bmcj 层级码前缀语义)。"""
    ids = {int(dept_id)}
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


def effective_scope(db: Session, user, dept_id: Optional[int] = None) -> Optional[set]:
    """用户可见部门集合;指定部门时再取该部门子树,与用户作用域取交集。"""
    user_scope = dept_scope_ids(db, user)
    if dept_id:
        scope = dept_subtree_ids(db, dept_id)
        if user_scope is not None:
            scope &= user_scope
        return scope
    return user_scope


# ===== 日期区间(照旧:默认整年;同时给起止时结束日包含当天) =====
def date_bounds(
    date_from: Optional[date], date_to: Optional[date], year: Optional[int] = None
):
    year = year or (date_from.year if date_from else (date_to.year if date_to else date.today().year))
    if date_from and date_to:
        start = datetime.combine(date_from, time.min)
        end = datetime.combine(date_to + timedelta(days=1), time.min)
    elif date_from:
        start = datetime.combine(date_from, time.min)
        end = datetime(date_from.year + 1, 1, 1)
    elif date_to:
        start = datetime(date_to.year, 1, 1)
        end = datetime.combine(date_to + timedelta(days=1), time.min)
    else:
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
    return start, end


def daily_conditions(
    db: Session,
    user,
    *,
    keyword: str = "",
    dept_id: Optional[int] = None,
    car_id: Optional[int] = None,
    driver: str = "",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    year: Optional[int] = None,
):
    start, end = date_bounds(date_from, date_to, year)
    conds = [Yongcherc.ksdate >= start, Yongcherc.ksdate < end]
    scope = effective_scope(db, user, dept_id)
    if scope is not None:
        conds.append(ClChe.bmid.in_(scope))
    if car_id:
        conds.append(Yongcherc.cheid == car_id)
    if (driver or "").strip():
        conds.append(Yongcherc.sj == driver.strip())
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        conds.append(or_(
            ClChe.chehao.like(like),
            Yongcherc.didian.like(like),
            Yongcherc.sj.like(like),
            Yongcherc.yuanyin.like(like),
        ))
    return conds


def daily_query(db: Session, user, **filters):
    return (
        db.query(Yongcherc)
        .join(ClChe, ClChe.id == Yongcherc.cheid)
        .filter(*daily_conditions(db, user, **filters))
    )


# ===== 行组装 =====
def record_row(rec: Yongcherc, car: Optional[ClChe], bumen: str,
               tps: Optional[list] = None, abnormal_reason: str = "") -> dict:
    d = rec.to_dict()
    d.update({
        "ID": rec.id,
        "chehao": car.chehao if car else "",
        "lx": car.lx if car else "",
        "yongtu": car.yongtu if car else "",
        "bumen": bumen,
        "AbnormalReason": abnormal_reason,
        "tps": tps or [],
    })
    return d


def build_rows(db: Session, records: list, with_images: bool = True) -> list:
    car_ids = {r.cheid for r in records if r.cheid}
    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_(car_ids)).all()} if car_ids else {}
    names = dept_name_map(db)

    images = {}
    if with_images and records:
        ids = [r.id for r in records]
        for img in db.query(YongchercTP).filter(YongchercTP.yongchercid.in_(ids)).all():
            images.setdefault(img.yongchercid, []).append(img.to_dict())

    return [
        record_row(
            r,
            cars.get(r.cheid),
            names.get(cars[r.cheid].bmid, "") if cars.get(r.cheid) and cars[r.cheid].bmid else
            (cars[r.cheid].bm if cars.get(r.cheid) else ""),
            images.get(r.id, []),
        )
        for r in records
    ]


def latest_car_info(db: Session, car: ClChe) -> dict:
    last = (
        db.query(Yongcherc)
        .filter(Yongcherc.cheid == car.id)
        .order_by(Yongcherc.jsgl.is_(None), Yongcherc.jsgl.desc(), Yongcherc.id.desc())
        .first()
    )
    return {
        "gls": last.jsgl if last and last.jsgl is not None else 0,
        "tingfang": (last.tingfang or "") if last else "",
        "shenhe": car.shenheren or "",
        "shenpi": "",
    }


def scope_cars(db: Session, user) -> list:
    q = db.query(ClChe).filter(ClChe.delf == 1)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    return q.order_by(ClChe.bmid, ClChe.chehao).all()


def driver_counts(db: Session, user, **filters) -> list:
    filters["driver"] = ""
    conds = daily_conditions(db, user, **filters)
    rows = (
        db.query(Yongcherc.sj, func.count().label("n"))
        .join(ClChe, ClChe.id == Yongcherc.cheid)
        .filter(*conds, Yongcherc.sj.isnot(None), Yongcherc.sj != "")
        .group_by(Yongcherc.sj)
        .order_by(func.count().desc(), Yongcherc.sj.asc())
        .all()
    )
    return [{"name": name, "count": int(n)} for name, n in rows]


def reason_options(db: Session, user) -> list:
    scope = dept_scope_ids(db, user)
    q = (
        db.query(Yongcherc.yuanyin, func.count().label("n"))
        .join(ClChe, ClChe.id == Yongcherc.cheid)
        .filter(Yongcherc.yuanyin.isnot(None), Yongcherc.yuanyin != "")
    )
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    rows = q.group_by(Yongcherc.yuanyin).order_by(func.count().desc()).limit(500).all()
    return [name for name, _n in rows]


# ===== 导出:重叠里程 / 空挡里程(照旧 LoadSearchEntities2/3) =====
def compute_overlap_rows(rows: list) -> list:
    grouped = {}
    for row in rows:
        if row.get("ksgl") is None or row.get("jsgl") is None:
            continue
        grouped.setdefault(row.get("cheid"), []).append(row)

    out = []
    for items in grouped.values():
        for row in items:
            if row["ksgl"] >= row["jsgl"]:
                out.append(row)
                continue
            for other in items:
                if other is row:
                    continue
                if other["jsgl"] is not None and row["ksgl"] < other["jsgl"] <= row["jsgl"]:
                    out.append(row)
                    break
    return out


def compute_gap_rows(rows: list) -> list:
    grouped = {}
    for row in rows:
        if row.get("jsgl") is None:
            continue
        grouped.setdefault(row.get("cheid"), []).append(row)

    out = []
    for items in grouped.values():
        for row in items:
            nxt = None
            for other in items:
                if other is row or other.get("ksgl") is None:
                    continue
                if other["ksgl"] >= row["jsgl"]:
                    if nxt is None or other["ksgl"] < nxt["ksgl"]:
                        nxt = other
            if nxt is not None and nxt["ksgl"] - row["jsgl"] > 2:
                out.append(row)
    return out


# ===== 异常里程检测(照旧 FindAbnormalRecordsForVehicle 等) =====
def _self_valid(r: Yongcherc) -> bool:
    if r.ksgl is None or r.jsgl is None:
        return False
    if r.ksdate is not None and r.jsdate is not None and r.ksdate > r.jsdate:
        return False
    if r.jsgl < r.ksgl:
        return False
    single = r.jsgl - r.ksgl
    return 0 <= single <= 800


def _continuous(prev: Yongcherc, curr: Yongcherc) -> bool:
    if curr.ksgl is None or prev.jsgl is None:
        return False
    gap = curr.ksgl - prev.jsgl
    return -2 <= gap <= 5000


def _self_invalid_reason(r: Yongcherc) -> str:
    if r.ksgl is None or r.jsgl is None:
        return "缺少开始或结束里程"
    if r.ksdate is not None and r.jsdate is not None and r.ksdate > r.jsdate:
        return "开始时间晚于结束时间"
    if r.jsgl < r.ksgl:
        return "结束里程小于开始里程"
    single = r.jsgl - r.ksgl
    if single < 0:
        return "里程差为负数"
    if single > 800:
        return f"单次里程{int(single)}公里，超过上限800公里"
    return "里程数据异常"


def find_abnormal_for_vehicle(records: list) -> list:
    if not records:
        return []

    segments = []
    current = []
    for r in records:
        if not current:
            current.append(r)
            continue
        if _continuous(current[-1], r):
            current.append(r)
        else:
            segments.append(current)
            current = [r]
    if current:
        segments.append(current)

    abnormal_ids = set()
    out = []

    for seg_idx, seg in enumerate(segments):
        if len(seg) == 1 and seg_idx > 0:
            rec = seg[0]
            if _self_valid(rec):
                out.append((rec, "里程跳跃/回退后无连续记录，无法确认为有效新段"))
                abnormal_ids.add(rec.id)
                continue

        last_valid = None
        for r in seg:
            if r.id in abnormal_ids:
                continue

            reason = None
            if not _self_valid(r):
                reason = _self_invalid_reason(r)
            elif last_valid is not None and not _continuous(last_valid, r):
                reason = "段内里程不连续（与上条正常记录矛盾）"
            elif last_valid is not None:
                gap = (r.ksgl or 0) - (last_valid.jsgl or 0)
                if gap < -2:
                    reason = (
                        f"段内异常回退：开始公里({r.ksgl})低于上次结束"
                        f"({last_valid.jsgl})，差值{gap}公里"
                    )

            if reason is not None:
                out.append((r, reason))
                abnormal_ids.add(r.id)
            else:
                last_valid = r

    return out


def find_abnormal_rows(db: Session, user) -> list:
    scope = dept_scope_ids(db, user)
    q = (
        db.query(Yongcherc)
        .join(ClChe, ClChe.id == Yongcherc.cheid)
        .filter(Yongcherc.ksgl.isnot(None), Yongcherc.jsgl.isnot(None))
    )
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    records = q.order_by(ClChe.id, Yongcherc.ksdate, Yongcherc.jsdate).all()

    grouped = {}
    for rec in records:
        grouped.setdefault(rec.cheid, []).append(rec)

    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_(grouped.keys())).all()} if grouped else {}
    names = dept_name_map(db)
    out = []
    for cheid, items in grouped.items():
        car = cars.get(cheid)
        bumen = ""
        if car:
            bumen = names.get(car.bmid, "") or car.bm or ""
        for rec, reason in find_abnormal_for_vehicle(items):
            out.append(record_row(rec, car, bumen, abnormal_reason=reason))
    out.sort(key=lambda r: (r.get("chehao") or "", r.get("id") or 0))
    return out


# ===== 提取整年公里数(照旧 Dogonglinum) =====
def extract_year_mileage(db: Session, user, year: Optional[int] = None) -> dict:
    year = year or date.today().year
    q = db.query(ClChe).filter(ClChe.delf != 0)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    cars = q.all()
    names = dept_name_map(db)
    now = datetime.now()
    created = 0

    for car in cars:
        bumen = names.get(car.bmid, "") or car.bm or ""
        for month in range(1, 13):
            start = datetime(year, month, 1)
            end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
            maxgl = (
                db.query(func.max(Yongcherc.jsgl))
                .filter(Yongcherc.cheid == car.id, Yongcherc.jsdate >= start, Yongcherc.jsdate < end)
                .scalar()
            )
            if not maxgl:
                continue
            oildate = datetime(year, month, monthrange(year, month)[1])
            exists = (
                db.query(Tboil.id)
                .filter(Tboil.cheid == car.id, Tboil.oildate == oildate, Tboil.glnum == maxgl)
                .first()
            )
            if exists:
                continue
            db.add(Tboil(
                cheid=car.id, oildate=oildate, oilnum=0, lei=car.oil or "",
                username=f"{user.username}导入", riqi=now, glnum=maxgl, bumen=bumen,
                oiljine=0, nian=year, yue=month,
            ))
            created += 1

        prev_start = datetime(year - 1, 1, 1)
        prev_end = datetime(year, 1, 1)
        prevmax = (
            db.query(func.max(Yongcherc.jsgl))
            .filter(Yongcherc.cheid == car.id, Yongcherc.jsdate >= prev_start,
                    Yongcherc.jsdate < prev_end)
            .scalar()
        )
        if not prevmax:
            continue
        rec = (
            db.query(Yongcherc)
            .filter(Yongcherc.cheid == car.id, Yongcherc.jsgl == prevmax,
                    Yongcherc.jsdate >= prev_start, Yongcherc.jsdate < prev_end)
            .order_by(Yongcherc.jsdate.asc())
            .first()
        )
        if rec is None or rec.jsdate is None:
            continue
        exists = db.query(Tboil.id).filter(Tboil.cheid == car.id, Tboil.glnum == prevmax).first()
        if exists:
            continue
        db.add(Tboil(
            cheid=car.id, oildate=rec.jsdate, oilnum=0, lei=car.oil or "",
            username=f"{user.username}导入", riqi=now, glnum=prevmax, bumen=bumen,
            oiljine=0, nian=rec.jsdate.year, yue=rec.jsdate.month,
        ))
        created += 1

    db.commit()
    return {"success": True, "year": year, "created": created}

