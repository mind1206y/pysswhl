"""合同登记/归集 Excel 导出(照旧 ExcelHt.loadAllExcel 的列口径)。"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from fastapi.responses import StreamingResponse

COLUMNS = [
    ("id", "ID", 8),
    ("leibie", "合同类别", 14),
    ("name", "合同名称", 34),
    ("allbh", "合同编号", 16),
    ("duixiang", "签订对象", 28),
    ("biaodi", "合同标的", 28),
    ("jine", "金额(元)", 14),
    ("qddate", "签订日期", 12),
    ("period", "实施时间", 24),
    ("lvxingqingkuang", "履行情况", 12),
    ("user", "提交人", 10),
    ("bm", "部门", 14),
    ("bz", "归集备注", 24),
    ("beizhu", "备注描述", 24),
    ("zt", "状态", 10),
    ("zhaobiaofangshi", "招标方式", 18),
    ("kongzhijia", "控制价(元)", 14),
    ("sfwjdw", "是否属于单次采购金额5-10万元(含)非直接采购项目", 30),
]

THIN = Side(style="thin", color="D9E2EC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _period(row):
    start = row.get("ssdate") or ""
    end = row.get("zzdate") or ""
    if start and end:
        return f"{start}至{end}"
    return start or end


def _cell(row, key):
    if key == "period":
        return _period(row)
    if key == "jine":
        v = row.get(key)
        return None if v is None else float(v)
    if key == "kongzhijia":
        v = row.get(key)
        return None if v is None else float(v)
    if key == "sfwjdw":
        v = row.get(key)
        return "" if v is None else ("是" if v else "否")
    return row.get(key)


def content_disposition(filename: str) -> str:
    return (
        f'attachment; filename="contracts.xlsx"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


def build_excel(rows: list, title: str, filename: str) -> StreamingResponse:
    wb = Workbook()
    ws = wb.active
    ws.title = "合同明细"
    total_width = sum(c[2] for c in COLUMNS)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMNS))
    title_cell = ws.cell(row=1, column=1, value=title)
    title_cell.font = Font(name="宋体", size=16, bold=True)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30
    _ = total_width

    header_fill = PatternFill("solid", fgColor="F2F6FC")
    for col, (_, label, width) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=2, column=col, value=label)
        c.font = Font(name="宋体", size=11, bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.fill = header_fill
        c.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[2].height = 30

    for r, row in enumerate(rows, start=3):
        for col, (key, _, _) in enumerate(COLUMNS, start=1):
            c = ws.cell(row=r, column=col, value=_cell(row, key))
            c.font = Font(name="宋体", size=10)
            c.alignment = Alignment(horizontal="left" if key in ("name", "biaodi", "duixiang", "bz", "beizhu") else "center",
                                    vertical="center", wrap_text=True)
            c.border = BORDER

    ws.freeze_panes = "A3"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )
