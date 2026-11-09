"""车辆管理导出:Excel 台账(照旧 loadchelexcel.cs 25 列) + 车辆图片资料 PDF。"""

from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.services.vehicle_common import EXPORT_COLUMNS

# Windows 自带中文字体(reportlab 无内置中文字体,不注册会显示成方块)
_FONT_CANDIDATES = [
    ("SimSun", "C:/Windows/Fonts/simsun.ttc", 0),
    ("MSYaHei", "C:/Windows/Fonts/msyh.ttc", 0),
    ("SimHei", "C:/Windows/Fonts/simhei.ttf", None),
]
PDF_FONT = "Helvetica"


def _register_font():
    global PDF_FONT
    for name, path, sub in _FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=sub) if sub is not None
                                    else TTFont(name, path))
            PDF_FONT = name
            return
        except Exception:
            continue


_register_font()


def excel_filename() -> str:
    return "车辆信息表.xlsx"


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码会 500。"""
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")


def pdf_disposition(filename: str) -> str:
    return (f'attachment; filename="vehicles.pdf"; '
            f"filename*=UTF-8''{quote(filename)}")


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "车辆信息表"
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=r - 1)
        for c, (_label, key) in enumerate(EXPORT_COLUMNS[1:], start=2):
            v = row.get(key)
            ws.cell(row=r, column=c, value=v if v is not None else "")
        for c in range(1, len(EXPORT_COLUMNS) + 1):
            ws.cell(row=r, column=c).border = border

    widths = [6, 16, 12, 12, 14, 18, 13, 16, 16, 12, 14, 12, 8, 18, 18,
              13, 12, 16, 16, 13, 8, 18, 20, 10, 13]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# PDF 单页展示的字段(标签, key),照 Excel 顺序排成两列
PDF_FIELDS = [(label, key) for label, key in EXPORT_COLUMNS if key]


def build_pdf(cars: list, image_paths: dict) -> BytesIO:
    """每辆车一页:上半部分基本信息,下半部分车辆图片(缺失则文字提示)。

    image_paths: {车辆id: [本地路径, ...]},由路由层解析;文件不存在的路径不传进来。
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for car in cars:
        c.setFont(PDF_FONT, 16)
        c.drawString(40, height - 45, f"车辆档案  {car.get('chehao') or ''}")
        c.setFont(PDF_FONT, 9)
        c.drawString(40, height - 62, f"部门:{car.get('bumen') or '-'}    类型:{car.get('lx') or '-'}    "
                                        f"状态:{'报废' if car.get('delf') == 2 else '正常'}")

        # 基本信息:两列并排,每项一行
        y = height - 90
        line_h = 15
        half = (len(PDF_FIELDS) + 1) // 2
        c.setFont(PDF_FONT, 9)
        for i, (label, key) in enumerate(PDF_FIELDS):
            col = 0 if i < half else 1
            row = i if i < half else i - half
            x = 40 + col * 265
            yy = y - row * line_h
            value = car.get(key)
            text = "" if value is None else str(value)
            c.drawString(x, yy, f"{label}: {text[:24]}")

        # 图片区
        paths = image_paths.get(car["id"], [])
        img_y = y - half * line_h - 20
        c.setFont(PDF_FONT, 9)
        if not paths:
            c.setFillColorRGB(0.6, 0.3, 0.3)
            c.drawString(40, img_y, "暂无图片(历史图片文件需从旧系统生产服务器拷贝)")
            c.setFillColorRGB(0, 0, 0)
        for i, path in enumerate(paths[:4]):
            col, row = i % 2, i // 2
            x = 40 + col * 265
            yy = img_y - 30 - row * 165
            try:
                c.drawImage(ImageReader(str(path)), x, yy - 135, width=240, height=135,
                            preserveAspectRatio=True, anchor="c")
                c.drawString(x, yy - 150, Path(path).name[:34])
            except Exception:
                c.drawString(x, yy - 60, f"图片无法读取:{Path(path).name[:24]}")
        c.showPage()
    c.save()
    buf.seek(0)
    return buf
