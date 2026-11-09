"""车辆维修 Excel 导出(照旧 Excelclwxd 的维修单/维修明细两套列)。"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

DAN_COLUMNS = [
    ("流水号", "ID"), ("进场日期", "jcriqi"), ("部门", "bm"), ("车号", "chehao"),
    ("总金额", "jine"), ("维修项目", "xiangmu"), ("维修单位", "dwname"),
    ("工时费", "gongshifei"), ("配件费", "peijianfei"), ("登记日期", "djriqi"),
    ("驾驶员", "jiashiyuan"), ("电话", "telphone"), ("车辆类型", "cllx"),
    ("品牌", "pinpai"),
]

MX_COLUMNS = [
    ("编号", "id"), ("维修单日期", "jcriqi"), ("部门", "bm"), ("车号", "chehao"),
    ("总金额", "zonge"), ("项目名称", "xiangmu"), ("规格", "guige"),
    ("单价", "danjia"), ("数量", "shuliang"), ("关键字", "gjz"),
    ("配件或工时", "pjorgs"), ("公里数", "gonglinum"), ("车辆类型", "cllx"),
    ("驾驶员", "jiashiyuan"), ("电话", "telphone"), ("出厂日期", "chuchang"),
    ("车龄", "car_age"),
]


def excel_disposition(filename: str) -> str:
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")


def build_excel(rows: list, kind: str = "dan") -> BytesIO:
    columns = MX_COLUMNS if kind == "mx" else DAN_COLUMNS
    title = "车辆维修明细" if kind == "mx" else "车辆维修单"
    wb = Workbook()
    ws = wb.active
    ws.title = title
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, (label, _key) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(columns, start=1):
            v = row.get(key)
            if key in ("jine", "gongshifei", "peijianfei", "zonge", "danjia") and v is not None:
                v = round(float(v), 2)
            ws.cell(row=r, column=c, value=v if v is not None else "")
            ws.cell(row=r, column=c).border = border

    widths = {
        "ID": 10, "id": 10, "jcriqi": 12, "djriqi": 19, "bm": 14, "chehao": 12,
        "jine": 11, "zonge": 11, "xiangmu": 30, "dwname": 24, "gongshifei": 10,
        "peijianfei": 10, "jiashiyuan": 10, "telphone": 14, "cllx": 12,
        "pinpai": 12, "guige": 22, "danjia": 10, "shuliang": 8, "gjz": 18,
        "pjorgs": 10, "gonglinum": 10, "chuchang": 12, "car_age": 8,
    }
    for c, (_label, key) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(key, 12)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
