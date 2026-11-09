"""维抢修加班导出(照旧 JiabanController 的 4 个 NPOI 导出 1:1 重建为 openpyxl)。

- build_by_name       ExportExcelNpoi      按姓名分 Sheet,每人一张《XX加班审批表》
- build_by_address    ExportByAddress      按工单号分 Sheet,《厦门营业所加班审批表》
- build_summary       ExportSummaryExcelNpoi  按人员汇总的《加班工资报销表》(含人民币大写)
- build_for_overtime  ExportForOvertimeApply  14 列格式,匹配加班申请"批量导入"模板

口径照旧:
- 工日 = 小时 / 8,四舍五入保留 1 位小数(AwayFromZero)
- 汇总金额 = round(工日 × 单价) 取整;中文大写金额按旧 ToChineseMoney 算法
- 导出给加班申请:只取有工号/姓名/起止时间的记录;所属月份按"上月21日~当月20日"
  归入当月(21日及以后算下一个月);加班类别固定"维抢修加班"、结算类型固定"加班费"
"""

import math
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

THIN = Border(*[Side(style="thin")] * 4)
GREY_FILL = PatternFill("solid", fgColor="D9D9D9")
WEEKDAY = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}
CHINESE_DIGITS = "零壹贰叁肆伍陆柒捌玖"
CHINESE_UNITS = ["", "拾", "佰", "仟", "万", "拾", "佰", "仟", "亿", "拾", "佰", "仟"]

TITLE_FONT = Font(bold=True, size=16)
HEADER_FONT = Font(bold=True)
CENTER = Alignment(horizontal="center", vertical="center")
CENTER_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center")
LEFT_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")


def _fmt(v, nd=2):
    """照旧 0.# / 0.## 数值格式(去尾零)。"""
    if v is None:
        v = 0
    return f"{float(v):.{nd}f}".rstrip("0").rstrip(".") or "0"


def chinese_money(money) -> str:
    """人民币大写(照旧 ToChineseMoney,含万/亿零位处理)。"""
    money = float(money or 0)
    if money == 0:
        return "零元整"
    s = f"{money:.2f}"
    integer_part, decimal_part = s.split(".")

    integer_result = ""
    length = len(integer_part)
    zero_flag = False
    for i, ch in enumerate(integer_part):
        digit = int(ch)
        pos = length - i - 1
        if digit == 0:
            zero_flag = True
            if pos in (4, 8):
                if pos == 8 and length > 8 and "0" in integer_part[: length - 8]:
                    integer_result += "零"
                integer_result += "万" if pos == 4 else "亿"
                zero_flag = False
        else:
            if zero_flag:
                integer_result += "零"
                zero_flag = False
            integer_result += CHINESE_DIGITS[digit] + CHINESE_UNITS[pos]
    integer_result = integer_result.rstrip("零") or "零"

    jiao, fen = int(decimal_part[0]), int(decimal_part[1])
    decimal_result = (CHINESE_DIGITS[jiao] + "角" if jiao else "") + \
                     (CHINESE_DIGITS[fen] + "分" if fen else "")
    if not decimal_result:
        decimal_result = "整"
    return integer_result + "元" + decimal_result


def _cell(ws, row, col, value, style=None):
    c = ws.cell(row=row, column=col, value=value)
    if style:
        c.alignment = style
    return c


def _apply_border(ws, row, col_start, col_end, font=None, wrap=False):
    for col in range(col_start, col_end + 1):
        c = ws.cell(row=row, column=col)
        c.border = THIN
        if font:
            c.font = font
        c.alignment = (CENTER_WRAP if wrap else CENTER)


