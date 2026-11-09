"""年度计划 Excel 导入/导出(照旧 NPOI 模板格式,统一输出 .xlsx)。

旧系统两类模板:
- 导出正式计划.xls        -> 正式计划 / 营业所发起导出(标题+表头+数据)
- 售水事业部更新改造计划.xlsx -> 实施单表/汇总:封面 + 7 个类别 sheet,
  每类含标题、编制单位、金额单位、表头、按部门分组的明细、小计、合计。

新系统用 openpyxl 重建同样的版式(列宽/行高/字体/边框/合并/合计公式),
不依赖旧 .xls 物理模板;金额单位统一万元。
"""

import io
import re
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

FONT_NAME = "宋体"
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _font(size=9, bold=False):
    return Font(name=FONT_NAME, size=size, bold=bold)


def _style(align="left", size=9, bold=False, wrap=True):
    return {
        "font": _font(size, bold),
        "border": BORDER,
        "alignment": Alignment(horizontal=align, vertical="center", wrap_text=wrap),
    }


def _put(ws, row, col, value, style):
    cell = ws.cell(row=row, column=col)
    cell.value = value
    cell.font = style["font"]
    cell.border = style["border"]
    cell.alignment = style["alignment"]
    return cell


def _merge(ws, row1, row2, col1, col2):
    ws.merge_cells(start_row=row1, start_column=col1, end_row=row2, end_column=col2)


def to_bytes(wb) -> bytes:
    wb.calculation.fullCalcOnLoad = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_sheet(data: bytes) -> list[list]:
    """读第一个工作表为二维数组,兼容 .xls(xlrd)/.xlsx(openpyxl)。"""
    if data[:4] == b"PK\x03\x04":
        wb = load_workbook(io.BytesIO(data), data_only=True)
        ws = wb.worksheets[0]
        out = []
        for row in ws.iter_rows(values_only=True):
            out.append(list(row))
        return out
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    ws = book.sheet_by_index(0)
    out = []
    for r in range(ws.nrows):
        line = []
        for c in range(ws.ncols):
            cell = ws.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                line.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
            else:
                line.append(cell.value)
        out.append(line)
    return out


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _date_text(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v) if v not in (None, "") else ""


def _slash_date(v):
    """旧模板日期显示为 2026/1/2(不补零)。"""
    text = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{int(m.group(1))}/{int(m.group(2))}/{int(m.group(3))}"
    return text


def _format_year_month(s):
    if not s:
        return ""
    m = re.match(r"^(\d{4})\s*[-/.年]\s*(\d{1,2})\s*月?$", str(s).strip())
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月"
    return str(s).strip()


# ==================== 行高自适应(照旧 Exceljh.CalcWrapLines/CalcPlanRowHeight) ====================

def _wrap_lines(text, col_width):
    if not text:
        return 1
    px = float(col_width) * 7 + 5
    lines = 0
    for seg in str(text).replace("\r", "").split("\n"):
        i, n = 0, len(seg)
        if n == 0:
            lines += 1
            continue
        while i < n:
            used = 0
            j = i
            while j < n:
                w = 12 if ord(seg[j]) > 0xFF else 6
                if used + w > px:
                    break
                used += w
                j += 1
            if j == i:
                j = i + 1
            lines += 1
            i = j
    return max(lines, 1)


def _plan_row_height(name, bz, dn_width, bz_width):
    lines = max(_wrap_lines(name, dn_width), _wrap_lines(bz, bz_width))
    if lines <= 1:
        return 25.0
    return 30.0 + (lines - 2) * 12.0


# ==================== 计划格式(实施单表/汇总) ====================

PLAN_CATEGORIES = ["更新改造", "大修理", "科技项目", "长期待摊", "管道工程", "中期更新", "中期大修"]

LAYOUTS = {
    "更新改造": {
        "headers": ["编号", "类别", "项目名称", "项目说明及测算依据", "项目计划总投资",
                    "本年计划投资", "开工年月", "竣工年月", "新建/续建", "主办单位", "负责人", "备注"],
        "widths": [7.12, 10.12, 38, 48.75, 10.5, 10.5, 9.12, 9.12, 8.5, 9.12, 8.5, 8.88],
        "group": True, "sub_merge": 4, "sum_col": 5, "jine_col": 4,
        "title_h": 44, "sub_h": 15.75, "head_h": 24.95,
        "dn_w": 38, "bz_w": 48.75,
    },
    "大修理": {
        "headers": ["编号", "小类别", "项目名称", "项目说明", "投资(万元)", "主办单位", "负责人", "备注"],
        "widths": [7.12, 10.12, 38, 48.75, 10.5, 9.12, 8.5, 8.75],
        "group": True, "sub_merge": 4, "sum_col": 4,
        "title_h": 30, "sub_h": 29, "head_h": 25.35,
        "dn_w": 38, "bz_w": 48.75,
    },
    "科技项目": {
        "headers": ["编号", "小类别", "项目名称", "项目说明及测算依据", "投资(万元)",
                    "主办单位", "负责人", "备注"],
        "widths": [7.38, 11.57, 39, 59.62, 10.5, 10.62, 8.5, 11.62],
        "group": False, "sub_merge": 4, "sum_col": 4,
        "title_h": 30, "sub_h": 29, "head_h": 25.35,
        "dn_w": 39, "bz_w": 59.62,
    },
    "长期待摊": {
        "headers": ["编号", "项目名称", "项目说明及测算依据", "投资(万元)", "主办单位", "负责人", "备注"],
        "widths": [7.38, 38.88, 53.5, 10.5, 9.62, 8.5, 8.62],
        "group": True, "sub_merge": 3, "sum_col": 3,
        "title_h": 30, "sub_h": 29, "head_h": 25.35,
        "dn_w": 38.88, "bz_w": 53.5,
    },
    "管道工程": {
        "headers": ["编号", "项目名称", "项目说明及测算依据", "投资(万元)", "主办单位", "负责人", "备注"],
        "widths": [7.38, 38.88, 53.5, 10.5, 9.62, 8.5, 8.62],
        "group": True, "sub_merge": 3, "sum_col": 3,
        "title_h": 30, "sub_h": 29, "head_h": 25.35,
        "dn_w": 38.88, "bz_w": 53.5,
    },
    "中期更新": {
        "headers": ["序号", "项目名称", "年初预算", "中期调整后",
                    "调整数（调增为正数，调减为负数）", "调整事由",
                    "调整数影响的报表科目\n（调整数根据调整表分解，自行插入行）"],
        "widths": [8.75, 30.12, 13.38, 13.62, 12.12, 36, 16],
        "group": False, "mid": True,
        "title_h": 25.5, "sub_h": 24, "head_h": 78,
        "dn_w": 30.12, "bz_w": 36,
    },
    "中期大修": {
        "headers": ["序号", "项目名称", "年初预算", "中期调整后",
                    "调整数（调增为正数，调减为负数）", "调整事由",
                    "调整数影响的报表科目\n（调整数根据调整表分解，自行插入行）"],
        "widths": [8.75, 29.62, 12.12, 11.38, 10.62, 38.62, 16.62],
        "group": False, "mid": True,
        "title_h": 25.5, "sub_h": 23, "head_h": 84,
        "dn_w": 29.62, "bz_w": 38.62,
    },
}


def _plan_data_row(ws, row, r, lb, layout, styles):
    left, center = styles["left"], styles["center"]
    if lb == "更新改造":
        vals = [
            r.get("xuhao", ""), r.get("leibie", ""), r.get("daibanname", ""), r.get("bz", ""),
            _num(r.get("jine")), _num(r.get("zongtouzi")),
            _format_year_month(r.get("kgny")), _format_year_month(r.get("jgny")),
            r.get("xjxl", ""), r.get("zb", ""), r.get("fzr", ""), "",
        ]
        align = [center, left, left, left, center, center, center, center, center, left, left, left]
    elif lb == "大修理":
        vals = [
            r.get("xuhao", ""), r.get("leibie", ""), r.get("daibanname", ""), r.get("bz", ""),
            _num(r.get("jine")), r.get("zb", ""), r.get("fzr", ""), "",
        ]
        align = [center, left, left, left, center, left, left, left]
    elif lb == "科技项目":
        vals = [
            r.get("xuhao", ""), r.get("leibie", ""), r.get("daibanname", ""), r.get("bz", ""),
            _num(r.get("jine")), r.get("zb", ""), r.get("fzr", ""), "",
        ]
        align = [center, left, left, left, center, left, left, left]
    elif lb in ("长期待摊", "管道工程"):
        vals = [
            r.get("xuhao", ""), r.get("daibanname", ""), r.get("bz", ""),
            _num(r.get("jine")), r.get("zb", ""), r.get("fzr", ""), "",
        ]
        align = [center, left, left, center, left, left, left]
    else:  # 中期更新/中期大修
        start = _num(r.get("startjine")) or 0
        jine = _num(r.get("jine")) or 0
        vals = [
            row - 3, r.get("daibanname", ""), start, jine, round(jine - start, 4),
            r.get("bz", ""), r.get("pizhu", ""),
        ]
        align = [center, left, center, center, center, left, left]

    for i, v in enumerate(vals):
        _put(ws, row, i + 1, v, center if align[i] == "center" else left)
    ws.row_dimensions[row].height = _plan_row_height(
        r.get("daibanname", ""), r.get("bz", ""), layout["dn_w"], layout["bz_w"],
    )


