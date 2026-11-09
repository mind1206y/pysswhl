"""加班模块 Excel 导入导出(1:1 复刻旧 Controller 的列序与口径)。

- 加班审批单:单 Sheet,与 Print.cshtml 结构一致(isTS/isComp/isWqx 三套表头)。
- 加班记录:每人一个 Sheet,按 work_date 月份分块 + 月合计。
- 导入模板:14 列 + 说明行 + 4 行示例。
- 汇总匹配导出:按 姓名+人员编号 回填 所属年月/费用项目/费用金额/备注。
"""

import io
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.overtime import (
    OvertimeApply,
    OvertimeApplyApproval,
    OvertimeApplyDetail,
    OvertimeApprovalLevel,
    OvertimePersonnel,
    OvertimeTimeEntry,
)
from app.services import overtime_common as oc

THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="F0F0F0")
TITLE_FONT = Font(bold=True, size=16)
WEEK_CN = "一二三四五六日"

TEMPLATE_HEADERS = ["姓名", "工号", "所属月份", "加班类别", "日期", "开始时间", "结束时间",
                    "倍数", "班次", "工单号", "地址", "日工资", "加班事由", "结算类型"]
TEMPLATE_WIDTHS = [2400, 3000, 2200, 3200, 2600, 2000, 2000, 1200, 1400,
                   3000, 3000, 1600, 6000, 2200]


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码会 500。"""
    return f'attachment; filename="export.xlsx"; filename*=UTF-8\'\'{quote(filename)}'


def to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _set_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(6, w / 256 if w > 100 else w)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------- 加班审批单

def apply_workbook(db: Session, apply_id: int) -> tuple[Workbook, str]:
    a = db.get(OvertimeApply, apply_id)
    if not a:
        raise ValueError("记录不存在")
    is_ts = a.work_type == oc.TS_WORK_TYPE
    is_comp = (a.settle_type or oc.SETTLE_PAY) == oc.SETTLE_COMP
    is_wqx = a.work_type == oc.WX_WORK_TYPE
    details = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.apply_id == apply_id).order_by(
        OvertimeApplyDetail.sort_order, OvertimeApplyDetail.id).all()
    dids = [d.id for d in details]
    entries = db.query(OvertimeTimeEntry).filter(
        OvertimeTimeEntry.detail_id.in_(dids or [-1])).order_by(
        OvertimeTimeEntry.sort_order, OvertimeTimeEntry.work_date,
        OvertimeTimeEntry.start_time).all()
    pmap, dmap = oc.personnel_map(db), {d.id: d for d in details}
    names, paths = oc.user_names(db), oc.dept_paths(db)

    wb = Workbook()
    ws = wb.active
    ws.title = "加班审批单"
    ws.merge_cells("A1:H1")
    ws["A1"] = "加班审批单"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center")
    total_amount = 0
    for d in details:
        for e in entries:
            if e.detail_id == d.id:
                total_amount += oc.fnum(e.overtime_amount)
    info = [
        ["编号", a.apply_no, "月份", a.apply_month, "类型", a.work_type + ("(补休)" if is_comp else ""), "", ""],
        ["部门", paths.get(a.apply_dept_id, ""), "申请人", names.get(a.apply_user_id, ""),
         "日期", oc.fmt_d(a.apply_date), "", ""],
        ["操作时间", oc.fmt_dt(a.create_time), "状态", oc.STATUS_TEXT.get(a.status or "", a.status or ""),
         "总金额" if is_ts else ("补休时长" if is_comp else "总时长"),
         f"{round(total_amount)}元" if is_ts else f"{oc.fnum(a.total_hours):.2f}h", "", ""],
        ["备注", oc.strip_source_ids(a.remark), "", "", "", "", "", ""],
    ]
    for row in info:
        ws.append(row)
    ws.append([])

    # 加班人员汇总
    if is_ts:
        dhead = ["姓名", "工号", "核算月份", "基数(元/天)", "汇总倍数", "加班金额(元)"]
    elif is_comp:
        dhead = ["姓名", "工号", "核算月份", "原始时长(h)", "折算时长(h)", "补休时长(h)"]
    else:
        dhead = ["姓名", "工号", "核算月份", "日工资", "原始时长(h)", "折算时长(h)", "加班天数", "加班金额(元)"]
    ws.append(["加班人员汇总"])
    ws.append(dhead)
    for c in range(1, len(dhead) + 1):
        ws.cell(ws.max_row, c).fill = HEAD_FILL
        ws.cell(ws.max_row, c).border = BORDER
    sum_raw = sum_total = sum_amount = 0
    for d in details:
        p = pmap.get(d.personnel_id)
        es = [e for e in entries if e.detail_id == d.id]
        raw = sum(oc.fnum(e.raw_hours) for e in es)
        total = sum(oc.fnum(e.total_hours) for e in es)
        amount = sum(oc.fnum(e.overtime_amount) for e in es)
        wage = 130 if is_ts else (oc.fnum(p.daily_wage) if p else 0)
        days = round(total / 8, 2)
        mul = sum(oc.fnum(e.multiplier) for e in es)
        if is_ts:
            row = [p.name if p else "", p.employee_no if p else "", d.accounting_month, 130, mul, round(amount)]
        elif is_comp:
            row = [p.name if p else "", p.employee_no if p else "", d.accounting_month,
                   round(raw, 2), round(total, 2), round(raw, 2)]
        else:
            row = [p.name if p else "", p.employee_no if p else "", d.accounting_month, wage,
                   round(raw, 2), round(total, 2), days, round(amount)]
        ws.append(row)
        sum_raw += raw
        sum_total += total
        sum_amount += amount
    ws.append(["合计", "", "", "", "", "", "",
               round(sum_amount) if not is_comp else round(sum_raw, 2)])
    ws.append([])

    # 加班时段明细
    if is_ts:
        thead = ["姓名", "日期", "开始", "结束", "原时长", "倍数", "基数(元)", "金额(元)", "事由"]
    elif is_comp:
        thead = ["姓名", "日期", "开始", "结束", "原时长", "倍数", "补休(h)", "事由"]
    else:
        thead = ["姓名", "日期", "开始", "结束", "原时长", "倍数", "折算(h)", "事由"]
    if is_wqx:
        thead += ["工单号", "地址"]
    ws.append(["加班时段明细"])
    ws.append(thead)
    for c in range(1, len(thead) + 1):
        ws.cell(ws.max_row, c).fill = HEAD_FILL
        ws.cell(ws.max_row, c).border = BORDER
    for e in entries:
        p = pmap.get(dmap[e.detail_id].personnel_id) if e.detail_id in dmap else None
        excl = oc.is_exclusive_entry(e.is_full_day, e.shift_type)
        wd = f"{oc.fmt_d(e.work_date)}(周{WEEK_CN[e.work_date.weekday()]})" if e.work_date else ""
        st = e.start_time.strftime("%H:%M") if e.start_time else ""
        et = e.end_time.strftime("%H:%M") if e.end_time else ""
        if excl and e.shift_type == "晚班":
            et = "次日 " + et
        if is_ts:
            row = [p.name if p else "", wd, st, et, oc.fnum(e.raw_hours),
                   oc.fnum(e.multiplier), 130, oc.fnum(e.overtime_amount), e.reason or ""]
        elif is_comp:
            row = [p.name if p else "", wd, st, et, oc.fnum(e.raw_hours),
                   oc.fnum(e.multiplier), oc.fnum(e.raw_hours), e.reason or ""]
        else:
            row = [p.name if p else "", wd, st, et, oc.fnum(e.raw_hours),
                   oc.fnum(e.multiplier), oc.fnum(e.total_hours), e.reason or ""]
        if is_wqx:
            row += [e.work_order_no or "", e.address or ""]
        ws.append(row)
    ws.append([])
    ws.append(["制单人", "复核", "领导", "HR核销"])

    approvals = db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.apply_id == apply_id).order_by(
        OvertimeApplyApproval.step_order).all()
    if approvals:
        levels = {l.id: l.level_name for l in db.query(OvertimeApprovalLevel).all()}
        ws.append([])
        ws.append(["审批记录"])
        ws.append(["审批步骤", "审批层级", "审批人", "审批状态", "审批意见", "审批时间"])
        for ap in approvals:
            ws.append([ap.step_order, levels.get(ap.approval_level_id, ""),
                       names.get(ap.approver_id, ""),
                       oc.APPROVAL_STATUS_TEXT.get(ap.status or "", ap.status or ""),
                       ap.comment or "", oc.fmt_dt(ap.approve_time)])
    _set_widths(ws, [14, 16, 12, 14, 12, 12, 14, 20, 24, 16, 20])
    return wb, f"加班审批单_{a.apply_no}_{_stamp()}.xlsx"


# ---------------------------------------------------------------- 加班记录(每人一 Sheet)

def records_workbook(db: Session, month: str, keyword: str = "", ids=None) -> tuple[Workbook, str]:
    q = (db.query(OvertimeTimeEntry, OvertimeApplyDetail)
         .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id))
    if ids:
        q = q.filter(OvertimeTimeEntry.detail_id.in_(ids))
    else:
        if month:
            q = q.filter(OvertimeTimeEntry.accounting_month == month)
        if keyword.strip():
            kw = f"%{keyword.strip()}%"
            pids = [p.id for p in db.query(OvertimePersonnel.id).filter(
                or_(OvertimePersonnel.name.like(kw), OvertimePersonnel.employee_no.like(kw))).all()]
            q = q.filter(OvertimeApplyDetail.personnel_id.in_(pids or [-1]))
    rows = q.order_by(OvertimeTimeEntry.work_date, OvertimeTimeEntry.start_time).all()
    pmap = oc.personnel_map(db)
    by_person = {}
    for e, d in rows:
        by_person.setdefault(d.personnel_id, []).append(e)
    wb = Workbook()
    wb.remove(wb.active)
    for pid, es in by_person.items():
        p = pmap.get(pid)
        ws = wb.create_sheet((p.name if p else f"人员{pid}")[:31] or "人员")
        ws.append(["日期", "加班时间", "加班时长（小时）", "星期", "加班事由"])
        last_mk, month_sum = None, 0
        for e in es:
            if not e.work_date:
                continue
            mk = e.work_date.strftime("%Y%m")
            if last_mk and mk != last_mk:
                ws.append([f"{int(last_mk[4:6])}月合计", "", round(month_sum, 2), "", ""])
                ws.append([])
                month_sum = 0
            last_mk = mk
            st = e.start_time.strftime("%H:%M") if e.start_time else ""
            et = e.end_time.strftime("%H:%M") if e.end_time else ""
            if e.shift_type == "晚班":
                et = "次日 " + et
            ws.append([f"{e.work_date.month}.{e.work_date.day}", f"{st}-{et}",
                       oc.fnum(e.raw_hours), "周" + WEEK_CN[e.work_date.weekday()],
                       e.reason or ""])
            month_sum += oc.fnum(e.raw_hours)
        if last_mk:
            ws.append([f"{int(last_mk[4:6])}月合计", "", round(month_sum, 2), "", ""])
        _set_widths(ws, [18, 17, 17, 11, 32])
    if not by_person:
        wb.create_sheet("无数据")
    return wb, f"加班记录_{month or '全部'}_{_stamp()}.xlsx"


# ---------------------------------------------------------------- 维抢修加班审批表

def qx_workbook(db: Session, month: str, remark: str = "") -> tuple[Workbook, str]:
    rows = (
        db.query(OvertimeApplyDetail.personnel_id,
                 func.coalesce(func.sum(OvertimeTimeEntry.total_hours), 0),
                 func.coalesce(func.sum(OvertimeTimeEntry.overtime_amount), 0),
                 func.max(OvertimeTimeEntry.daily_wage))
        .join(OvertimeTimeEntry, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeTimeEntry.work_type == oc.WX_WORK_TYPE,
                OvertimeTimeEntry.accounting_month == month)
        .group_by(OvertimeApplyDetail.personnel_id).all()
    )
    pmap = oc.personnel_map(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "加班工资汇总"
    ws.merge_cells("A1:I1")
    ws["A1"] = "厦门市政水务集团有限公司 加班工资报销表"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.append(["序号", "姓名", "摘要", "单位", "数量", "单价", "金额", "金额", "领款人签名"])
    total = 0
    for i, (pid, hours, amount, wage) in enumerate(rows, 1):
        p = pmap.get(pid)
        w = oc.fnum(wage) if wage else (oc.fnum(p.daily_wage) if p else 0)
        days = round(oc.fnum(hours) / 8, 1)
        money = round(days * w)
        total += money
        ws.append([i, p.name if p else "", remark or "维抢修加班", "工日", days, w, money, "", ""])
    ws.append(["合计人民币：", "", "", "", "", "", total, "", ""])
    _set_widths(ws, [8, 12, 24, 8, 10, 10, 12, 12, 16])
    return wb, f"维抢修加班审批表_{_stamp()}.xlsx"


# ---------------------------------------------------------------- 导入模板

def template_workbook(names=None, employee_nos=None) -> tuple[Workbook, str]:
    wb = Workbook()
    ws = wb.active
    ws.title = "加班明细"
    ws.merge_cells("A1:N1")
    ws["A1"] = "加班明细批量导入模板"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center")
    tips = [
        "1. 姓名、工号必须与「配置管理-人员管理」中的人员完全一致，否则该行跳过。",
        "2. 所属月份填 6 位数字，如 202606；下行留空则沿用上方最近一个非空值。",
        "3. 日期格式 yyyy-MM-dd；开始/结束时间填 4 位数字如 0830 / 1730，结束小于开始视为次日。",
        "4. 倍数留空自动按 工作日1.5 / 周末2 / 法定节假日3；法定节假日只能填 2 或 3。",
        "5. 班次填 白班 / 晚班 / 留空；填了班次或勾选全天即固定 8 小时（白班 08:30 起，晚班次日 08:30 止）。",
        "6. 工单号、地址仅「维抢修加班」必填；日工资留空取人员配置，特水开关阀门缺省 130。",
        "7. 加班事由尽量填写；结算类型填 加班费 / 补休，法定节假日加班费不允许补休。",
        "8. 补休按 1:1 计入余额，不计加班费；补休记录近 12 个月有效。",
        "9. 导入只生成草稿，请在「我的加班」核对后提交。",
        "10. 示例行（张三/李四/王五/赵六）会自动跳过，可删除。",
        "11. 同一人同一天存在全天/班次记录时不可再录其他类别；普通时段不可重叠。",
        "12. 加班类别必须为系统 13 类之一，见下拉说明。",
    ]
    for t in tips:
        ws.append([t])
    ws.append(TEMPLATE_HEADERS)
    head_row = ws.max_row
    for c in range(1, 15):
        cell = ws.cell(head_row, c)
        cell.fill = HEAD_FILL
        cell.border = BORDER
        cell.font = Font(bold=True)
    examples = [
        ["张三", "A62000000001", "202606", "日常加班费", "2026-06-10", "0830", "1730", "1.5", "", "", "", "", "设备巡检", "加班费"],
        ["李四", "A62000000002", "202606", "法定节假日加班费", "2026-06-19", "", "", "3", "白班", "", "", "", "节假日值守", "加班费"],
        ["王五", "A62000000003", "202606", "维抢修加班", "2026-06-12", "1800", "2100", "2", "", "GD20260612001", "思明区某路", 150, "管道抢修", "加班费"],
        ["赵六", "A62000000004", "202606", "日常加班费", "2026-06-15", "0830", "1200", "", "", "", "", "", "社区服务", "补休"],
    ]
    for r in examples:
        ws.append(r)
    if names:
        ns = [x for x in str(names).split("|") if x]
        nos = [x for x in str(employee_nos or "").split("|")]
        for i, n in enumerate(ns):
            ws.append([n, nos[i] if i < len(nos) else "", ""])
    for col in (5,):
        for row in range(head_row + 1, ws.max_row + 1):
            ws.cell(row, col).number_format = "yyyy-mm-dd"
    for col in (6, 7):
        for row in range(head_row + 1, ws.max_row + 1):
            ws.cell(row, col).number_format = "@"
    _set_widths(ws, TEMPLATE_WIDTHS)
    return wb, "加班明细批量导入模板.xlsx"


# ---------------------------------------------------------------- 解析导入明细

def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _four_time(v, day: date, base: str):
    s = "".join(ch for ch in _cell(v) if ch.isdigit())
    if len(s) < 4:
        return None
    return datetime.combine(day, time(int(s[:2]) % 24, int(s[2:4]) % 60))


def read_import_rows(file_bytes: bytes) -> tuple[list[dict], list[dict]]:
    """返回 (有效行, 错误行)。定位表头后沿用上方月份/类别/结算类型,跳过示例行。"""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
    head = next((i for i, r in enumerate(rows)
                 if len(r) > 1 and r[0] == "姓名" and r[1] == "工号"), None)
    if head is None:
        raise ValueError('未找到表头行（需包含"姓名"和"工号"两列）')
    out, errors = [], []
    carry_month = carry_type = carry_settle = ""
    for idx, r in enumerate(rows[head + 1:], start=head + 2):
        r = (r + [""] * 14)[:14]
        name, emp_no, month, work_type, day_s, start_s, end_s, mul_s, shift, wo, addr, wage_s, reason, settle = r
        if not name and not emp_no:
            continue
        if name in ("张三", "李四", "王五", "赵六") and emp_no.startswith("A62000000") and len(emp_no) == 11:
            errors.append({"Row": idx, "Name": name, "Msg": "示例行已跳过"})
            continue
        carry_month = month or carry_month
        carry_type = work_type or carry_type
        carry_settle = settle or carry_settle
        out.append({
            "row": idx, "name": name, "employee_no": emp_no,
            "apply_month": carry_month, "work_type": carry_type,
            "work_date": day_s, "start": start_s, "end": end_s,
            "multiplier": mul_s, "shift_type": shift, "work_order_no": wo,
            "address": addr, "daily_wage": wage_s, "reason": reason,
            "settle_type": carry_settle or oc.SETTLE_PAY,
        })
    return out, errors


def validate_import_row(db: Session, r: dict):
    """旧 TryImportRow 等价校验,返回 (规范化后的 dict, 错误文本)。"""
    p = None
    if r["name"] and r["employee_no"]:
        p = (db.query(OvertimePersonnel)
             .filter(OvertimePersonnel.name == r["name"],
                     OvertimePersonnel.employee_no == r["employee_no"],
                     OvertimePersonnel.is_active.is_(True)).first())
    if not p:
        return None, f"人员不存在或未启用：{r['name']} / {r['employee_no']}"
    wt = r["work_type"]
    if wt not in oc.WORK_TYPES:
        return None, "加班类别不是合法值：" + wt
    month = (r["apply_month"] or "").replace("-", "")
    if len(month) != 6 or not month.isdigit():
        return None, "所属月份格式错误：" + r["apply_month"]
    try:
        day = datetime.strptime(r["work_date"][:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, "日期格式错误：" + r["work_date"]
    settle = r["settle_type"] or oc.SETTLE_PAY
    is_holiday = wt == oc.HOLIDAY_WORK_TYPE
    is_comp = settle == oc.SETTLE_COMP
    if is_comp and is_holiday:
        return None, "法定节假日加班费不允许选择补休"
    mul_s = r["multiplier"]
    if mul_s:
        try:
            mul = oc.D(mul_s)
        except Exception:
            return None, "倍数格式错误：" + mul_s
    else:
        weekend = day.weekday() >= 5
        mul = oc.D(3 if is_holiday else (2 if weekend else 1.5))
    if is_holiday and mul not in (oc.D(2), oc.D(3)):
        return None, "法定节假日倍数只能填 2 或 3"
    if is_comp:
        mul = oc.D(1)
    wage = oc.D(r["daily_wage"]) if r["daily_wage"] else oc.D(p.daily_wage)
    if wt == oc.TS_WORK_TYPE and wage == 0:
        wage = oc.TS_DEFAULT_WAGE
    shift = oc.normalize_shift(r["shift_type"])
    excl = bool(shift)
    if excl:
        if shift == "晚班":
            st = datetime.combine(day, time(17, 30))
            en = datetime.combine(day + timedelta(days=1), time(8, 30))
        else:
            st = datetime.combine(day, time(8, 30))
            en = datetime.combine(day, time(18, 0))
        raw, total = oc.D(8), oc.D(8) * mul
        amount = oc.D(0) if is_comp else wage * mul
    else:
        st = _four_time(r["start"], day, "start")
        en = _four_time(r["end"], day, "end")
        if not st or not en:
            return None, "开始/结束时间需为 4 位数字"
        if en <= st:
            en += timedelta(days=1)
        raw = oc.dec2((en - st).total_seconds() / 3600)
        total = raw * mul
        amount = (oc.D(0) if is_comp else
                  (wage * mul if wt == oc.TS_WORK_TYPE else
                   (wage / oc.D(8) * raw * mul).quantize(oc.D("1"), rounding="ROUND_HALF_EVEN")))
    return {
        "personnel_id": p.id, "apply_month": month, "work_type": wt,
        "work_date": day, "start_time": st, "end_time": en,
        "multiplier": mul, "raw_hours": raw, "total_hours": total,
        "overtime_amount": oc.dec2(amount), "daily_wage": wage,
        "shift_type": shift, "is_full_day": False, "settle_type": settle,
        "reason": r["reason"], "work_order_no": r["work_order_no"],
        "address": r["address"],
    }, None


# ---------------------------------------------------------------- 人员导入

def read_personnel_rows(file_bytes: bytes):
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
    head = next((i for i, r in enumerate(rows)
                 if len(r) > 2 and r[0] == "部门" and r[1] == "姓名" and r[2] == "人员编号"), None)
    if head is None:
        raise ValueError('未找到表头行（需包含"部门""姓名""人员编号"三列）')
    out = []
    for r in rows[head + 1:]:
        r = (r + [""] * 3)[:3]
        if not r[1]:
            continue
        out.append({"dept": r[0], "name": r[1], "employee_no": r[2]})
    return out


# ---------------------------------------------------------------- 汇总匹配导出

def match_summary_workbook(file_bytes: bytes, db: Session, month: str,
                           work_type: str) -> tuple[Workbook, int, int]:
    """读取用户上传的表格,按 姓名+人员编号 匹配已核销记录,回填 col3~col6。"""
    verified = (
        db.query(OvertimeApply.status, OvertimeTimeEntry, OvertimeApplyDetail, OvertimePersonnel)
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .join(OvertimePersonnel, OvertimeApplyDetail.personnel_id == OvertimePersonnel.id)
        .outerjoin(OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id)
        .filter(OvertimeTimeEntry.accounting_month == month,
                OvertimeTimeEntry.work_type == work_type,
                OvertimeApply.status == "verified").all()
    )
    by_key = {}
    for _status, e, d, p in verified:
        key = ((p.name or "").lower(), (p.employee_no or "").lower())
        by_key.setdefault(key, []).append(e)
    wb = load_workbook(io.BytesIO(file_bytes))
    ws = wb.active
    matched = unmatched = 0
    for row in range(2, ws.max_row + 1):
        name, emp_no = _cell(ws.cell(row, 1).value), _cell(ws.cell(row, 2).value)
        if not name and not emp_no:
            continue
        es = by_key.get((name.lower(), emp_no.lower()))
        if not es:
            unmatched += 1
            continue
        matched += 1
        amount = round(sum(oc.fnum(e.overtime_amount) for e in es))
        reasons = []
        for e in es:
            if e.start_time and e.reason:
                s = f"{e.start_time.strftime('%Y-%m-%d %H:%M')}-{e.end_time.strftime('%H:%M') if e.end_time else ''} {e.reason}"
                if s not in reasons:
                    reasons.append(s)
        if work_type == oc.WX_WORK_TYPE:
            days = round(sum(oc.fnum(e.raw_hours) for e in es) / 8, 1)
            first = min((e.work_date for e in es if e.work_date), default=None)
            last = max((e.work_date for e in es if e.work_date), default=None)
            remark = (f"{first.strftime('%m.%d')}-{last.strftime('%m.%d')}（{days}天）管网维抢修加班，详见附件。"
                      if first and last else "")
        else:
            remark = "；".join(reasons[:10])
        ws.cell(row, 4, month)
        ws.cell(row, 5, work_type)
        ws.cell(row, 6, amount)
        ws.cell(row, 7, remark)
    return wb, matched, unmatched