# ==================== 1. 按姓名导出(每人一个 Sheet) ====================
def build_by_name(records: list[dict], remark: str, end_date) -> BytesIO:
    """records 需含 name/bm/gongdanNo/riqi/dizhi/neirong/kjshijian/shijian/beishu/zongshu。"""
    wb = Workbook()
    wb.remove(wb.active)
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r.get("name") or "未知", []).append(r)

    for name, items in groups.items():
        department = items[0].get("bm") or ""
        ws = wb.create_sheet(title=name[:31])
        for i, width in enumerate((11, 12, 15, 15, 11, 9, 12), start=1):
            ws.column_dimensions[get_column_letter(i)].width = width

        row = 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        ws.row_dimensions[row].height = 30
        _cell(ws, row, 1, f"{department}加班审批表", CENTER)
        _apply_border(ws, row, 1, 7)
        ws.cell(row=row, column=1).font = TITLE_FONT
        row += 1

        if end_date:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            _cell(ws, row, 1, f"{end_date.year}年{end_date.month}月{end_date.day}日", RIGHT)
            row += 1

        for label, value in (("部门", department), ("姓名", name)):
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
            ws.row_dimensions[row].height = 20
            _cell(ws, row, 1, label, CENTER)
            _cell(ws, row, 3, value, CENTER)
            _apply_border(ws, row, 1, 7, font=HEADER_FONT)
            row += 1

        headers = ["日期", "工单号", "地址", "工作内容", "加班时间", "原始时间", "加班时长"]
        ws.row_dimensions[row].height = 18
        for i, h in enumerate(headers, start=1):
            _cell(ws, row, i, h)
        _apply_border(ws, row, 1, 7, font=HEADER_FONT, wrap=True)
        row += 1

        total_hours = 0.0
        total_shijian = 0.0
        for item in items:
            riqi = item.get("riqi")
            if isinstance(riqi, str):
                riqi = datetime.strptime(riqi[:10], "%Y-%m-%d")
            _cell(ws, row, 1, f"{riqi:%m.%d}({WEEKDAY[riqi.weekday()]})")
            _cell(ws, row, 2, item.get("gongdanNo") or "")
            _cell(ws, row, 3, item.get("dizhi") or "", LEFT_WRAP)
            _cell(ws, row, 4, item.get("neirong") or "", LEFT_WRAP)
            _cell(ws, row, 5, item.get("kjshijian") or "")
            _cell(ws, row, 6, _fmt(item.get("shijian"), 1))
            _cell(ws, row, 7, f"{_fmt(item.get('shijian'), 1)}*"
                              f"{_fmt(item.get('beishu'), 1)}={_fmt(item.get('zongshu'))}", LEFT)
            _apply_border(ws, row, 1, 7)
            ws.cell(row=row, column=3).alignment = LEFT_WRAP
            ws.cell(row=row, column=4).alignment = LEFT_WRAP
            total_hours += float(item.get("zongshu") or 0)
            total_shijian += float(item.get("shijian") or 0)
            row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 18
        _cell(ws, row, 1, "合计加班时间")
        _cell(ws, row, 6, f"{_fmt(total_shijian)} 小时")
        _cell(ws, row, 7, f"{_fmt(total_hours)} 小时")
        _apply_border(ws, row, 1, 7, font=HEADER_FONT)
        row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 18
        _cell(ws, row, 1, "合计工日")
        _cell(ws, row, 6, f"{math.floor(total_shijian / 8 * 10 + 0.5) / 10:.1f} 天")
        _cell(ws, row, 7, f"{math.floor(total_hours / 8 * 10 + 0.5) / 10:.1f} 天")
        _apply_border(ws, row, 1, 7, font=HEADER_FONT)
        row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        ws.row_dimensions[row].height = 18
        _cell(ws, row, 1, "备注", CENTER)
        _cell(ws, row, 3, remark or "", LEFT_WRAP)
        _apply_border(ws, row, 1, 7)
        ws.cell(row=row, column=3).alignment = LEFT_WRAP
        row += 1

        ws.row_dimensions[row].height = 40
        _cell(ws, row, 1, "审批:")
        _cell(ws, row, 3, "复核:")
        _cell(ws, row, 5, "制表:")
        row += 1

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