def _sum_row(ws, row, label, layout, styles, subtotal_cells=None, total_cells=None):
    ncol = len(layout["headers"])
    center = styles["center"]
    for c in range(1, ncol + 1):
        _put(ws, row, c, None, center)
    ws.cell(row=row, column=1).value = label
    merge_to = layout.get("mid") and 2 or layout.get("sub_merge", 4)
    _merge(ws, row, row, 1, merge_to)
    ws.row_dimensions[row].height = 22


def _write_plan_sheet(ws, rows, year, lb, styles):
    layout = LAYOUTS[lb]
    ncol = len(layout["headers"])
    ws.sheet_view.showGridLines = False

    for i, w in enumerate(layout["widths"], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 标题 / 副标题 / 表头
    title = (
        f"{year}年更新改造项目中期调整表" if lb == "中期更新"
        else f"{year}年大修理项目中期调整表" if lb == "中期大修"
        else f"厦门市政水务集团有限公司售水事业部{year}年{lb}计划"
    )
    _merge(ws, 1, 1, 1, ncol)
    _put(ws, 1, 1, title, styles["title"])
    ws.row_dimensions[1].height = layout["title_h"]

    _put(ws, 2, 1, "编制单位：售水事业部" if lb not in ("中期更新", "中期大修") else "填报单位：",
         styles["subtitle"])
    if lb not in ("中期更新", "中期大修"):
        _put(ws, 2, ncol, "金额单位：万元", styles["unit"])
    else:
        _put(ws, 2, 2, "售水事业部", styles["subtitle_left"])
        _put(ws, 2, ncol, "金额单位：万元", styles["unit"])
    ws.row_dimensions[2].height = layout["sub_h"]

    for i, h in enumerate(layout["headers"], start=1):
        _put(ws, 3, i, h, styles["head"])
    ws.row_dimensions[3].height = layout["head_h"]

    row = 4
    if layout.get("mid"):
        for r in rows:
            _plan_data_row(ws, row, r, lb, layout, styles)
            row += 1
        total_row = row
        _sum_row(ws, total_row, "合  计", layout, styles)
        for c in (3, 4, 5):
            letter = get_column_letter(c)
            _put(ws, total_row, c, f"=SUM({letter}4:{letter}{total_row - 1})", styles["center"])
        ws.row_dimensions[total_row].height = 22
        return

    if not layout["group"]:
        for r in rows:
            _plan_data_row(ws, row, r, lb, layout, styles)
            row += 1
        total_row = row
        _sum_row(ws, total_row, "合  计", layout, styles)
        col = layout["sum_col"] + 1
        letter = get_column_letter(col)
        if total_row > 4:
            _put(ws, total_row, col, f"=SUM({letter}4:{letter}{total_row - 1})", styles["center"])
        else:
            _put(ws, total_row, col, 0, styles["center"])
        ws.row_dimensions[total_row].height = 22
        return

    # 按所属部门分组:部门行 -> 明细 -> 小计
    groups = []
    current = None
    for r in rows:
        name = r.get("ssbm") or "未知部门"
        if current is None or current[0] != name:
            current = (name, [])
            groups.append(current)
        current[1].append(r)

    subtotal_rows = []
    for dept_name, items in groups:
        for c in range(1, ncol + 1):
            _put(ws, row, c, dept_name if c == 1 else None, styles["center"])
        _merge(ws, row, row, 1, ncol)
        ws.row_dimensions[row].height = 24.95
        row += 1

        first_data = row
        for r in items:
            _plan_data_row(ws, row, r, lb, layout, styles)
            row += 1
        last_data = row - 1

        sub_row = row
        _sum_row(ws, sub_row, "小  计", layout, styles)
        sum_col = layout["sum_col"] + 1
        letter = get_column_letter(sum_col)
        if last_data >= first_data:
            _put(ws, sub_row, sum_col, f"=SUM({letter}{first_data}:{letter}{last_data})", styles["center"])
        else:
            _put(ws, sub_row, sum_col, 0, styles["center"])
        if lb == "更新改造":
            letter_e = get_column_letter(layout["jine_col"] + 1)
            _put(ws, sub_row, layout["jine_col"] + 1,
                 f"=SUM({letter_e}{first_data}:{letter_e}{last_data})" if last_data >= first_data else 0,
                 styles["center"])
        subtotal_rows.append(sub_row)
        row += 1

    total_row = row
    _sum_row(ws, total_row, "合  计", layout, styles)
    sum_col = layout["sum_col"] + 1
    letter = get_column_letter(sum_col)
    if subtotal_rows:
        args = ",".join(f"{letter}{r}" for r in subtotal_rows)
        _put(ws, total_row, sum_col, f"=SUM({args})", styles["center"])
        if lb == "更新改造":
            le = get_column_letter(layout["jine_col"] + 1)
            args_e = ",".join(f"{le}{r}" for r in subtotal_rows)
            _put(ws, total_row, layout["jine_col"] + 1, f"=SUM({args_e})", styles["center"])
    else:
        _put(ws, total_row, sum_col, 0, styles["center"])


def _styles_for(wb):
    return {
        "left": _style("left"),
        "center": _style("center"),
        "title": _style("center", 14, True),
        "subtitle": _style("left", 12, True, wrap=False),
        "subtitle_left": _style("left", 9, False, wrap=False),
        "unit": _style("right", 12, True, wrap=False),
        "head": _style("center", 10, True),
    }


def _write_cover(wb, year, categories):
    ws = wb.active
    ws.title = "封面"
    ws.sheet_view.showGridLines = False
    for i in range(1, 13):
        ws.column_dimensions[get_column_letter(i)].width = 8.75
    if categories:
        names = [c for c in PLAN_CATEGORIES if c in categories]
        title = f"售水事业部{year}年度" + ("、".join(names) if names else "更新改造、大修理、科技项目") + "计划"
    else:
        title = f"售水事业部{year}年度更新改造、大修理、科技项目计划"
    _merge(ws, 18, 18, 3, 12)
    cell = ws.cell(row=18, column=3, value=title)
    cell.font = Font(name=FONT_NAME, size=20, bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[18].height = 76
    now = datetime.now()
    _merge(ws, 20, 20, 7, 8)
    date_cell = ws.cell(row=20, column=7, value=f"{now.year}/{now.month}/{now.day}")
    date_cell.font = Font(name=FONT_NAME, size=12)
    date_cell.alignment = Alignment(horizontal="center", vertical="center")


def export_plan_workbook(rows_by_category: dict, year, categories=None) -> bytes:
    """完整计划:封面 + 各类别 sheet(标题/部门分组/小计/合计)。"""
    wb = Workbook()
    _write_cover(wb, year, categories)
    styles = _styles_for(wb)
    for lb in PLAN_CATEGORIES:
        if categories is not None and lb not in categories:
            continue
        ws = wb.create_sheet(lb)
        _write_plan_sheet(ws, rows_by_category.get(lb, []), year, lb, styles)
    return to_bytes(wb)


def export_plan_sheet(rows: list[dict], year, lb: str = "更新改造") -> bytes:
    """当前页/单类别计划:与完整计划同一版式(含部门分组/小计/合计)。"""
    lb = lb if lb in LAYOUTS else "更新改造"
    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}年度计划"
    _write_plan_sheet(ws, rows, year, lb, _styles_for(wb))
    return to_bytes(wb)


# ==================== 正式计划(导出正式计划.xls 版式) ====================

OFFICIAL_HEADERS = [
    "编号", "计划类别", "年度", "部门", "项目名称", "项目说明", "投资额", "主办单位",
    "负责人", "备注", "已付款", "项目状态", "专管员", "进度数值", "进度描述",
    "最新日期", "开工日期", "合同签订日期",
]
OFFICIAL_WIDTHS = [
    7.12, 11.75, 8, 14.5, 38, 48.75, 10.5, 9.12, 8.5, 11.57,
    15, 19.85, 15.4, 17.14, 40, 12, 12, 12,
]


def _official_sheet(wb, title, headers, widths, data_rows, title_height=45.75):
    ws = wb.active
    ws.title = "更新改造"
    ws.sheet_view.showGridLines = False
    ncol = len(headers)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    _merge(ws, 1, 1, 1, ncol)
    _put(ws, 1, 1, title, _style("center", 16, True, wrap=False))
    ws.row_dimensions[1].height = title_height
    head = _style("center", 10, True)
    for i, h in enumerate(headers, start=1):
        _put(ws, 2, i, h, head)
    ws.row_dimensions[2].height = 24.95
    left, center = _style("left"), _style("center")
    for idx, values in enumerate(data_rows, start=3):
        for c, v in enumerate(values, start=1):
            _put(ws, idx, c, v, center if c in (1, 2, 3, 7, 11, 14, 16, 17, 18) else left)
        ws.row_dimensions[idx].height = 24.95
    return ws


def export_official(rows: list[dict], year=None, lb: str = "") -> bytes:
    title = f"厦门市政水务集团有限公司售水事业部{year}年{lb or '更新改造'}计划" if year else (lb or "更新改造计划")
    data_rows = [[
        r.get("xh", ""), r.get("lb", ""), r.get("nd"), r.get("bm", ""), r.get("name", ""),
        r.get("bz", ""), _num(r.get("jine")), r.get("zb", ""), r.get("fzr", ""),
        r.get("xmbz", ""), _num(r.get("zongji")), r.get("jdzt", ""), r.get("zgy", ""),
        r.get("jdztValue"), r.get("jdztDesc", ""), _slash_date(r.get("latest_riqi")),
        _slash_date(r.get("kaigong_date")), _slash_date(r.get("hetong_date")),
    ] for r in rows]
    wb = Workbook()
    _official_sheet(wb, title, OFFICIAL_HEADERS, OFFICIAL_WIDTHS, data_rows)
    return to_bytes(wb)


def export_yyfq(rows: list[dict], year=None) -> bytes:
    """营业所发起导出:照旧使用正式计划模板,只保留前 13 列。"""
    title = f"更新改造计划" if not year else f"{year}年度更新改造计划"
    data_rows = [[
        "", r.get("jhlb", ""), r.get("niandu"), r.get("bm", ""), r.get("faqiname", ""),
        r.get("bz", ""), _num(r.get("jine")), "", "", "", "", "", r.get("zgy", ""),
    ] for r in rows]
    wb = Workbook()
    _official_sheet(wb, title, OFFICIAL_HEADERS[:13], OFFICIAL_WIDTHS[:13], data_rows)
    return to_bytes(wb)


# ==================== 进度 / 售水填报记录(平表) ====================

def _flat_sheet(wb, title, headers, rows, widths, center_cols=()):
    ws = wb.active
    ws.title = title
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    head = _style("center", 10, True)
    for i, h in enumerate(headers, start=1):
        _put(ws, 1, i, h, head)
    ws.row_dimensions[1].height = 24.95
    left, center = _style("left"), _style("center")
    for idx, values in enumerate(rows, start=2):
        for c, v in enumerate(values, start=1):
            _put(ws, idx, c, "" if v is None else v, center if c in center_cols else left)
        ws.row_dimensions[idx].height = 22
    ws.freeze_panes = "A2"
    return ws


def export_progress(rows: list[dict]) -> bytes:
    headers = ["计划名称", "年度", "所属部门", "主办部门", "日期", "进度状态", "描述",
               "付款金额(万元)", "备注", "操作人", "操作时间", "项目备注"]
    data = [[
        r.get("plan_name", ""), r.get("nd"), r.get("bm", ""), r.get("zb", ""),
        r.get("riqi", ""), r.get("leixing", ""), r.get("miaoshu", ""),
        round(float(r.get("fukuan") or 0) / 10000, 4), r.get("beizhu", ""),
        r.get("username", ""), r.get("caozuotime", ""), r.get("xmbz", ""),
    ] for r in rows]
    wb = Workbook()
    _flat_sheet(wb, "进度明细", headers, data,
                [20, 8, 14, 14, 12, 12, 20, 14, 20, 10, 16, 18],
                center_cols=(2, 5, 6, 8, 10, 11))
    return to_bytes(wb)


def export_ssdb(rows: list[dict], sheet_title="计划明细") -> bytes:
    """兼容旧调用:平表导出行数据。"""
    headers = [
        "流水号", "计划号", "小类别", "所属部门", "项目名称", "项目说明", "计划总投资(万元)",
        "年初金额(万元)", "本年计划投资(万元)", "调增/调减(万元)", "主办部门", "负责人",
        "专管员", "上报员", "计划类别", "状态", "开工年月", "竣工年月", "新建/续建",
        "批注", "最后操作", "最后操作日期", "年度", "排序号",
    ]
    data = []
    for r in rows:
        jine = float(r.get("jine") or 0)
        start = r.get("startjine")
        tz = round(jine - float(start), 2) if start is not None else ""
        data.append([
            r.get("ID"), r.get("xuhao", ""), r.get("leibie", ""), r.get("ssbm", ""),
            r.get("daibanname", ""), r.get("bz", ""), jine, start, r.get("zongtouzi"),
            tz, r.get("zb", ""), r.get("fzr", ""), r.get("username", ""),
            r.get("opname", ""), r.get("jhlb", ""), r.get("zt", ""), r.get("kgny", ""),
            r.get("jgny", ""), r.get("xjxl", ""), r.get("pizhu", ""), r.get("lastop", ""),
            r.get("dbtimep", ""), r.get("niandu"), r.get("nxuhao"),
        ])
    wb = Workbook()
    _flat_sheet(wb, sheet_title, headers, data,
                [9, 12, 10, 18, 34, 55, 15, 15, 15, 15, 16, 10, 10, 10, 12, 13, 11, 11, 10,
                 24, 10, 18, 8, 8])
    return to_bytes(wb)


def export_reported(rows: list[dict], year) -> bytes:
    headers = ["计划号", "主办单位", "负责人", "项目名称", "项目说明", "计划总投资(万元)",
               "年度", "专管员", "操作员", "状态", "最后操作日期", "计划类别", "所属部门", "最后操作"]
    data = [[
        r.get("xuhao", ""), r.get("zb", ""), r.get("fzr", ""), r.get("faqiname", ""),
        r.get("bz", ""), r.get("jine"), r.get("niandu"), r.get("zgy", ""), r.get("op", ""),
        r.get("zt", ""), r.get("fqtimep", ""), r.get("jhlb", ""), r.get("bm", ""),
        r.get("lastop", ""),
    ] for r in rows]
    wb = Workbook()
    _flat_sheet(wb, f"{year}售水填报记录", headers, data,
                [12, 18, 10, 34, 55, 15, 8, 10, 10, 13, 18, 12, 18, 10],
                center_cols=(1, 6, 7, 8, 10, 11))
    return to_bytes(wb)


# ==================== 导入模板 ====================

def template_yyfq() -> bytes:
    """营业所更新改造计划模板:第 1 行标题、第 2 行表头、第 3 行起填数据。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "更新改造"
    ws.sheet_view.showGridLines = False
    headers = ["计划项目名称", "项目说明", "金额（万元）", "售水专管员姓名", "计划类别（更新改造/其他类别）"]
    widths = [29.5, 45.4, 17.25, 15.5, 27.6]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    _merge(ws, 1, 1, 1, 5)
    _put(ws, 1, 1, "营业所更新改造计划模板", _style("center", 14, True))
    ws.row_dimensions[1].height = 42.75
    for i, h in enumerate(headers, start=1):
        _put(ws, 2, i, h, _style("center", 10, True))
    ws.row_dimensions[2].height = 37.5
    for c in range(1, 6):
        _put(ws, 3, c, "", _style("left"))
    ws.row_dimensions[3].height = 24.95
    return to_bytes(wb)


def template_ssdb(host_name: str = "", dept_name: str = "") -> bytes:
    """计划.xls 模板:第 1 行表头,第 2 行起为数据。"""
    headers = ["年度", "小类别", "项目名称", "项目说明", "金额(万元)",
               "主办部门", "所属部门", "计划类别"]
    wb = Workbook()
    ws = wb.active
    ws.title = "计划"
    ws.sheet_view.showGridLines = False
    for i, w in enumerate([8, 10, 34, 55, 14, 18, 18, 12], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for i, h in enumerate(headers, start=1):
        _put(ws, 1, i, h, _style("center", 10, True))
    ws.row_dimensions[1].height = 24.95
    _put(ws, 2, 1, "", _style("left"))
    return to_bytes(wb)
