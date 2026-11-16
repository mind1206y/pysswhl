"""传导完好率(照旧 CDwanhaolvController 1:1 复刻)。

- 列表:每月 25 日的部门汇总报表,关键字搜备注,footer 是当前页合计
- 生成报表:按登录人部门子树重算当月完好率(上月有报表才生成)
- 编辑备注 / 锁定开关:锁定只影响故障/大修/变动三页的增删改,不影响本页
- 导出:公司版(全部门)/营业所版(本部门) 3 sheet 汇总表
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.cd import CDGz, CDWhl, CDXz
from app.models.user import User
from app.services.cd_common import (
    bt_title, dept_names, display_name, generate_report, is_locked, report_date,
    scoped_query, set_locked, whl_footer, whl_row, xz_row, gz_row,
)
from app.services.cd_excel import build_whl_excel, content_disposition

router = APIRouter()


class RemarkIn(BaseModel):
    id: int
    bz: str = ""


class GenerateIn(BaseModel):
    rq: str = ""


class LockIn(BaseModel):
    is_locked: bool = False


def _get_or_404(db: Session, wid: int) -> CDWhl:
    row = db.get(CDWhl, wid)
    if row is None:
        raise HTTPException(status_code=404, detail="报表记录不存在")
    return row


def _list_payload(db: Session, current: User, *, page=1, size=30, rq="",
                  bmid=None, keyword="") -> dict:
    q = scoped_query(db, current, CDWhl, rq, bmid, keyword, (CDWhl.bz,))
    total = q.count()
    rows = (
        q.order_by(CDWhl.bmid.asc(), CDWhl.id.asc())
        .offset((max(page, 1) - 1) * size).limit(size).all()
    )
    names = dept_names(db)
    items = [whl_row(r, names) for r in rows]
    return {
        "items": items, "total": total, "bt": bt_title(rq),
        "footer": whl_footer(items), "is_locked": is_locked(db),
    }


@router.get("")
def list_whl(
    page: int = 1, size: int = 30, rq: str = "", bmid: str = "", keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:view")),
):
    return _list_payload(db, current, page=page, size=size, rq=rq,
                         bmid=bmid, keyword=keyword)


@router.post("/generate")
def generate_whl(
    data: GenerateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:view")),
):
    created = generate_report(db, current, data.rq)
    return {"message": "ok", "created": created,
            "detail": f"已生成 {created} 个部门的报表" if created else "上月无报表,未生成记录"}


@router.get("/remark")
def get_remark(
    id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:view")),
):
    return {"bz": _get_or_404(db, id).bz or ""}


@router.post("/remark")
def save_remark(
    data: RemarkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:view")),
):
    row = _get_or_404(db, data.id)
    row.bz = data.bz or ""
    row.finadate = datetime.now()
    db.commit()
    return {"message": "ok"}


@router.post("/lock")
def lock_report(
    data: LockIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:manage")),
):
    value = set_locked(db, bool(data.is_locked))
    return {"message": "ok", "is_locked": value}


@router.get("/export")
def export_whl(
    rq: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdwhl:view")),
):
    """照旧 ExcelCD.ewk / yysewk:导出不受页面关键字/部门下拉影响,只看报表日期。"""
    names = dept_names(db)
    whl_items = [
        whl_row(r, names)
        for r in scoped_query(db, current, CDWhl, rq).order_by(CDWhl.bmid).all()
    ]
    xz_items = [
        xz_row(r, names)
        for r in scoped_query(db, current, CDXz, rq).order_by(CDXz.bdlb, CDXz.id).all()
    ]
    gz_items = [
        gz_row(r, names)
        for r in scoped_query(db, current, CDGz, rq).order_by(CDGz.bmid, CDGz.id).all()
    ]
    scope = dept_scope_ids(db, current)
    company = scope is None
    dept_label = "售水事业部" if company else (
        current.departments[0].name if current.departments else "售水事业部"
    )
    buf = build_whl_excel(
        bt_title(rq), whl_items, xz_items, gz_items, names,
        dept_label, display_name(current),
    )
    filename = f"{dept_label}{bt_title(rq)}传导设备完好率汇总表.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )
