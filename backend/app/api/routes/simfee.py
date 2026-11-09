"""通信费(照旧 simFeiyongController 复刻)。

只有查询/导出,无增删改;话费数据由 SIM 卡管理的「上传话费」写入。
权限:simfee:view(入口 + 列表/导出)。
"""

from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.simcard import Feiyong
from app.models.user import Department, User
from app.services.simfee_common import (
    available_months, available_years, base_query, build_export, build_rows,
    default_period, empty_yongtu_rows,
)

router = APIRouter()


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="export.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("")
def list_fees(
    page: int = 1,
    size: int = 20,
    year: Optional[int] = None,
    month: Optional[int] = None,
    bmid: Optional[int] = None,
    keyword: str = "",
    only_self: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simfee:view")),
):
    if year is None or month is None:
        year, month = default_period(db)
    q = base_query(
        db, current, year, month, bmid=bmid, keyword=keyword,
        only_self=only_self, username=current.username,
    )
    total = q.count()
    tj = q.with_entities(func.coalesce(func.sum(Feiyong.jine), 0)).scalar() or 0
    fees = q.order_by(Feiyong.jine.desc(), Feiyong.id.asc()).offset(
        (page - 1) * size
    ).limit(size).all()
    return {
        "total": total,
        "items": build_rows(db, fees, year),
        "tj": f"{float(tj):.2f}",
        "year": year,
        "month": month,
    }


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simfee:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [
        {"id": d.id, "name": d.name}
        for d in dq.order_by(Department.id).all()
    ]
    years = available_years(db)
    default_year, default_month = default_period(db)
    today = date.today()
    return {
        "departments": departments,
        "years": years,
        "months": available_months(db, default_year),
        "default_year": default_year,
        "default_month": default_month,
        "current_year": today.year,
        "current_month": today.month,
    }


@router.get("/months")
def months(
    year: int,
    current: User = Depends(require_permission("simfee:view")),
    db: Session = Depends(get_db),
):
    return {"year": year, "months": available_months(db, year)}


@router.get("/export")
def export_fees(
    year: Optional[int] = None,
    month: Optional[int] = None,
    bmid: Optional[int] = None,
    keyword: str = "",
    only_self: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simfee:view")),
):
    if year is None or month is None:
        year, month = default_period(db)
    q = base_query(
        db, current, year, month, bmid=bmid, keyword=keyword,
        only_self=only_self, username=current.username,
    )
    fees = q.order_by(Feiyong.jine.desc(), Feiyong.id.asc()).all()
    rows = build_rows(db, fees, year)
    return _xlsx_response(build_export(rows), f"费用明细_{year}_{month}.xlsx")


@router.get("/export-empty")
def export_empty_yongtu(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simfee:view")),
):
    if year is None or year <= 0:
        raise HTTPException(status_code=400, detail="请先选择正确的年度")
    rows = empty_yongtu_rows(db, current, year)
    if not rows:
        raise HTTPException(status_code=400, detail="没有符合条件的记录")
    return _xlsx_response(
        build_export(rows, "用途为空"),
        f"费用明细_年度{year}_yongtu空.xlsx",
    )
