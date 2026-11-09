"""车辆维修(chelwx)公共口径:筛选条件、维修单行组装、配件/工时费回算。

照旧 clwxdanService.LoadSearchEntities:
- 日期默认取当前年度;只有起止都传才按区间(结束日 +1 天,左闭右开)
- 关键字=车号/维修项目/维修单位模糊,或总金额精确
- 部门按登录人部门子树过滤(超管不限)
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, ClWxdan, ClWxdw, ClWxmx, ClWxdTP

LX_OPTIONS = ["维修", "保养", "年检"]
PJORGS_OPTIONS = ["配件费", "工时费"]
ZK_OPTIONS = [
    {"value": "1", "label": "无折扣"},
    {"value": "0.85", "label": "中一 0.85 折"},
    {"value": "0.78", "label": "安恒 0.78 折"},
    {"value": "0.68", "label": "厦贸 0.68 折"},
]


def _f(v):
    if v is None:
        return None
    return float(v)


def _round2(v) -> float:
    if v is None:
        v = 0
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _d(v):
    return v.strftime("%Y-%m-%d") if isinstance(v, (date, datetime)) else None


def _dt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else None


def subtree_ids(db: Session, root_id: int) -> list:
    """部门自身 + 全部子孙部门 id。"""
    from app.models.user import Department

    ids = {root_id}
    while True:
        rows = db.query(Department.id).filter(
            Department.parent_id.in_(ids), ~Department.id.in_(ids)
        ).all()
        if not rows:
            break
        ids |= {r[0] for r in rows}
    return list(ids)


def date_window(rq: Optional[date], rqend: Optional[date]):
    """返回 [start, end) 左闭右开;无区间取当前自然年。"""
    if rq and rqend:
        return rq, rqend + timedelta(days=1)
    if rq:
        return rq, date(rq.year, 12, 31) + timedelta(days=1)
    today = date.today()
    return date(today.year, 1, 1), date(today.year, 12, 31) + timedelta(days=1)


def order_query(
    db: Session, user, rq: Optional[date] = None, rqend: Optional[date] = None,
    bmid: Optional[int] = None, cheid: Optional[int] = None,
    wxdw: Optional[int] = None, keyword: str = "",
):
    start, end = date_window(rq, rqend)
    q = db.query(ClWxdan).join(ClChe, ClWxdan.cheid == ClChe.id)
    q = q.filter(ClWxdan.jcriqi >= start, ClWxdan.jcriqi < end)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    if bmid:
        q = q.filter(ClChe.bmid.in_(subtree_ids(db, bmid)))
    if cheid:
        q = q.filter(ClWxdan.cheid == cheid)
    if wxdw:
        q = q.filter(ClWxdan.wxdw == wxdw)
    kw = (keyword or "").strip()
    if kw:
        q = q.outerjoin(ClWxdw, ClWxdan.wxdw == ClWxdw.id)
        cond = or_(
            ClChe.chehao.contains(kw),
            ClWxdan.xiangmu.contains(kw),
            ClWxdw.dwname.contains(kw),
        )
        try:
            cond = or_(cond, ClWxdan.jine == Decimal(kw))
        except (InvalidOperation, ValueError):
            pass
        q = q.filter(cond)
    return q, start, end


def build_order_rows(db: Session, orders: list) -> list:
    if not orders:
        return []
    ids = [o.id for o in orders]
    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_({o.cheid for o in orders if o.cheid})).all()}
    units = {u.id: u for u in db.query(ClWxdw).filter(
        ClWxdw.id.in_({o.wxdw for o in orders if o.wxdw})
    ).all()}
    tps = {}
    for tp in db.query(ClWxdTP).filter(ClWxdTP.wxdid.in_(ids)).order_by(ClWxdTP.id).all():
        tps.setdefault(tp.wxdid, []).append(tp.to_dict())
    counts = dict(
        db.query(ClWxmx.wxdid, func.count(ClWxmx.id))
        .filter(ClWxmx.wxdid.in_(ids)).group_by(ClWxmx.wxdid).all()
    )
    names = dept_name_map(db)

    rows = []
    for o in orders:
        car = cars.get(o.cheid)
        unit = units.get(o.wxdw)
        jine = o.jine or 0
        gsf = o.gongshifei or 0
        pjf = o.peijianfei or 0
        rows.append({
            "ID": o.id, "id": o.id,
            "lx": o.lx or "", "jcriqi": _d(o.jcriqi),
            "bm": (names.get(car.bmid) if car and car.bmid else None) or (car.bm if car else "") or "",
            "bxren": o.bxren or "",
            "chehao": car.chehao if car else "",
            "xiangmu": o.xiangmu or "",
            "jine": _f(jine), "zk": _f(o.zk),
            "cllx": car.lx if car else "",
            "gonglinum": o.gonglinum,
            "dwname": unit.dwname if unit else "",
            "gongshifei": _f(gsf), "peijianfei": _f(pjf),
            "sx": _round2(jine - gsf - pjf),
            "username": o.username or "",
            "djriqi": _dt(o.djriqi),
            "tps": tps.get(o.id, []),
            "sp": bool(o.sp) if o.sp is not None else False,
            "spren": o.spren or "", "sptime": _dt(o.sptime),
            "cheid": o.cheid, "wxdw": o.wxdw,
            "ccriqi": _d(o.ccriqi),
            "detail_count": counts.get(o.id, 0),
            "jiashiyuan": car.jiashiyuan if car else "",
            "telphone": car.telphone if car else "",
            "pinpai": car.pinpai if car else "",
            "chuchang": _d(car.chuchang) if car else None,
        })
    return rows


def recompute_fees(db: Session, order: ClWxdan):
    """维修明细增删改后回写维修单的工时费/配件费(照旧 jspjgs)。"""
    rows = db.query(ClWxmx.pjorgs, func.coalesce(func.sum(ClWxmx.zonge), 0)).filter(
        ClWxmx.wxdid == order.id
    ).group_by(ClWxmx.pjorgs).all()
    fees = {k: v for k, v in rows}
    order.gongshifei = fees.get("工时费", 0)
    order.peijianfei = fees.get("配件费", 0)


def remaining(db: Session, order: ClWxdan, ze=0, mxid: Optional[int] = None) -> float:
    """尚需金额:总金额 - 已有明细合计(- 本次填报 + 被修改明细原金额)。"""
    total = db.query(func.coalesce(func.sum(ClWxmx.zonge), 0)).filter(
        ClWxmx.wxdid == order.id
    ).scalar() or 0
    old = 0
    if mxid:
        mx = db.get(ClWxmx, mxid)
        old = mx.zonge if mx and mx.zonge is not None else 0
    return _round2((order.jine or 0) - total + old - (ze or 0))


def has_perm(user, code: str) -> bool:
    if user.is_superuser:
        return True
    return any(p.code == code for role in user.roles for p in role.permissions)
