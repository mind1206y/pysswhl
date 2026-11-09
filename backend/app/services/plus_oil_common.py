"""加油明细公共逻辑(照旧 PlusOilController / PlusOilService 复刻)。

- 按部门子树 + 日期区间 + 油类/车辆类型/车辆状态/车辆用途/关键字筛选
- 列表合计金额与油量;导出当前筛选结果(照旧 OilCardExcel.exportPlusOil 列)
"""

from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.user import Department
from app.models.vehicle import ClChe, OilCard, PlusOil
from app.services.vehicle_common import YONGTU_OPTIONS

LEI_OPTIONS = ["0#", "92#", "95#"]
STATUS_OPTIONS = [
    {"value": 1, "label": "正常"},
    {"value": 2, "label": "报废"},
    {"value": 0, "label": "删除"},
]
EXPORT_HEADERS = ["卡号", "车号", "交易时间", "油品", "数量(升)", "金额(元)", "地点", "部门"]


def _subtree_ids(db: Session, root_id: int) -> set:
    ids = {root_id}
    frontier = {root_id}
    while frontier:
        children = {r[0] for r in db.query(Department.id)
                    .filter(Department.parent_id.in_(frontier), ~Department.id.in_(ids)).all()}
        if not children:
            break
        ids |= children
        frontier = children
    return ids


def filtered_query(
    db: Session, user, *, keyword: str = "", bmid: Optional[int] = None,
    start: Optional[date] = None, end: Optional[date] = None, lei: str = "",
    chellx: str = "", chezhuangtai: Optional[int] = None, chelyt: str = "",
):
    """照旧 PlusOilService.LoadSearchEntities:部门看记录归属 bmid,不是车辆当前部门。"""
    q = (db.query(PlusOil)
         .outerjoin(ClChe, ClChe.id == PlusOil.cheid)
         .outerjoin(OilCard, OilCard.id == PlusOil.kaid))
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(PlusOil.bmid.in_(scope))
    if bmid:
        q = q.filter(PlusOil.bmid.in_(_subtree_ids(db, bmid)))

    today = date.today()
    start = start or date(today.year, 1, 1)
    end = end or today
    q = q.filter(PlusOil.ptime >= datetime.combine(start, time.min),
                 PlusOil.ptime < datetime.combine(end + timedelta(days=1), time.min))

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(PlusOil.didian.like(like), OilCard.kanum.like(like),
                         ClChe.chehao.like(like)))
    if (lei or "").strip():
        q = q.filter(PlusOil.lei == lei.strip())
    if (chellx or "").strip():
        q = q.filter(ClChe.lx == chellx.strip())
    if (chelyt or "").strip():
        q = q.filter(ClChe.yongtu == chelyt.strip())
    if chezhuangtai is not None:
        q = q.filter(ClChe.delf == chezhuangtai)
    return q


def build_rows(db: Session, records: List[PlusOil]) -> List[dict]:
    names = dept_name_map(db)
    car_ids = [r.cheid for r in records if r.cheid]
    card_ids = [r.kaid for r in records if r.kaid]
    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_(car_ids)).all()} if car_ids else {}
    cards = {c.id: c for c in db.query(OilCard).filter(OilCard.id.in_(card_ids)).all()} if card_ids else {}
    rows = []
    for r in records:
        car = cars.get(r.cheid) if r.cheid else None
        card = cards.get(r.kaid) if r.kaid else None
        rows.append({
            "ID": r.id,
            "bm": names.get(r.bmid) or (car.bm if car else "") or "",
            "kanum": card.kanum if card and card.kanum else "",
            "leibie": r.leibie or "",
            "ptime": r.ptime.strftime("%Y-%m-%d %H:%M:%S") if r.ptime else "",
            "jine": round(float(r.jine or 0), 2),
            "oill": round(float(r.oill or 0), 2),
            "lx": car.lx if car else "",
            "chehao": car.chehao if car else "",
            "lei": r.lei or "",
            "didian": r.didian or "",
            "addtime": r.addtime.strftime("%Y-%m-%d %H:%M:%S") if r.addtime else "",
        })
    return rows


def footer_stats(db: Session, q) -> dict:
    oill, jine = q.with_entities(
        func.coalesce(func.sum(PlusOil.oill), 0),
        func.coalesce(func.sum(PlusOil.jine), 0),
    ).one()
    return {"oill": round(float(oill or 0), 2), "jine": round(float(jine or 0), 2)}


def years(db: Session, user) -> List[int]:
    q = db.query(func.year(PlusOil.ptime)).filter(PlusOil.ptime.isnot(None))
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(PlusOil.bmid.in_(scope))
    found = {int(y): None for (y,) in q.distinct().all() if y}
    found.setdefault(date.today().year, None)
    return sorted(found.keys(), reverse=True)


def export_rows(db: Session, user, **filters) -> BytesIO:
    q = filtered_query(db, user, **filters)
    records = q.order_by(PlusOil.id.desc()).all()
    rows = build_rows(db, records)

    wb = Workbook()
    ws = wb.active
    ws.title = "加油记录"
    fill = PatternFill("solid", fgColor="eef2f7")
    for i, name in enumerate(EXPORT_HEADERS, start=1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r, row in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=row["kanum"])
        ws.cell(row=r, column=2, value=row["chehao"])
        ws.cell(row=r, column=3, value=row["ptime"])
        ws.cell(row=r, column=4, value=row["leibie"])
        ws.cell(row=r, column=5, value=row["oill"])
        ws.cell(row=r, column=6, value=row["jine"])
        ws.cell(row=r, column=7, value=row["didian"])
        ws.cell(row=r, column=8, value=row["bm"])
    for i, width in enumerate([24, 14, 20, 12, 12, 12, 24, 14], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
