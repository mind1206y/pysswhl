"""加油明细(照旧 PlusOilController 复刻)。

只读列表 + 筛选 + 合计 + 导出当前筛选记录(列照旧 OilCardExcel.exportPlusOil)。

权限:plusoil:view。
"""

from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, PlusOil
from app.services import plus_oil_common as svc
from app.services.vehicle_common import YONGTU_OPTIONS

router = APIRouter()


@router.get("")
def list_plus_oil(
    page: int = 1,
    size: int = 30,
    keyword: str = "",
    bmid: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    lei: str = "",
    chellx: str = "",
    chezhuangtai: Optional[int] = None,
    chelyt: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plusoil:view")),
):
    q = svc.filtered_query(db, current, keyword=keyword, bmid=bmid, start=start, end=end,
                           lei=lei, chellx=chellx, chezhuangtai=chezhuangtai, chelyt=chelyt)
    total = q.count()
    records = (q.order_by(PlusOil.id.desc())
               .offset(max(page - 1, 0) * size).limit(size).all())
    return {
        "total": total,
        "items": svc.build_rows(db, records),
        "footer": svc.footer_stats(db, q),
    }


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plusoil:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    lx = [r[0] for r in db.query(ClChe.lx).filter(ClChe.lx != "")
          .distinct().order_by(ClChe.lx).all()]
    return {
        "departments": departments,
        "lx": lx,
        "lei": svc.LEI_OPTIONS,
        "status": svc.STATUS_OPTIONS,
        "yongtu": YONGTU_OPTIONS,
        "years": svc.years(db, current),
        "current_year": date.today().year,
    }


@router.get("/export")
def export_excel(
    keyword: str = "",
    bmid: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    lei: str = "",
    chellx: str = "",
    chezhuangtai: Optional[int] = None,
    chelyt: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plusoil:view")),
):
    buf = svc.export_rows(db, current, keyword=keyword, bmid=bmid, start=start, end=end,
                          lei=lei, chellx=chellx, chezhuangtai=chezhuangtai, chelyt=chelyt)
    filename = "加油记录.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(filename)}"},
    )
