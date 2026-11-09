"""oiltj(车辆油量统计报表)Excel 导出,照旧 whl.BLL.Exceiloilbb.cs 三张表复刻。

旧系统用 .xls 模板 + NPOI;新系统没有模板文件,用 openpyxl 按
模板的行列布局重建(标题/信息/表头/数据/合计行,SUM 公式照旧)。
"""

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")
_FONT = Font(name="宋体", size=11)


def _style_cell(cell):
    cell.font = _FONT
    cell.border = _BORDER
    cell.alignment = _CENTER


def _put(ws, row, col, value):
    cell = ws.cell(row=row, column=col, value=value)
    _style_cell(cell)
    return cell


def _autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ==================== 月度报表(照 loadExcel) ====================
def build_month_excel(rows: list, dept_name: str, nian: int, yue: int) -> bytes:
    """rows: 列表接口同一套统计行(月度口径),列序照旧模板 11 列。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "加油统计"
    ws.merge_cells("A1:K1")
    c = ws.cell(row=1, column=1, value=f"{dept_name}{nian}年加油统计表")
    c.font = Font(name="宋体", size=14, bold=True)
    c.alignment = _CENTER
    ws.merge_cells("A2:D2")
    ws.cell(row=2, column=1, value=f"统计部门:{dept_name}")
    ws.cell(row=2, column=7, value=f"年度:{nian}  月份:{yue}")

    headers = ["序号", "部门", "车号", "本月底公里数", "上月底公里数", "月行驶公里",
               "月加油量(l)", "备注", "车辆类型", "用途", "油类"]
    for col, h in enumerate(headers, start=1):
        _put(ws, 3, col, h)

    r = 4
    for i, zc in enumerate(rows, start=1):
        _put(ws, r, 1, i)
        _put(ws, r, 2, zc["bumen"])
        _put(ws, r, 3, zc["chehao"])
        _put(ws, r, 4, zc["bydgls"])
        _put(ws, r, 5, zc["sydgls"])
        _put(ws, r, 6, zc["yssgls"])
        _put(ws, r, 7, zc["yoil"])
        _put(ws, r, 8, zc["bz"])
        _put(ws, r, 9, zc["lx"])
        _put(ws, r, 10, zc["cheyt"])
        _put(ws, r, 11, "柴油" if zc["oil"] == "0#" else (zc["oil"] or ""))
        r += 1

    if rows:
        sum_row = r
        _put(ws, sum_row, 1, "合计")
        ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=6)
        cell = ws.cell(row=sum_row, column=7,
                       value=f"=SUM(G4:G{r - 1})")
        _style_cell(cell)
        ws.row_dimensions[sum_row].height = 25

    _autosize(ws, [6, 14, 14, 14, 14, 12, 12, 16, 12, 12, 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==================== 年度报表(照 loadExcelnd) ====================
def build_year_excel(rows: list, dept_name: str, nian: int) -> bytes:
    """rows: 年度口径统计行,列序照旧模板 16 列。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "油耗统计"
    ws.merge_cells("A1:P1")
    c = ws.cell(row=1, column=1, value=f"{dept_name}{nian}年油耗统计表")
    c.font = Font(name="宋体", size=14, bold=True)
    c.alignment = _CENTER
    ws.merge_cells("A2:D2")
    ws.cell(row=2, column=1, value=f"统计部门:{dept_name}")
    ws.cell(row=2, column=7, value=f"年份:{nian}年")

    headers = ["序号", "部门", "车号", "全年行驶公里", "全年加油量(l)", "百公里油耗",
               "备注", "车辆类型", "用途", "车辆状态", "上年最大公里数", "今年最大公里数",
               "油类", "注册日期", "加油金额(元)", "排量"]
    for col, h in enumerate(headers, start=1):
        _put(ws, 3, col, h)

    r = 4
    for i, zc in enumerate(rows, start=1):
        _put(ws, r, 1, i)
        _put(ws, r, 2, zc["bumen"])
        _put(ws, r, 3, zc["chehao"])
        _put(ws, r, 4, zc["ngls"])
        _put(ws, r, 5, zc["noil"])
        _put(ws, r, 6, zc["lpkm_tboil"])
        _put(ws, r, 7, zc["bz"])
        _put(ws, r, 8, zc["lx"])
        _put(ws, r, 9, zc["cheyt"])
        status = {1: "正常在用", 2: "已报废"}.get(zc["delf"], "已删除")
        _put(ws, r, 10, status)
        _put(ws, r, 11, zc["snzdgls"])
        _put(ws, r, 12, zc["jnzdgls"])
        _put(ws, r, 13, "柴油" if zc["oil"] == "0#" else (zc["oil"] or ""))
        _put(ws, r, 14, zc["chuchang"] or "")
        _put(ws, r, 15, zc["yoil_je"])
        _put(ws, r, 16, zc["pailiang"])
        r += 1

    _autosize(ws, [6, 14, 14, 13, 13, 11, 16, 12, 12, 10, 13, 13, 10, 12, 13, 8])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==================== 财务报表(照 loadExcelcw,双 sheet) ====================
