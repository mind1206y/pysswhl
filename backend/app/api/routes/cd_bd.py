"""传导变动表(照旧 CDbiandongController 1:1 复刻)。

- 列表:报表日期 + 部门子树 + 部门下拉 + 变动类别 + 关键字(设备名称)
- 增删改:锁定时禁止;编辑/删除限本人;删除限本月
- 模板下载 / 上传导入:旧 CDWHLExcel 从第 2 行起读 A=设备名称、B=变动类型,
  空首列停止,bbdate 固定当月 25 日,bmid 取登录人部门。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.cd import CDXz
from app.models.user import User
from app.services.cd_common import (
    BD_LB, bt_title, default_bmid, dept_names, display_name, ensure_current_month,
    ensure_not_locked, ensure_owner, parse_date, report_date, scoped_query, xz_row,
)
from app.services.cd_excel import build_bd_template, content_disposition, parse_bd_excel

router = APIRouter()


class XzIn(BaseModel):
    bbdate: Optional[str] = None
    bdlb: Optional[str] = None
    sbname: Optional[str] = None


def _get_or_404(db: Session, rid: int) -> CDXz:
    row = db.get(CDXz, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="变动记录不存在")
    return row


def _validate(data: XzIn):
    if not (data.sbname or "").strip():
        raise HTTPException(status_code=400, detail="请输入设备明细")
    if (data.bdlb or "").strip() not in BD_LB:
        raise HTTPException(status_code=400, detail="请选择变动类别")


@router.get("")
def list_bd(
    page: int = 1, size: int = 30, rq: str = "", bmid: str = "", keyword: str = "",
    bdlb: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    extra = CDXz.bdlb == bdlb if (bdlb or "").strip() else None
    q = scoped_query(db, current, CDXz, rq, bmid, keyword, (CDXz.sbname,), extra)
    total = q.count()
    rows = (
        q.order_by(CDXz.id.desc())
        .offset((max(page, 1) - 1) * size).limit(size).all()
    )
    names = dept_names(db)
    return {"items": [xz_row(r, names) for r in rows], "total": total, "bt": bt_title(rq)}


@router.get("/template")
def download_template(
    current: User = Depends(require_permission("cdbd:view")),
):
    buf = build_bd_template()
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition("传导设备变动表.xlsx")},
    )


@router.post("/upload")
async def upload_template(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    ensure_not_locked(db)
    content = await file.read()
    try:
        rows = parse_bd_excel(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = datetime.now()
    bmid = default_bmid(current)
    rd = report_date()
    uname = display_name(current)
    for sbname, bdlb in rows:
        db.add(CDXz(
            sbname=sbname, bmid=bmid, bbdate=rd, bdlb=bdlb,
            adddate=now, finadate=now, username=uname,
        ))
    db.commit()
    return {"message": "ok", "count": len(rows), "detail": f"成功导入 {len(rows)} 条"}


@router.post("")
def add_bd(
    data: XzIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    ensure_not_locked(db)
    _validate(data)
    now = datetime.now()
    row = CDXz(
        sbname=(data.sbname or "").strip(), bdlb=data.bdlb,
        bbdate=parse_date(data.bbdate) or report_date(),
        bmid=default_bmid(current), username=display_name(current),
        adddate=now, finadate=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return xz_row(row, dept_names(db))


@router.put("/{rid}")
def update_bd(
    rid: int, data: XzIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    ensure_not_locked(db)
    row = _get_or_404(db, rid)
    ensure_owner(row, current, "修改")
    _validate(data)
    row.bbdate = parse_date(data.bbdate) or report_date()
    row.sbname = (data.sbname or "").strip()
    row.bdlb = data.bdlb
    row.finadate = datetime.now()
    db.commit()
    db.refresh(row)
    return xz_row(row, dept_names(db))


@router.delete("/{rid}")
def delete_bd(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    ensure_not_locked(db)
    row = _get_or_404(db, rid)
    ensure_current_month(row, "往期报表无法改动")
    ensure_owner(row, current, "删除")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.get("/{rid}")
def get_bd(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdbd:view")),
):
    ensure_not_locked(db)
    return xz_row(_get_or_404(db, rid), dept_names(db))
