"""传导完好率分组 Excel 导入/导出(照旧 NPOI 模板版式,统一输出 .xlsx)。

- 完好率汇总表:3 个 sheet「统计 / 变动 / 故障」,公司版按 5 个营业所分列,
  营业所版只出本部门;旧模板是 .xls 且靠 ShiftRows 插行,这里用 openpyxl 直接排版,
  标题 `{bt}传导设备完好率统计表`、11 列统计表 + 合计公式 + 制表人均照旧。
- 大修明细:单 sheet 两级表头 15 列(设备大修/更新记录、口径、备注、施工情况分组)。
- 变动表:下载 2 列模板(设备名称/变动类型),上传从第 2 行起逐行导入,空首列停止。
  ⚠️ 旧模板里残留一批超市商品示例数据,新模板只保留表头,避免误导入。
"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

THIN = Side(style="thin", color="7f8c8d")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="dce6f1")
TOTAL_FILL = PatternFill("solid", fgColor="fff2cc")
TITLE_FONT = Font(bold=True, size=15, color="1f2937")
HEAD_FONT = Font(bold=True, size=10, color="1f2937")
CELL_FONT = Font(size=10, color="1f2937")


def content_disposition(filename: str) -> str:
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")


def _cell(ws, row, col, value=None, *, bold=False, fill=None, align="center",
          wrap=False, fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    c.border = BORDER
    c.font = Font(bold=bold, size=10, color="1f2937") if not bold else HEAD_FONT
    c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    return c


def _title(ws, text, last_col, row=1):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    c = ws.cell(row=row, column=1, value=text)
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 30


def _widths(ws, values):
    for i, w in enumerate(values, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _xlsx(wb: Workbook) -> BytesIO:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _by_dept(items: list, names: dict, order: list) -> list:
    """按旧模板部门顺序归集;模板外的部门按名称追加。"""
    grouped = {}
    for it in items:
        name = it.get("bumen") or names.get(it.get("bmid")) or ""
        grouped.setdefault(name, []).append(it)
    keys = [n for n in order if n in grouped] + sorted(
        n for n in grouped if n not in order
    )
    return [(k, grouped[k]) for k in keys]


def build_whl_excel(bt: str, whl_items: list, xz_items: list, gz_items: list,
                    names: dict, dept_label: str, operator: str) -> BytesIO:
    """完好率汇总表(统计/变动/故障 3 sheet)。dept_label 为编制单位名称。"""
    wb = Workbook()

    # ---------- sheet1 统计 ----------
    ws = wb.active
    ws.title = "统计"
    _title(ws, f"{bt}传导设备完好率统计表", 11)
    _cell(ws, 2, 1, f"编制单位:{dept_label}", align="left")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=11)
    headers = [
        "单位名称", "设备台数（台）", "实有台时数", "故障台时数", "完好台时数",
        "设备完好率%", "本月新增设备台数（台）", "本月报废设备台数",
        "本月调出设备台数", "本月停用设备台数", "备注",
    ]
    for i, h in enumerate(headers, start=1):
        _cell(ws, 3, i, h, bold=True, fill=HEAD_FILL, wrap=True)
    ws.row_dimensions[3].height = 34
    _widths(ws, [16, 13, 14, 13, 14, 12, 15, 14, 14, 14, 16])

    grouped = _by_dept(whl_items, names,
                       ["厦门营业所", "翔安营业所", "海沧营业所", "集美营业所", "同安营业所"])
    r = 4
    for dept, rows in grouped:
        # 同部门同月理论一行;历史重复行照旧累加
        total = lambda k: sum(float(x.get(k) or 0) for x in rows)  # noqa: E731
        sytss = total("sytss")
        decwh = total("decwhtss")
        values = [
            dept, total("ts"), sytss, total("decgztss"), decwh,
            round(decwh / sytss * 100, 2) if sytss else None,
            total("xzts"), total("bfts"), total("dcts"), total("tyts"),
            " ".join(x.get("bz") or "" for x in rows).strip(),
        ]
        for i, v in enumerate(values, start=1):
            _cell(ws, r, i, v, align="left" if i in (1, 11) else "center")
        r += 1
    if r == 4:  # 无数据也保留一行空部门,避免合计公式引用空区间
        for i in range(1, 12):
            _cell(ws, r, i, dept_label if i == 1 else None)
        r += 1
    first, last = 4, r - 1
    sum_row = r
    _cell(ws, sum_row, 1, "合         计", bold=True, fill=TOTAL_FILL)
    for col in (2, 3, 4, 5, 7, 8, 9, 10):
        letter = get_column_letter(col)
        _cell(ws, sum_row, col, f"=SUM({letter}{first}:{letter}{last})",
              bold=True, fill=TOTAL_FILL)
    _cell(ws, sum_row, 6, f"=IF(C{sum_row}=0,0,ROUND(E{sum_row}/C{sum_row}*100,2))",
          bold=True, fill=TOTAL_FILL)
    _cell(ws, sum_row, 11, "", fill=TOTAL_FILL)
    _cell(ws, sum_row + 2, 8, f"制表：{operator}", align="left")

    # ---------- sheet2 变动 ----------
    ws2 = wb.create_sheet("变动")
    _title(ws2, f"{bt}传导设备变动明细表", 3)
    _widths(ws2, [10, 62, 4])
    r = 2
    for lb in ["新增设备", "报废设备", "调出设备", "停用设备"]:
        _cell(ws2, r, 1, f"本月{lb}明细", bold=True, fill=HEAD_FILL, align="left")
        ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        r += 1
        _cell(ws2, r, 1, "序号", bold=True, fill=HEAD_FILL)
        _cell(ws2, r, 2, "设备名称", bold=True, fill=HEAD_FILL)
        r += 1
        rows = [x for x in xz_items if (x.get("bdlb") or "") == lb]
        for idx, item in enumerate(rows, start=1):
            _cell(ws2, r, 1, idx)
            _cell(ws2, r, 2, item.get("sbname") or "", align="left", wrap=True)
            r += 1
        r += 1

    # ---------- sheet3 故障 ----------
    ws3 = wb.create_sheet("故障")
    _title(ws3, f"{bt}传导设备故障情况明细", 8)
    _cell(ws3, 2, 1, f"制表：{dept_label}", align="left")
    ws3.merge_cells(start_row=2, start_column=1, end_row=2, end_column=3)
    _widths(ws3, [8, 22, 12, 12, 32, 26, 24, 12])
    gz_headers = ["序号", "故障设备名称", "管径", "管材", "故障地点",
                  "故障发生日期", "故障原因", "故障时数"]
    r = 3
    for dept, rows in _by_dept(gz_items, names,
                               ["海沧营业所", "厦门营业所", "集美营业所",
                                "翔安营业所", "同安营业所"]):
        _cell(ws3, r, 1, dept, bold=True, fill=HEAD_FILL, align="left")
        ws3.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
        r += 1
        for i, h in enumerate(gz_headers, start=1):
            _cell(ws3, r, i, h, bold=True, fill=HEAD_FILL, wrap=True)
        r += 1
        total_ts = 0.0
        for idx, it in enumerate(rows, start=1):
            period = (it.get("ksdate") or "") + "至" + (it.get("jsdate") or "")
            vals = [idx, it.get("sbname"), it.get("guanjing"), it.get("guancai"),
                    it.get("didian"), period, it.get("yy"), it.get("dects")]
            for i, v in enumerate(vals, start=1):
                _cell(ws3, r, i, v, align="left" if i in (2, 5, 7) else "center",
                      wrap=i in (2, 5, 7))
            total_ts += float(it.get("dects") or 0)
            r += 1
        _cell(ws3, r, 1, "合计", bold=True, fill=TOTAL_FILL)
        for i in range(2, 8):
            _cell(ws3, r, i, "", fill=TOTAL_FILL)
        _cell(ws3, r, 8, total_ts, bold=True, fill=TOTAL_FILL)
        r += 1
    return _xlsx(wb)


def build_daxiu_excel(bt: str, items: list) -> BytesIO:
    """传导设备大修/更新记录(照旧「传导设备大修明细表.xls」两级表头 15 列)。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "大修记录"
    _title(ws, f"{bt}厦门市政水务集团传导设备大修/更新记录", 15)
    # 第 2 行分组头
    groups = [
        (1, 1, "编号"), (2, 2, "部门"), (3, 5, "设备大修/更新记录"),
        (6, 6, "工单号"), (7, 10, "口径"), (11, 11, "数量"),
        (12, 12, "备注"), (13, 13, "其他"), (14, 15, "施工情况"),
    ]
    for c1, c2, text in groups:
        if c1 != c2:
            ws.merge_cells(start_row=2, start_column=c1, end_row=2, end_column=c2)
        _cell(ws, 2, c1, text, bold=True, fill=HEAD_FILL)
        for c in range(c1, c2 + 1):
            ws.cell(row=2, column=c).border = BORDER
    # 第 3 行子表头(rowspan 列合并 2~3 行)
    rowspan = [(1, "编号"), (2, "部门"), (6, "工单号"), (11, "数量"),
               (12, "外力损坏"), (13, "存放地点")]
    for c, text in rowspan:
        ws.merge_cells(start_row=2, start_column=c, end_row=3, end_column=c)
        _cell(ws, 2, c, text, bold=True, fill=HEAD_FILL)
        ws.cell(row=3, column=c).border = BORDER
    subs = ["日期", "大修/更新类别", "项目内容（更新、大修地点）", "管道", "修补器",
            "阀门", "消防栓", "施工员", "电话"]
    for c, text in zip([3, 4, 5, 7, 8, 9, 10, 14, 15], subs):
        _cell(ws, 3, c, text, bold=True, fill=HEAD_FILL, wrap=True)
    ws.row_dimensions[3].height = 30
    _widths(ws, [7, 14, 13, 14, 34, 14, 11, 11, 11, 11, 8, 14, 14, 12, 14])

    r = 4
    for idx, it in enumerate(items, start=1):
        vals = [
            idx, it.get("bumen"), it.get("daxiudate"), it.get("lb"), it.get("nr"),
            it.get("gdh"), it.get("gdkj"), it.get("xbqkj"), it.get("fmkj"),
            it.get("xfskj"), it.get("num"), it.get("bz"), it.get("cfd"),
            it.get("sgy"), it.get("sgtel"),
        ]
        for c, v in enumerate(vals, start=1):
            _cell(ws, r, c, v, align="left" if c == 5 else "center", wrap=c in (5, 13))
        r += 1
    return _xlsx(wb)


def build_bd_template() -> BytesIO:
    """变动表上传模板:2 列(A 设备名称 / B 变动类型),只保留表头。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    _cell(ws, 1, 1, "设备名称", bold=True, fill=HEAD_FILL)
    _cell(ws, 1, 2, "变动类型（新增设备/报废设备/调出设备/停用设备）",
          bold=True, fill=HEAD_FILL)
    _widths(ws, [52, 48])
    return _xlsx(wb)


def parse_bd_excel(content: bytes, filename: str) -> list:
    """解析上传模板:从第 2 行起,A=设备名称(空即停止),B=变动类别。

    旧系统要求文件名恰为「传导设备变动表.xls」且只认 .xls;新模板改发 .xlsx,
    因此放宽为「传导设备变动表」开头 + .xls/.xlsx 两种后缀。
    """
    name = (filename or "").strip()
    if not name.startswith("传导设备变动表"):
        raise ValueError("请上传名为“传导设备变动表”的模板文件")
    low = name.lower()
    rows = []
    if low.endswith(".xls"):
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=content)
        except Exception as exc:
            raise ValueError(f"无法读取 Excel 模板:{exc}") from exc
        sheet = book.sheet_by_index(0)
        for i in range(1, sheet.nrows):
            sbname = str(sheet.cell_value(i, 0) or "").strip()
            if not sbname:
                break
            bdlb = str(sheet.cell_value(i, 1) or "").strip() if sheet.ncols > 1 else ""
            rows.append((sbname, bdlb))
    elif low.endswith(".xlsx"):
        try:
            book = load_workbook(BytesIO(content), data_only=True)
        except Exception as exc:
            raise ValueError(f"无法读取 Excel 模板:{exc}") from exc
        sheet = book.worksheets[0]
        for r in range(2, sheet.max_row + 1):
            sbname = str(sheet.cell(row=r, column=1).value or "").strip()
            if not sbname or sbname.lower() == "none":
                break
            bdlb = str(sheet.cell(row=r, column=2).value or "").strip()
            rows.append((sbname, bdlb))
    else:
        raise ValueError("请上传 .xls 或 .xlsx 格式的传导设备变动表")
    if not rows:
        raise ValueError("模板中没有可导入的数据")
    return rows
