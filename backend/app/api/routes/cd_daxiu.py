"""传导大修/更新记录(照旧 CDdaxiuController 1:1 复刻)。

- 列表:报表日期 + 部门子树 + 部门下拉 + 关键字(内容/存放点/施工员/备注)
- 增删改:添加/编辑/打开编辑弹窗受锁定限制;删除照旧**不检查锁定**,但仍限本月且限本人
- 导出:当前报表日期筛选全量(忽略分页),照旧 NPOI 模板两级表头
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.cd import CDDaxiu
from app.models.user import User
from app.services.cd_common import (
    bt_title, daxiu_row, default_bmid, dept_names, display_name,
    ensure_current_month, ensure_not_locked, ensure_owner, parse_date, report_date,
    scoped_query,
)
from app.services.cd_excel import build_daxiu_excel, content_disposition

router = APIRouter()


class DaxiuIn(BaseModel):
    bbdate: Optional[str] = None
    daxiudate: Optional[str] = None
    lb: Optional[str] = None
    nr: Optional[str] = None
    gdh: Optional[str] = None
    gdkj: Optional[str] = None
    xbqkj: Optional[str] = None
    fmkj: Optional[str] = None
    xfskj: Optional[str] = None
    num: Optional[int] = None
    bz: Optional[str] = None
    cfd: Optional[str] = None
    sgy: Optional[str] = None
    sgtel: Optional[str] = None


def _get_or_404(db: Session, rid: int) -> CDDaxiu:
    row = db.get(CDDaxiu, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="大修记录不存在")
    return row


def _validate(data: DaxiuIn):
    if not (data.nr or "").strip():
        raise HTTPException(status_code=400, detail="请输入项目内容")
    if not (data.gdh or "").strip():
        raise HTTPException(status_code=400, detail="请输入工单号")
    d = parse_date(data.daxiudate)
    if d is None:
        raise HTTPException(status_code=400, detail="请选择大修日期")
    if data.num is not None and int(data.num) < 0:
        raise HTTPException(status_code=400, detail="数量不能为负数")
    return d


def _apply(row: CDDaxiu, data: DaxiuIn, daxiudate):
    row.bbdate = parse_date(data.bbdate) or report_date()
    row.daxiudate = daxiudate
    for field in ("lb", "nr", "gdh", "gdkj", "xbqkj", "fmkj", "xfskj",
                  "bz", "cfd", "sgy", "sgtel"):
        setattr(row, field, (getattr(data, field) or "").strip()
                if field in ("nr", "gdh") else getattr(data, field) or "")
    row.num = data.num


@router.get("")
def list_daxiu(
    page: int = 1, size: int = 30, rq: str = "", bmid: str = "", keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    q = scoped_query(db, current, CDDaxiu, rq, bmid, keyword,
                     (CDDaxiu.nr, CDDaxiu.cfd, CDDaxiu.sgy, CDDaxiu.bz))
    total = q.count()
    rows = (
        q.order_by(CDDaxiu.id.desc())
        .offset((max(page, 1) - 1) * size).limit(size).all()
    )
    names = dept_names(db)
    return {"items": [daxiu_row(r, names) for r in rows],
            "total": total, "bt": bt_title(rq)}


@router.get("/export")
def export_daxiu(
    rq: str = "", bmid: str = "", keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    """照旧 Excel 用 LoadSearchEntitiesNoPage:导出当前筛选全量(含关键字/部门)。"""
    q = scoped_query(db, current, CDDaxiu, rq, bmid, keyword,
                     (CDDaxiu.nr, CDDaxiu.cfd, CDDaxiu.sgy, CDDaxiu.bz))
    names = dept_names(db)
    items = [daxiu_row(r, names) for r in q.order_by(CDDaxiu.id.desc()).all()]
    buf = build_daxiu_excel(bt_title(rq), items)
    filename = f"{bt_title(rq)}传导设备大修明细.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("")
def add_daxiu(
    data: DaxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    ensure_not_locked(db)
    daxiudate = _validate(data)
    now = datetime.now()
    row = CDDaxiu(bmid=default_bmid(current), username=display_name(current),
                  adddate=now, finadate=now)
    _apply(row, data, daxiudate)
    db.add(row)
    db.commit()
    db.refresh(row)
    return daxiu_row(row, dept_names(db))


@router.put("/{rid}")
def update_daxiu(
    rid: int, data: DaxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    ensure_not_locked(db)
    row = _get_or_404(db, rid)
    ensure_owner(row, current, "修改")
    daxiudate = _validate(data)
    _apply(row, data, daxiudate)
    row.finadate = datetime.now()
    db.commit()
    db.refresh(row)
    return daxiu_row(row, dept_names(db))


@router.delete("/{rid}")
def delete_daxiu(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    # 旧 Deletegz 未做锁定检查,仅往期/本人校验(与故障页不同,照旧保留)
    row = _get_or_404(db, rid)
    ensure_current_month(row, "往期数据无法删除")
    ensure_owner(row, current, "删除")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.get("/{rid}")
def get_daxiu(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cddaxiu:view")),
):
    ensure_not_locked(db)
    return daxiu_row(_get_or_404(db, rid), dept_names(db))
