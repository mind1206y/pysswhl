"""路面修复管理导出(照旧 RoadRepairController.ExportList 双 Sheet)。

Sheet1 维修记录:与列表筛选完全一致(不分页);
Sheet2 进度记录:仅导出当前筛选结果的进度,按 repair_id + 进度日期排序。
"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS1 = [
    "ID", "地址", "单位", "开挖日期", "道路类型", "面积", "决算面积",
    "单价", "总额", "当前状态", "原因", "班组", "备注",
]
HEADERS2 = ["repair_id", "进度", "进度日期", "操作人"]


def _txt(value) -> str:
    if value is None:
        return ""
    return str(value)


def _num(value):
    return float(value) if value is not None else 0.0


def _style_header(ws):
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def build_export(rows: list[dict], progress_rows: list[dict]) -> BytesIO:
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "维修记录"
    ws1.append(HEADERS1)
    for item in rows:
        ws1.append([
            item.get("id"),
            _txt(item.get("address")),
            _txt(item.get("company")),
            _txt(item.get("dig_date") or ""),
            _txt(item.get("road_type")),
            _num(item.get("area")),
            _num(item.get("final_area")),
            _num(item.get("price")),
            _num(item.get("total")),
            _txt(item.get("current_progress")),
            _txt(item.get("reason")),
            _txt(item.get("banzu")),
            _txt(item.get("remark")),
        ])
    _style_header(ws1)
    for col in ws1.columns:
        ws1.column_dimensions[col[0].column_letter].width = 16
    ws1.column_dimensions["A"].width = 8
    ws1.column_dimensions["B"].width = 28

    ws2 = wb.create_sheet("进度记录")
    ws2.append(HEADERS2)
    for item in progress_rows:
        ws2.append([
            item.get("repair_id") or 0,
            _txt(item.get("progress")),
            _txt(item.get("progress_date") or ""),
            _txt(item.get("operator_name")),
        ])
    _style_header(ws2)
    for col in ws2.columns:
        ws2.column_dimensions[col[0].column_letter].width = 20
    ws2.column_dimensions["A"].width = 10

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def excel_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"