# ==================== 2. 按地址导出(每个工单号一个 Sheet) ====================
def build_by_address(records: list[dict], remark: str) -> BytesIO:
    wb = Workbook()
    wb.remove(wb.active)
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r.get("gongdanNo") or "", []).append(r)

    used_names = set()
    for gongdan_no, items in groups.items():
        base = (gongdan_no or "无工单号")[:28]
        sheet_name = base
        suffix = 1
        while sheet_name in used_names:
            sheet_name = f"{base}_{suffix}"
            suffix += 1
        used_names.add(sheet_name)
        ws = wb.create_sheet(title=sheet_name)

        first = items[0]
        riqi = first.get("riqi")
        if isinstance(riqi, str):
            riqi = datetime.strptime(riqi[:10], "%Y-%m-%d")

        row = 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        ws.row_dimensions[row].height = 30
        _cell(ws, row, 1, "厦门营业所加班审批表", CENTER)
        ws.cell(row=row, column=1).font = TITLE_FONT
        row += 1

        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=8)
        ws.row_dimensions[row].height = 20
        _cell(ws, row, 1, "工单号", CENTER)
        _cell(ws, row, 2, gongdan_no)
        _cell(ws, row, 4, "日期", CENTER)
        _cell(ws, row, 5, f"{riqi:%Y-%m-%d}")
        _apply_border(ws, row, 1, 8, font=HEADER_FONT)
        row += 1

        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
        ws.row_dimensions[row].height = 20
        _cell(ws, row, 1, "地址", CENTER)
        _cell(ws, row, 2, first.get("dizhi") or "")
        _apply_border(ws, row, 1, 8, font=HEADER_FONT)
        row += 1

        headers = ["序号", "姓名", "部门", "起止时间", "加班时长", "倍数", "总时长", "工作内容"]
        ws.row_dimensions[row].height = 18
        for i, h in enumerate(headers, start=1):
            _cell(ws, row, i, h)
        _apply_border(ws, row, 1, 8, font=HEADER_FONT)
        row += 1

        total_shijian = 0.0
        total_hours = 0.0
        for idx, item in enumerate(items, start=1):
            ws.row_dimensions[row].height = 18
            _cell(ws, row, 1, idx)
            _cell(ws, row, 2, item.get("name") or "")
            _cell(ws, row, 3, item.get("bm") or "")
            _cell(ws, row, 4, item.get("kjshijian") or "")
            _cell(ws, row, 5, _fmt(item.get("shijian"), 1))
            _cell(ws, row, 6, _fmt(item.get("beishu"), 1))
            _cell(ws, row, 7, _fmt(item.get("zongshu")))
            _cell(ws, row, 8, item.get("neirong") or "", LEFT)
            _apply_border(ws, row, 1, 8)
            ws.cell(row=row, column=8).alignment = LEFT
            total_shijian += float(item.get("shijian") or 0)
            total_hours += float(item.get("zongshu") or 0)
            row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.row_dimensions[row].height = 18
        _cell(ws, row, 1, "合计")
        _cell(ws, row, 5, _fmt(total_shijian))
        _cell(ws, row, 7, _fmt(total_hours))
        _apply_border(ws, row, 1, 8, font=HEADER_FONT)
        row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.row_dimensions[row].height = 18
        _cell(ws, row, 1, "合计工日")
        _cell(ws, row, 5, f"{math.floor(total_shijian / 8 * 10 + 0.5) / 10:.1f} 天")
        _cell(ws, row, 7, f"{math.floor(total_hours / 8 * 10 + 0.5) / 10:.1f} 天")
        _apply_border(ws, row, 1, 8, font=HEADER_FONT)
        row += 1

        if (remark or "").strip():
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            ws.row_dimensions[row].height = 18
            _cell(ws, row, 1, "备注", CENTER)
            _cell(ws, row, 2, remark)
            _apply_border(ws, row, 1, 8, font=HEADER_FONT)
            row += 1

        ws.row_dimensions[row].height = 40
        _cell(ws, row, 1, "审批:")
        _cell(ws, row, 4, "复核:")
        _cell(ws, row, 7, "制表:")

        for i, width in enumerate((6, 10, 16, 14, 10, 8, 10, 24), start=1):
            ws.column_dimensions[get_column_letter(i)].width = width

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


