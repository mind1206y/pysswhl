"""车辆费用明细统计(照旧 chelfytjController 1:1 复刻)。

- 列表:cl_che 按部门子树/状态/关键字/类型/用途/非油卡筛选,四表(加油/维修/保险/
  各类费用)按日期区间逐车汇总,footer 合计对全量车(与列表行同口径随筛选变化)
- 字典:类型/用途下拉取 cl_che 历史值(照旧 Index 全量去重,不限部门)
- 导出:全量车 Excel,照旧「费用统计」模板(标题按起始年+部门名,修复旧硬编码 2023)

权限:chelfytj:view(旧系统仅菜单控制访问,init_db 登记)。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe
from app.services.chelfytj import build_excel, car_query, export_title, parse_range, summarize
from app.services.vehicle_export import content_disposition

router = APIRouter()


def _subtree_ids(db: Session, root: int) -> set:
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


def _scope_ids(db: Session, user: User, bmid: Optional[int]) -> Optional[set]:
    """生效部门集合:选了部门取其子树,否则登录人子树;超管且未选部门 → None。"""
    if bmid:
        return _subtree_ids(db, bmid)
    return dept_scope_ids(db, user)


def _user_dept_name(db: Session, user: User) -> str:
    if user.departments:
        d = db.get(Department, sorted({x.id for x in user.departments})[0])
        return d.name if d else ""
    return "全部部门"


def _list_params(**kw):
    zt = kw.get("zt") or 0
    try:
        zt = int(zt)
    except (TypeError, ValueError):
        zt = 0
    if zt not in (0, 1, 2, 3):
        zt = 0
    return dict(subtree_ids=kw["subtree_ids"], zt=zt, mohu=kw.get("sousou") or "",
                chellx=kw.get("chellx") or "", chelyt=kw.get("chelyt") or "",
                nocd=bool(kw.get("nocd")),
                _rq=kw.get("_rq") or "", _rqend=kw.get("_rqend") or "")


def _full_rows(db, current, params):
    """未分页全量行 + footer(列表与导出共用,照旧 getchl)。"""
    ksd, jsd = parse_range(params["_rq"], params["_rqend"])
    cars = car_query(db, **{k: v for k, v in params.items()
                            if not k.startswith("_")}).all()
    rows, footer = summarize(db, cars, ksd, jsd)
    return cars, rows, footer, params["_rq"]


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def get_table(
    page: int = 1,
    size: int = 20,
    bmid: Optional[int] = None,
    sousou: str = "",
    chellx: str = "",
    chelyt: str = "",
    zt: int = 0,
    nocd: bool = False,
    rq: str = "",
    rqend: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("chelfytj:view")),
):
    params = _list_params(subtree_ids=_scope_ids(db, current, bmid), zt=zt,
                          sousou=sousou, chellx=chellx, chelyt=chelyt,
                          nocd=nocd, _rq=rq, _rqend=rqend)
    cars, rows, footer, _ = _full_rows(db, current, params)
    page_rows = rows[(page - 1) * size: page * size]
    return {"total": len(cars), "rows": page_rows, "footer": footer}


@router.get("/dicts")
def dicts(db: Session = Depends(get_db),
          current: User = Depends(require_permission("chelfytj:view"))):
    """类型/用途下拉(照旧 Index:全量车辆去重排序,不限部门);部门下拉限登录人子树。"""
    lx_used = [r[0] for r in (
        db.query(ClChe.lx).filter(ClChe.lx != "")
        .distinct().order_by(ClChe.lx).all()
    )]
    yt_used = [r[0] for r in (
        db.query(ClChe.yongtu).filter(ClChe.yongtu != "")
        .distinct().order_by(ClChe.yongtu).all()
    )]
    scope = dept_scope_ids(db, current)
    dq = db.query(Department).order_by(Department.id)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    return {
        "chellx": lx_used,
        "chelyt": yt_used,
        "departments": [{"id": d.id, "name": d.name} for d in dq.all()],
        "my_dept": _user_dept_name(db, current),
    }


@router.get("/export")
def export_excel(
    bmid: Optional[int] = None,
    sousou: str = "",
    chellx: str = "",
    chelyt: str = "",
    zt: int = 0,
    nocd: bool = False,
    rq: str = "",
    rqend: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("chelfytj:view")),
):
    params = _list_params(subtree_ids=_scope_ids(db, current, bmid), zt=zt,
                          sousou=sousou, chellx=chellx, chelyt=chelyt,
                          nocd=nocd, _rq=rq, _rqend=rqend)
    _, rows, footer, rq_start = _full_rows(db, current, params)
    year = datetime.now().year
    if rq_start:
        try:
            year = datetime.strptime(rq_start, "%Y-%m-%d").year
        except ValueError:
            pass
    title = export_title(year, _user_dept_name(db, current))
    buf = build_excel(rows, footer, title)
    filename = f"费用统计_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )
