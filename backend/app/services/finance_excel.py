"""财务管理三模块的 Excel 导入/导出(照旧 NPOI 模板列序,统一输出 .xlsx)。

- 固定资产:固定资产明细表(17 列) / 固定资产盘点表(14 列 + 合计 + 签字行)
- 清理报告:清理报告(9 列 + 合计 + 申请原因/签章栏)
- 物资采购申请:申请单 / 验收单 / 明细模板,以及明细 Excel 与盘点表 Excel 的解析
"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

THIN = Side(style="thin", color="9aa4b2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="e8eef5")
TOTAL_FILL = PatternFill("solid", fgColor="fff2cc")


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码报 500。"""
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")


def _sheet(wb, title, headers, widths=None):
    ws = wb.active
    ws.title = title
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, size=11, color="1f2937")
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
        if widths and i <= len(widths):
            ws.column_dimensions[c.column_letter].width = widths[i - 1]
    ws.row_dimensions[1].height = 24
    return ws


def _title_row(ws, text, last_col, row=1, size=15):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(bold=True, size=size, color="1f2937")
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 30


def _write_rows(ws, data_rows, start_row=2, numeric_cols=(), text_cols=()):
    for r, values in enumerate(data_rows, start=start_row):
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value if value not in (None, "") else "")
            cell.border = BORDER
            if c in numeric_cols:
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif c in text_cols:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")


def _finish(wb) -> BytesIO:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ==================== 固定资产:明细表 / 盘点表 ====================
GDZC_DETAIL_HEADERS = [
    "固定资产类别", "资产号", "设备名称", "数量", "在用地点", "设备启用日期",
    "原值", "净值", "规格型号", "设备编号", "期限", "已用", "所属的部门",
    "备注人", "备注", "备注日期", "盘点数量",
]


def gdzc_detail_excel(rows, nd, dept_name):
    """照旧 ExcelCW.ewk_Optimized 的 17 列;盘点状态为 NULL 写「盘亏」否则写数量。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "固定资产明细表"
    _title_row(ws, f"{dept_name}{nd}盘点年度固定资产明细表", 17)
    for i, h in enumerate(GDZC_DETAIL_HEADERS, start=1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = Font(bold=True, color="1f2937")
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = [16, 18, 24, 8, 14, 14, 16, 16,
                                                       20, 20, 8, 8, 16, 12, 26, 20, 12][i - 1]
    data = []
    for r in rows:
        data.append([
            r.get("lb", ""), r.get("zccode", ""), r.get("sbname", ""), r.get("num"),
            r.get("didian", ""), r.get("qyrq", ""), r.get("yz"), r.get("jz"),
            r.get("guige", ""), r.get("sbbh", ""), r.get("yujishiyong"),
            r.get("yishiyong"), r.get("bm", ""), r.get("beizhuren", ""),
            r.get("beizhu", ""), r.get("bzdate", "")[:19] if r.get("bzdate") else "",
            r.get("num") if r.get("pandian") else "盘亏",
        ])
    _write_rows(ws, data, start_row=3, numeric_cols=(7, 8), text_cols=(3, 9, 10, 15))
    return _finish(wb)


GDZC_PD_HEADERS = [
    "序号", "类别", "固定资产卡片号", "资产号", "集团设备卡编号", "设备名称",
    "规格", "原值", "净值", "始用日期", "账面数量", "盘点数量", "差异数量", "存放地点",
]


def gdzc_pandian_excel(rows, nd, dept_name):
    """照旧 ExcelCW.ewkPD_Optimized:第 3 行写年度/部门,数据从第 5 行起,末尾合计 + 签字行。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "固定资产盘点表"
    _title_row(ws, f"{nd}年度{dept_name}固定资产盘点表", 14)
    ws.cell(row=2, column=1, value="填报单位：").font = Font(bold=True)
    ws.cell(row=2, column=4, value=dept_name)
    ws.cell(row=2, column=7, value="截止日期：").font = Font(bold=True)
    ws.cell(row=2, column=9, value=f"{nd}.12.31")
    for i, h in enumerate(GDZC_PD_HEADERS, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="1f2937")
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = [7, 16, 18, 18, 18, 24, 18, 16,
                                                       16, 14, 12, 12, 12, 16][i - 1]
    ws.row_dimensions[3].height = 30
    data = []
    for i, r in enumerate(rows, start=1):
        # 照旧:账面数量/盘点数量都写 num,差异数量恒 0(不读 pandian)
        data.append([
            i, r.get("lb", ""), "", r.get("zccode", ""), r.get("sbbh", ""),
            r.get("sbname", ""), r.get("guige", ""), r.get("yz"), r.get("jz"),
            r.get("qyrq", ""), r.get("num"), r.get("num"), 0, r.get("didian", ""),
        ])
    _write_rows(ws, data, start_row=4, numeric_cols=(8, 9), text_cols=(6, 7))
    total_row = 4 + len(data)
    yz = sum(float(r.get("yz") or 0) for r in rows)
    jz = sum(float(r.get("jz") or 0) for r in rows)
    ws.cell(row=total_row, column=1, value="合计")
    ws.cell(row=total_row, column=8, value=yz).number_format = "#,##0.00"
    ws.cell(row=total_row, column=9, value=jz).number_format = "#,##0.00"
    for c in range(1, 15):
        cell = ws.cell(row=total_row, column=c)
        cell.border = BORDER
        cell.font = Font(bold=True)
        cell.fill = TOTAL_FILL
    sign = total_row + 1
    ws.merge_cells(start_row=sign, start_column=1, end_row=sign, end_column=14)
    ws.cell(row=sign, column=1,
            value="单位负责人：            财务负责人：            资产管理员：            盘点人：").alignment = \
        Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[sign].height = 30
    return _finish(wb)


# ==================== 清理报告 ====================
QLBG_HEADERS = ["设备编号", "财务编号", "设备名称", "规格型号", "单位", "数量",
                "安装地点", "启用日期", "原值", "累计折旧", "净值", "备注"]


def baofei_report_excel(rows, dept_name, main_id):
    """照旧 Excelqlbg:10 行数据区 + 合计行 + 申请原因/签章栏。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "清理报告"
    _title_row(ws, "厦门市政水务集团有限公司资产（设备）清理报告", 12)
    ws.cell(row=2, column=1, value=f"申请单位：{dept_name}")
    ws.cell(row=2, column=7, value="日期：").alignment = Alignment(horizontal="right")
    from datetime import datetime
    ws.cell(row=2, column=8, value=datetime.now().strftime("%Y-%m-%d"))
    ws.cell(row=2, column=9, value=f"编号：{main_id}")
    ws.cell(row=2, column=12, value="单位：（元）")
    for i, h in enumerate(QLBG_HEADERS, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="1f2937")
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = [18, 16, 22, 18, 8, 10, 16,
                                                       14, 16, 14, 16, 18][i - 1]
    data = []
    for r in rows:
        data.append([
            r.get("sbbh", ""), r.get("zccode", ""), r.get("sbname", ""),
            r.get("guige", ""), "台", r.get("num"), r.get("didian", ""),
            r.get("qyrq", ""), r.get("yz"), "", "", "",
        ])
    _write_rows(ws, data, start_row=4, numeric_cols=(9,), text_cols=(3, 4))
    # 模板固定 10 行数据区,合计行在第 14 行(索引 14)
    total_row = 14
    ws.cell(row=total_row, column=1, value="合计")
    ws.cell(row=total_row, column=6, value=sum(float(r.get("num") or 0) for r in rows))
    ws.cell(row=total_row, column=9, value=sum(float(r.get("yz") or 0) for r in rows))
    ws.cell(row=total_row, column=9).number_format = "#,##0.00"
    for c in range(1, 13):
        cell = ws.cell(row=total_row, column=c)
        cell.border = BORDER
        cell.font = Font(bold=True)
        cell.fill = TOTAL_FILL
    ws.merge_cells(start_row=15, start_column=1, end_row=15, end_column=12)
    ws.cell(row=15, column=1, value="申请原因：以上设备已到使用年限，且无利旧价值，现申请报废清理。")
    ws.merge_cells(start_row=16, start_column=1, end_row=16, end_column=12)
    ws.cell(row=16, column=1, value="管辖单位分管部门签章：            管辖单位经理签章：")
    ws.merge_cells(start_row=17, start_column=1, end_row=17, end_column=12)
    ws.cell(row=17, column=1, value="设备管理员签字：            部门负责人签字及部门：")
    return _finish(wb)


# ==================== 物资采购申请:申请单 / 验收单 / 模板 ====================
SQ_HEADERS = ["序号", "物品名称", "规格、型号", "单位", "数量", "单价", "小计", "备注"]
YS_HEADERS = ["序号", "物品名称", "规格、型号", "单位", "数量", "单价", "小计", "验收情况", "备注"]


def _wz_sheet(kind, main, mx, user_bm):
    is_sq = kind == "sq"
    headers = SQ_HEADERS if is_sq else YS_HEADERS
    n = len(headers)
    wb = Workbook()
    ws = wb.active
    ws.title = "物资采购申请单" if is_sq else "物资采购验收单"
    _title_row(ws, f"{user_bm}{ws.title}", n)
    ws.cell(row=2, column=1, value=("申请部门：" if is_sq else "部门名称：") + (main.get("bumen") or ""))
    ws.cell(row=2, column=4, value=("申购原因：" + (main.get("sgyy") or "")) if is_sq
            else "日期：" + (main.get("djriqi") or "")[:10])
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="1f2937")
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[c.column_letter].width = (
            [6, 22, 18, 9, 10, 12, 13, 18] if is_sq
            else [6, 20, 16, 8, 9, 11, 12, 12, 16])[i - 1]
    data = []
    for i, m in enumerate(mx, start=1):
        base = [i, m.get("wpmc", ""), m.get("ggxh", ""), m.get("danwei", ""),
                m.get("shuliang"), m.get("danjia"), m.get("xiaoji")]
        data.append(base + [m.get("beizhu", "")] if is_sq
                    else base + [m.get("ysqk", "") or "完成", m.get("beizhu", "")])
    _write_rows(ws, data, start_row=4, numeric_cols=(5, 6, 7), text_cols=(2, 3, 8, 9))
    total_row = 4 + len(data)
    ws.cell(row=total_row, column=1, value="合计")
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=6)
    cell = ws.cell(row=total_row, column=7, value=float(main.get("hj") or 0))
    cell.number_format = "#,##0.00"
    for c in range(1, n + 1):
        x = ws.cell(row=total_row, column=c)
        x.border = BORDER
        x.font = Font(bold=True)
        x.fill = TOTAL_FILL
    sign = total_row + 1
    ws.merge_cells(start_row=sign, start_column=1, end_row=sign, end_column=n)
    ws.cell(row=sign, column=1, value=("审核：                 申请人：" if is_sq
                                       else "验收：                 经办："))
    ws.row_dimensions[sign].height = 28
    ws.print_options.horizontalCentered = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    return _finish(wb)


def wzcgsq_sq_excel(main, mx, user_bm):
    return _wz_sheet("sq", main, mx, user_bm)


def wzcgsq_ys_excel(main, mx, user_bm):
    return _wz_sheet("ys", main, mx, user_bm)


def wzcgsq_template_excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    headers = ["物品名称", "规格、型号", "单位", "数量", "单价", "小计", "验收情况", "备注"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="1f2937")
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[c.column_letter].width = [22, 18, 10, 12, 12, 12, 14, 20][i - 1]
    for r in range(2, 22):
        for c in range(1, 9):
            ws.cell(row=r, column=c).border = BORDER
    tip = wb.create_sheet("填写说明")
    for i, line in enumerate([
        "1. 只需填写「明细」子表,物品名称、数量必填(数量须大于 0)。",
        "2. 数量、单价必须是数字;小计与合计由系统自动计算,「小计」列无需填写。",
        "3. 验收情况不填默认为「完成」;明细行数不限。",
    ], start=1):
        tip.cell(row=i, column=1, value=line)
    tip.column_dimensions["A"].width = 90
    return _finish(wb)


# ==================== 上传解析 ====================
def _cells(content: bytes, filename: str):
    """返回二维单元格值列表(兼容 .xls / .xlsx)。"""
    if filename.lower().endswith(".xls"):
        import xlrd
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_index(0)
        return [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)]
    import openpyxl
    book = openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
    sheet = book.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def _dec(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", "").replace("，", "").strip() or 0)


def _str(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_mx_excel(content: bytes, filename: str):
    """照旧 UploadMx:按表头文字定位列,物品名称必填且数量>0,小计由服务端重算。"""
    grid = _cells(content, filename)
    if not grid:
        raise ValueError("没有解析到有效明细行（物品名称、数量须填写，数量须大于0）")
    header = [_str(v).replace(" ", "").replace("　", "") for v in grid[0]]
    idx = {}
    for i, h in enumerate(header):
        if h:
            idx[h] = i
    if "物品名称" not in idx or "数量" not in idx:
        raise ValueError("请使用「下载明细模板」里的表头格式（须含物品名称、数量）")
    if "规格、型号" in idx:
        idx.setdefault("规格型号", idx["规格、型号"])

    def col(row, key):
        i = idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    rows, skipped = [], 0
    for row in grid[1:]:
        name = _str(col(row, "物品名称"))
        qty = _dec(col(row, "数量"))
        if not name or qty <= 0:
            if name:
                skipped += 1
            continue
        rows.append({
            "wpmc": name,
            "ggxh": _str(col(row, "规格型号")),
            "danwei": _str(col(row, "单位")),
            "shuliang": qty,
            "danjia": _dec(col(row, "单价")),
            "ysqk": _str(col(row, "验收情况")) or "完成",
            "beizhu": _str(col(row, "备注")),
        })
    if not rows:
        raise ValueError("没有解析到有效明细行（物品名称、数量须填写，数量须大于0）")
    return rows, skipped


def parse_pandian_excel(content: bytes, filename: str, categories: dict):
    """照旧 ExcelCW.exeExcel:第 0 行表头,列 0~12 固定映射;首列空终止。

    categories: {类别名: zc_lb.id};类别精确匹配,未知类别整单拒绝(补旧代码
    「提前 return 但已 Add 的行仍会提交」的 bug)。
    """
    grid = _cells(content, filename)
    if len(grid) < 2:
        raise ValueError("盘点表没有数据行")
    from datetime import date, datetime

    def num(row, i):
        return _dec(row[i]) if i < len(row) else 0.0

    def txt(row, i):
        return _str(row[i]) if i < len(row) else ""

    def to_date(row, i):
        v = row[i] if i < len(row) else None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        if isinstance(v, (int, float)) and v > 1:
            try:
                import xlrd
                return xlrd.xldate_as_datetime(float(v), 0).date()
            except Exception:
                return None
        s = _str(v)
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
        return None

    rows = []
    for row in grid[1:]:
        lb_name = txt(row, 0)
        if not lb_name:
            break
        if lb_name not in categories:
            raise ValueError(f"固定资产类别「{lb_name}」不存在,请先在类别字典中补录")
        qyrq = to_date(row, 5) or date(1900, 1, 1)
        rows.append({
            "lbid": categories[lb_name],
            "zccode": txt(row, 1), "sbname": txt(row, 2),
            "num": int(num(row, 3)), "didian": txt(row, 4),
            "qyrq": qyrq, "yz": num(row, 6), "jz": num(row, 7),
            "guige": txt(row, 8), "sbbh": txt(row, 9),
            "yujishiyong": int(num(row, 10)), "yishiyong": int(num(row, 11)),
            "nd": int(num(row, 12)) if num(row, 12) else None,
        })
    return rows