# ==================== 3. 加班工资汇总表 ====================
def build_summary(groups: list[dict], show_dept: str, tab_user: str) -> BytesIO:
    """groups: [{name, danjia, totalHours, bmlb}],已按 bmlb/name 排序。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "加班工资汇总"

    row = 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    _cell(ws, row, 1, "厦门市政水务集团有限公司 加班工资报销表", CENTER)
    ws.cell(row=row, column=1).font = TITLE_FONT
    row += 1

    now = datetime.now()
    dept_info = f"部门：{show_dept}  制表时间：{now.year}年{now.month}月{now.day}日"
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    ws.row_dimensions[row].height = 18
    _cell(ws, row, 1, dept_info, CENTER)
    row += 1

    headers = ["序号", "姓名", "摘要", "单位", "数量", "单价", "金额", "金额", "领款人签名"]
    for i, h in enumerate(headers, start=1):
        _cell(ws, row, i, h)
    _apply_border(ws, row, 1, 9, font=HEADER_FONT)
    row += 1

    serial = 1
    total_amount = 0
    for item in groups:
        _cell(ws, row, 1, serial)
        serial += 1
        _cell(ws, row, 2, item.get("name") or "未知")
        _cell(ws, row, 3, "")
        _cell(ws, row, 4, "工日")
        gongri = math.floor((float(item.get("totalHours") or 0)) / 8 * 10 + 0.5) / 10
        _cell(ws, row, 5, gongri)
        danjia = float(item.get("danjia") or 0)
        _cell(ws, row, 6, danjia)
        amount = math.floor(gongri * danjia + 0.5)
        total_amount += amount
        _cell(ws, row, 7, amount)
        _cell(ws, row, 8, "")
        _cell(ws, row, 9, "")
        _apply_border(ws, row, 1, 9)
        for col, align in ((5, CENTER), (6, RIGHT), (7, RIGHT)):
            ws.cell(row=row, column=col).alignment = align
            ws.cell(row=row, column=col).number_format = \
                "0.0" if col == 5 else "0.00"
        row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=6)
    ws.row_dimensions[row].height = 20
    _cell(ws, row, 1, "合计人民币：", CENTER)
    _cell(ws, row, 3, chinese_money(total_amount), CENTER)
    _cell(ws, row, 7, f"{total_amount:.2f}")
    _apply_border(ws, row, 1, 9, font=HEADER_FONT)
    ws.cell(row=row, column=7).alignment = RIGHT
    row += 1

    _cell(ws, row, 1, "营业所：")
    _cell(ws, row, 3, "复核：")
    _cell(ws, row, 8, "制表：")
    _cell(ws, row, 9, tab_user)
    for i in range(1, 10):
        ws.column_dimensions[get_column_letter(i)].width = 12
    ws.column_dimensions["I"].width = 14

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


# ==================== 4. 导出给加班申请模块(14 列导入模板) ====================
OT_HEADERS = ["姓名", "工号", "所属月份", "加班类别", "日期", "开始时间", "结束时间",
              "倍数", "班次", "工单号", "地址", "日工资", "加班事由", "结算类型"]
OT_WIDTHS = (12, 15, 11, 16, 13, 10, 10, 6, 7, 15, 15, 8, 30, 11)
OT_NOTE = ("【说明】此文件可直接上传到\"加班申请管理\"→\"我的加班\"→\"批量导入\"按钮。"
           "加班类别已固定为维抢修加班，所属月份按日期自动计算，结算类型固定为加班费"
           "（如需补休请手动改为补休）。")


def _apply_month(riqi) -> str:
    if isinstance(riqi, str):
        riqi = datetime.strptime(riqi[:10], "%Y-%m-%d")
    if riqi.day >= 21:
        month = riqi.month + 1
        year = riqi.year
        if month > 12:
            month = 1
            year += 1
        return f"{year}{month:02d}"
    return f"{riqi.year}{riqi.month:02d}"


def build_for_overtime(records: list[dict]) -> BytesIO:
    """records 已过滤(有工号/姓名/起止时间),字段与按姓名导出一致 + gonghao/danjia。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "加班明细"

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=14)
    note = ws.cell(row=1, column=1, value=OT_NOTE)
    note.font = Font(size=10, color="0000FF")
    note.alignment = Alignment(vertical="top", wrap_text=True)

    for i, h in enumerate(OT_HEADERS, start=1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = GREY_FILL
        c.border = THIN
        c.alignment = CENTER
    ws.row_dimensions[2].height = 20

    row = 3
    for r in records:
        riqi = r.get("riqi")
        if isinstance(riqi, str):
            riqi = datetime.strptime(riqi[:10], "%Y-%m-%d")
        kstime, jstime = r.get("kstime"), r.get("jstime")
        if isinstance(kstime, str):
            kstime = datetime.fromisoformat(kstime)
        if isinstance(jstime, str):
            jstime = datetime.fromisoformat(jstime)
        values = [
            r.get("name") or "",
            str(r.get("gonghao") or ""),
            _apply_month(riqi),
            "维抢修加班",
            f"{riqi:%Y-%m-%d}",
            f"{kstime:%H%M}",
            f"{jstime:%H%M}",
            float(r.get("beishu") or 0),
            "",
            r.get("gongdanNo") or "",
            r.get("dizhi") or "",
            float(r.get("danjia") or 0),
            r.get("neirong") or "",
            "加班费",
        ]
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=i, value=v)
            c.border = THIN
            c.alignment = Alignment(vertical="center")
            if i in (2, 3, 6, 7, 10, 11):  # 文本格式,防纯数字被转数值
                c.number_format = "@"
        row += 1

    for i, width in enumerate(OT_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out