def build_finance_excel(details: list, nian: int, yue: int, dept_name: str) -> bytes:
    """details: 财务口径明细行(部门/卡号/车号/加油时间/升数/金额/油类)。

    sheet1 按部门聚合(照旧 gb 分组),sheet2 明细 + 纵向合并(照 MergeVerticalCells)。
    """
    groups = {}
    for zc in details:
        g = groups.setdefault(zc["bumen"], {
            "s0_l": 0.0, "s0_e": 0.0, "s92_l": 0.0, "s92_e": 0.0,
            "s95_l": 0.0, "s95_e": 0.0, "ol": 0.0, "ze": 0.0})
        key = {"0#": "0", "92#": "92", "95#": "95"}.get(zc["lei"])
        if key:
            g[f"s{key}_l"] += zc["oill"] or 0
            g[f"s{key}_e"] += zc["jine"] or 0
        g["ol"] += zc["oill"] or 0
        g["ze"] += zc["jine"] or 0
    # 按部门名排序,与旧库 groupby 输出顺序近似(旧无显式排序,此处稳定即可)
    ordered = sorted(groups.items(), key=lambda kv: kv[0])

    wb = Workbook()
    # ---- sheet1 部门汇总 ----
    ws = wb.active
    ws.title = "部门汇总"
    ws.merge_cells("A1:J1")
    c = ws.cell(row=1, column=1, value=f"{nian}年{yue}月{dept_name}加油统计表")
    c.font = Font(name="宋体", size=14, bold=True)
    c.alignment = _CENTER
    headers = ["序号", "部门", "0#（升）", "0#（元）", "92#（升）", "92#（元）",
               "95#（升）", "95#（元）", "金额(元)", "加油量(升)"]
    for col, h in enumerate(headers, start=1):
        _put(ws, 2, col, h)
    r = 3
    for i, (bm, g) in enumerate(ordered, start=1):
        _put(ws, r, 1, i)
        _put(ws, r, 2, bm)
        _put(ws, r, 3, round(g["s0_l"], 2))
        _put(ws, r, 4, round(g["s0_e"], 2))
        _put(ws, r, 5, round(g["s92_l"], 2))
        _put(ws, r, 6, round(g["s92_e"], 2))
        _put(ws, r, 7, round(g["s95_l"], 2))
        _put(ws, r, 8, round(g["s95_e"], 2))
        _put(ws, r, 9, round(g["ze"], 2))
        _put(ws, r, 10, round(g["ol"], 2))
        r += 1
    if ordered:
        sum_row = r
        ws.row_dimensions[sum_row].height = 25
        _put(ws, sum_row, 1, "合计")
        ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=2)
        for col, letter in zip(range(3, 11), ["C", "D", "E", "F", "G", "H", "I", "J"]):
            cell = ws.cell(row=sum_row, column=col, value=f"=SUM({letter}3:{letter}{r - 1})")
            _style_cell(cell)
    _autosize(ws, [6, 14, 12, 14, 14, 14, 14, 14, 14, 14])

    # ---- sheet2 明细(照旧:部门金额/升数、卡号升数都重复后纵向合并) ----
    ws2 = wb.create_sheet("加油明细")
    ws2.merge_cells("A1:J1")
    c = ws2.cell(row=1, column=1, value=f"{nian}年{yue}月{dept_name}加油明细")
    c.font = Font(name="宋体", size=14, bold=True)
    c.alignment = _CENTER
    headers2 = ["序号", "部门", "部门金额(元)", "部门升数(L)", "卡号", "车号",
                "卡号升数(L)", "加油时间", "升数(L)", "金额(元)"]
    for col, h in enumerate(headers2, start=1):
        _put(ws2, 2, col, h)

    dept_je, dept_ol, card_ol = {}, {}, {}
    for zc in details:
        dept_je[zc["bumen"]] = dept_je.get(zc["bumen"], 0) + (zc["jine"] or 0)
        dept_ol[zc["bumen"]] = dept_ol.get(zc["bumen"], 0) + (zc["oill"] or 0)
        card_ol[zc["kanum"]] = card_ol.get(zc["kanum"], 0) + (zc["oill"] or 0)

    r = 3
    for i, zc in enumerate(details, start=1):
        _put(ws2, r, 1, i)
        _put(ws2, r, 2, zc["bumen"])
        _put(ws2, r, 3, round(dept_je[zc["bumen"]], 2))
        _put(ws2, r, 4, round(dept_ol[zc["bumen"]], 2))
        _put(ws2, r, 5, zc["kanum"])
        _put(ws2, r, 6, zc["chehao"])
        _put(ws2, r, 7, round(card_ol[zc["kanum"]], 2))
        _put(ws2, r, 8, zc["ptime"] or "")
        _put(ws2, r, 9, round(zc["oill"] or 0, 2))
        _put(ws2, r, 10, round(zc["jine"] or 0, 2))
        ws2.row_dimensions[r].height = 20
        r += 1
    if details:
        sum_row = r
        ws2.row_dimensions[sum_row].height = 20
        _put(ws2, sum_row, 1, "合计")
        cell = ws2.cell(row=sum_row, column=9, value=f"=SUM(I3:I{r - 1})")
        _style_cell(cell)
        cell = ws2.cell(row=sum_row, column=10, value=f"=SUM(J3:J{r - 1})")
        _style_cell(cell)
        # 照旧 MergeVerticalCells(wk, 1, col):B~G 列纵向合并
        for col in range(2, 7):
            ws2.merge_cells(start_row=3, start_column=col, end_row=max(r - 1, 3), end_column=col)
        for col, w in enumerate([6, 14, 14, 14, 14, 14, 14, 20, 10, 12], start=1):
            ws2.column_dimensions[get_column_letter(col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def finance_filename(nian: int, yue: int, dept_name: str) -> str:
    return f"{nian}年{yue}月{dept_name}加油统计表({datetime.now():%Y-%m-%d}).xlsx"
