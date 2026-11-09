"""手机管理导出(照旧 shoujiController.ExportJcExcel 的 19 列)。"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def _txt(value) -> str:
    if value is None:
        return ""
    return str(value)


HEADERS = [
    "ID", "品牌", "规格", "编号", "备注", "部门", "登记人", "登记时间",
    "启用日期", "状态", "用途", "使用人", "号码", "操作", "操作时间",
    "确认日期", "确认人", "价格", "理由",
]


def build_export(rows: list[dict]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "基础信息"

    header_fill = PatternFill("solid", fgColor="DDEBF7")
    for i, title in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=i, value=title)
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = 20

    for r, item in enumerate(rows, start=2):
        values = [
            item.get("id"),
            item.get("pinpai"),
            item.get("guige"),
            item.get("bh"),
            item.get("bz"),
            item.get("bm"),
            item.get("djuser"),
            (item.get("djtime") or "")[:10],
            item.get("qiyongdate"),
            item.get("zt"),
            item.get("yongtu"),
            item.get("shiyongren"),
            item.get("haoma"),
            item.get("caozuo"),
            item.get("caozuotime"),
            (item.get("querendate") or "")[:10],
            item.get("querenuser"),
            float(item.get("jiage") or 0),
            item.get("liyou"),
        ]
        for c, value in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=_txt(value) if not isinstance(value, float) else value)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def excel_disposition(filename: str) -> str:
    return f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(filename)}"
