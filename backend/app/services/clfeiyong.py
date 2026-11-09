"""车辆各类费用(照旧 CLfeiyongController / ClfeiyongS)公共逻辑:筛选、行组装、Excel。

旧系统列表(LoadSearchEntities)与导出(LoadSearchEntitiesNoPage)是两套查询:
- 列表关键字匹配「收费单位 或 车号」,且有类别筛选
- 导出关键字只匹配收费单位,且漏了类别筛选(照旧导出会带出列表看不到的记录)
新系统统一成一个 fee_query,下载记录 = 当前筛选全量(与 celou/gongdan 的处理一致)。
"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, ClFeiyong

# 旧 Index ViewBag.lei 的固定三项(顺序照旧:洗车/高速/停车)
CATEGORIES = ["洗车", "高速", "停车"]


def fee_query(db, user, *, year: str = "", lx: str = "", keyword: str = ""):
    """费用记录 + 车辆联查,部门取车辆 bmid 子树(照旧 bb_bumen.cj.Contains(cj))。"""
    q = db.query(ClFeiyong, ClChe).join(ClChe, ClFeiyong.cheid == ClChe.id)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    y = (year or "").strip()
    if y.isdigit():
        q = q.filter(func.year(ClFeiyong.feiyongdate) == int(y))
    category = (lx or "").strip()
    if category:
        q = q.filter(ClFeiyong.lx == category)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(ClFeiyong.dw.like(like), ClChe.chehao.like(like)))
    return q


def total_amount(q) -> float:
    """筛选后全量合计(不是当页),照旧 gz.tongjijine。"""
    value = (
        q.order_by(None)
        .with_entities(func.coalesce(func.sum(ClFeiyong.jine), 0))
        .scalar()
    )
    return float(value or 0)


def build_rows(db, pairs) -> list:
    """列表/导出行:主表字段 + 车辆车号与部门名(旧 GetList 的 bm / chehao)。"""
    names = dept_name_map(db)
    rows = []
    for fee, car in pairs:
        d = fee.to_dict()
        d["chehao"] = car.chehao if car else ""
        d["bumen"] = (names.get(car.bmid) if car and car.bmid else "") or (car.bm if car else "") or ""
        rows.append(d)
    return rows


# 照旧 App_Data/车辆其他各项费用.xls 的 9 列模板
EXPORT_COLUMNS = [
    ("序号", None), ("车牌号", "chehao"), ("交费日期", "feiyongdate"),
    ("费用名称", "lx"), ("费用金额", "jine"), ("收费单位", "dw"),
    ("交费方式", "fangshi"), ("经手人", "jingshou"), ("备注", "bz"),
]
TITLE = "高速、洗车、停车费                                                  单位：元"


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "各类费用"
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
    title = ws.cell(row=1, column=1, value=TITLE)
    title.font = Font(bold=True, size=14, color="1f2937")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    thin = Side(style="thin", color="b8c2cc")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="e8eef5")
    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=2, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[2].height = 22

    for r, row in enumerate(rows, start=3):
        for c, (label, key) in enumerate(EXPORT_COLUMNS, start=1):
            value = r - 2 if label == "序号" else row.get(key)
            if label == "费用金额":
                value = float(value) if value not in (None, "") else 0
            cell = ws.cell(row=r, column=c, value=value if value not in (None, "") else "")
            cell.border = border
            if label in ("序号", "交费日期", "费用名称", "费用金额"):
                cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[r].height = 19

    widths = [8, 14, 14, 12, 12, 34, 12, 12, 24]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码报 500。"""
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")
