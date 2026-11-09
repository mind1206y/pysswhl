"""加班申请模块公共业务规则(1:1 复刻旧系统 OvertimeApplyController + OvertimeApprovalEngine)。

本文件集中所有"不能凭感觉重写"的规则:13 类加班类别、独占判定、时长/金额公式、
GR-/JB- 编号、核算月、三层查重、部门镜像树、月度 36h 预警、补休余额、权限折算。
"""

import re
import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func

from app.api.deps import dept_scope_ids
from app.models.overtime import (
    OvertimeApply,
    OvertimeApplyApproval,
    OvertimeApplyDetail,
    OvertimeApprovalLevel,
    OvertimeApprover,
    OvertimeCompLeave,
    OvertimeDept,
    OvertimeMonthConfig,
    OvertimePersonnel,
    OvertimeTimeEntry,
)
from app.models.user import User

# ---------------------------------------------------------------- 常量

WORK_TYPES = [
    "法定节假日加班费", "日常加班费", "服务进社区", "一日运营加班", "日清日结加班",
    "管网周末加班", "超时加班", "水质冲排加班", "供水保障加班", "泵站加班",
    "特水开关阀门", "维抢修加班", "应急响应值班",
]
EXCLUSIVE_WORK_TYPES = ["法定节假日加班费", "应急响应值班", "管网周末加班"]
COMP_LEAVE_WORK_TYPES = [w for w in WORK_TYPES if w != "法定节假日加班费"]
MULTI_DATE_WORK_TYPES = ["日常加班费", "日清日结加班"]  # 批量新建支持多日期网格的类别

SETTLE_PAY = "加班费"
SETTLE_COMP = "补休"
FIXED_FULL_DAY_HOURS = Decimal("8")
COMP_LEAVE_VALID_MONTHS = 12
TS_WORK_TYPE = "特水开关阀门"
TS_DEFAULT_WAGE = Decimal("130")
WX_WORK_TYPE = "维抢修加班"
HOLIDAY_WORK_TYPE = "法定节假日加班费"
GW_WORK_TYPE = "管网周末加班"

STATUS_TEXT = {
    "draft": "草稿", "submitted": "已提交", "grouped": "已汇总", "pending": "审批中",
    "approved": "已通过", "rejected": "已驳回", "skipped": "已跳过",
    "printed": "已打印", "verified": "已核销",
}
APPROVAL_STATUS_TEXT = {
    "pending": "待审批", "approved": "已通过", "rejected": "已驳回", "skipped": "已跳过",
}

PERM_APPLY = "overtime:apply"
PERM_VERIFY = "overtime:verify"
PERM_HR = "overtime:hr"
PERM_MANAGE = "overtime:manage"
PERM_VIEW = "overtime:view"

_SRC_RE = re.compile(r"__SRC__\[[^\]]*\]")


def D(value) -> Decimal:
    """安全转 Decimal。"""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fnum(value) -> float:
    return float(D(value))


def dec2(value) -> Decimal:
    """两位小数(银行家舍入,对齐 C# Math.Round(decimal))。"""
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def round0_half_up(value) -> Decimal:
    return D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def current_month() -> str:
    return datetime.now().strftime("%Y%m")


def month_options():
    """当前月前 6 个月 ~ 后 17 个月,共 24 项;索引 6 为当前月(与旧系统 _months 一致)。"""
    now = datetime.now()
    out = []
    for i in range(-6, 18):
        y = now.year + (now.month - 1 + i) // 12
        m = (now.month - 1 + i) % 12 + 1
        out.append(f"{y:04d}{m:02d}")
    return out


# ---------------------------------------------------------------- 权限(旧 otherqx 标签 -> 权限码)

def user_perms(user: User) -> set:
    return {p.code for role in user.roles for p in role.permissions}


def has_any_perm(user: User, *codes) -> bool:
    if user.is_superuser:
        return True
    owned = user_perms(user)
    return any(c in owned for c in codes)


def ensure_perm(user: User, *codes):
    """接口内手工鉴权:超管直通,否则要求持有任一权限码。"""
    if not has_any_perm(user, *codes):
        raise HTTPException(status_code=403, detail="没有操作权限")


def is_admin(user: User) -> bool:
    """旧 IsAdmin() = otherqx 含 admin;新系统折算为超管或 overtime:manage。"""
    return has_any_perm(user, PERM_MANAGE)


def is_verifier(user: User) -> bool:
    """旧 IsVerifier() = admin / 加班管理 / HR -> 新系统三个管理权限码任一。"""
    return has_any_perm(user, PERM_APPLY, PERM_VERIFY, PERM_HR, PERM_MANAGE)


def is_hr(user: User) -> bool:
    """旧 IsHr() = admin / HR。"""
    return has_any_perm(user, PERM_VERIFY, PERM_HR, PERM_MANAGE)


def approval_enabled(db) -> bool:
    row = (
        db.query(OvertimeMonthConfig)
        .filter(OvertimeMonthConfig.config_type == "approval_switch")
        .first()
    )
    return bool(row and row.is_active)


def is_approver(db, user: User) -> bool:
    if not approval_enabled(db):
        return False
    return bool(
        db.query(OvertimeApprover.id)
        .filter(OvertimeApprover.bb_user_id == user.id, OvertimeApprover.is_active.is_(True))
        .first()
    )


# ---------------------------------------------------------------- 计算

def is_exclusive_entry(is_full_day: bool, shift_type: str | None) -> bool:
    """条目级独占判定:与 work_type 无关,= 全天 或 指定了班次。"""
    return bool(is_full_day) or bool(shift_type)


def has_time_overlap(a_start, a_end, b_start, b_end) -> bool:
    """旧 OvertimeWorkTypeHelper.HasTimeOverlap 三条件展开(相邻不重叠)。"""
    if not all((a_start, a_end, b_start, b_end)):
        return False
    return (
        (a_start >= b_start and a_start < b_end)
        or (a_end > b_start and a_end <= b_end)
        or (a_start <= b_start and a_end >= b_end)
    )


def compute_overtime_amount(total_hours, daily_wage) -> Decimal:
    """列表/汇总按人金额口径: round(round(total/8,2)*wage, 0, AwayFromZero)。"""
    hours, wage = D(total_hours), D(daily_wage)
    if wage <= 0 or hours <= 0:
        return Decimal("0")
    days = (hours / Decimal("8")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return round0_half_up(days * wage)


def normalize_shift(value) -> str | None:
    v = (value or "").strip()
    return v or None


def compute_entry_fields(
    *, work_type: str, work_date, start_time, end_time, multiplier,
    daily_wage, settle_type: str, is_full_day: bool, shift_type,
    full_day_end: str = "18:00",
) -> dict:
    """按旧系统三处同源公式计算一条时段(后端重算路径)。

    返回 raw_hours / total_hours / overtime_amount / start_time / end_time / multiplier。
    注意: SavePersonalRecord 与 SaveApply 走前端 DTO 直落,不调用本函数(保持旧行为)。
    """
    settle = settle_type or SETTLE_PAY
    mul = D(multiplier) if multiplier not in (None, "") else (
        Decimal("3") if (is_full_day or shift_type) else Decimal("1.5")
    )
    wage = D(daily_wage)
    is_comp = settle == SETTLE_COMP
    if is_comp:
        mul = Decimal("1")
    is_ts = work_type == TS_WORK_TYPE
    if is_ts and wage == 0:
        wage = TS_DEFAULT_WAGE
    excl = is_exclusive_entry(is_full_day, shift_type)
    if excl:
        raw = FIXED_FULL_DAY_HOURS
        total = raw * mul
        amount = Decimal("0") if is_comp else wage * mul
        if shift_type == "晚班":
            st = combine(work_date, start_time.time() if isinstance(start_time, datetime) else time(17, 30))
            et = datetime.combine(as_date(work_date) + timedelta(days=1), time(8, 30))
        else:
            st = datetime.combine(as_date(work_date), time(8, 30))
            hh, mm = (full_day_end or "18:00").split(":")[:2]
            et = datetime.combine(as_date(work_date), time(int(hh), int(mm)))
            if et <= st:
                et = datetime.combine(as_date(work_date), time(18, 0))
    else:
        st, et = start_time, end_time
        if et <= st:
            et = et + timedelta(days=1)
        raw = Decimal(str((et - st).total_seconds() / 3600)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        if raw <= 0:
            raise HTTPException(400, "结束时间必须大于开始时间")
        total = raw * mul
        if is_comp:
            amount = Decimal("0")
        elif is_ts:
            amount = wage * mul
        else:
            amount = (wage / Decimal("8") * raw * mul).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
    return {
        "raw_hours": dec2(raw),
        "multiplier": mul,
        "total_hours": dec2(total),
        "overtime_amount": dec2(amount),
        "start_time": st,
        "end_time": et,
        "daily_wage": wage,
    }


def as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def combine(day, tm: time) -> datetime:
    return datetime.combine(as_date(day), tm)


def parse_dt(value, default=None):
    """前端可能传 'yyyy-MM-dd HH:mm' / ISO / 空,统一成 datetime。"""
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value
    s = str(value).replace("T", " ").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2], fmt)
        except ValueError:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    raise HTTPException(400, f"时间格式错误: {value}")


def require_time_range(start, end):
    """校验起止时间并返回 (st, en, work_date)。

    parse_dt 对空值返回 None,校验接口若直接 st.date() 会抛 AttributeError 变成 500;
    录入弹窗尚未填完时间就会调 /check-overlap,这里统一挡成 400。
    """
    st, en = parse_dt(start), parse_dt(end)
    if st is None or en is None:
        raise HTTPException(400, "缺少开始时间或结束时间")
    return st, en, st.date()


def fmt_dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else ""


def fmt_d(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%d") if isinstance(value, date) else ""


# ---------------------------------------------------------------- 核算月 / 编号

def accounting_month(day: date, db, config_type="detail") -> str:
    """旧 Engine.GetAccountingMonth: day >= start_day -> 次月。控制器写入路径从不调用,
    仅 SaveApply 用 month_date_range 校验申请日期;此处保留工具函数供导入/校验使用。"""
    cfg = (
        db.query(OvertimeMonthConfig)
        .filter(OvertimeMonthConfig.config_type == config_type,
                OvertimeMonthConfig.is_active.is_(True))
        .first()
    )
    start_day = cfg.start_day if cfg and cfg.start_day else 26
    if day.day >= start_day:
        y = day.year + (day.month // 12)
        m = day.month % 12 + 1
        return f"{y:04d}{m:02d}"
    return day.strftime("%Y%m")


def month_date_range(month: str, db, config_type="apply"):
    """返回 [上月 start_day 00:00, 本月 end_day 23:59:59],默认 26/25 切割。"""
    cfg = (
        db.query(OvertimeMonthConfig)
        .filter(OvertimeMonthConfig.config_type == config_type,
                OvertimeMonthConfig.is_active.is_(True))
        .first()
    )
    start_day = cfg.start_day if cfg and cfg.start_day else 26
    end_day = cfg.end_day if cfg and cfg.end_day else 25
    y, m = int(month[:4]), int(month[4:6])
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    start = datetime(py, pm, min(start_day, 28))
    end = datetime(y, m, min(end_day, 28), 23, 59, 59)
    return start, end


_NO_LOCK = threading.Lock()


def generate_no(db, prefix: str, month: str) -> str:
    """旧 GenerateNo: lock 串行 + 取同前缀尾号 MAX + 1, D3 补零。"""
    head = f"{prefix}{month}-"
    with _NO_LOCK:
        nums = (
            db.query(OvertimeApply.apply_no)
            .filter(OvertimeApply.apply_no.like(f"{head}%"))
            .all()
        )
        mx = 0
        for (no,) in nums:
            try:
                mx = max(mx, int((no or "")[len(head):]))
            except ValueError:
                pass
        return f"{head}{mx + 1:03d}"


def generate_personal_no(db, month: str) -> str:
    return generate_no(db, "GR-", month)


def generate_apply_no(db, month: str) -> str:
    return generate_no(db, "JB-", month)


# ---------------------------------------------------------------- 备注里的源明细编码

def strip_source_ids(remark) -> str:
    return _SRC_RE.sub("", remark or "").strip()


def encode_source_ids(ids, remark: str = "") -> str:
    return f"__SRC__[{','.join(str(i) for i in ids)}]" + (remark or "")


def decode_source_ids(remark) -> list[int]:
    m = _SRC_RE.search(remark or "")
    if not m:
        return []
    inner = m.group(0)[8:-1]
    return [int(x) for x in inner.split(",") if x.strip().isdigit()]


def preserve_source_prefix(old_remark, new_remark) -> str:
    m = _SRC_RE.search(old_remark or "")
    return (m.group(0) if m else "") + (new_remark or "")


# ---------------------------------------------------------------- 基础映射与名称

def user_names(db) -> dict:
    return {u.id: (u.real_name or u.username or "") for u in db.query(User).all()}


def dept_paths(db) -> dict:
    return {d.id: d.full_path or d.name or "" for d in db.query(OvertimeDept).all()}


def dept_rows(db) -> list:
    return db.query(OvertimeDept).all()


def personnel_map(db) -> dict:
    return {p.id: p for p in db.query(OvertimePersonnel).all()}


def new_system_dept_names(db) -> dict:
    from app.models.user import Department
    return {d.id: d.name for d in db.query(Department).all()}


# ---------------------------------------------------------------- 加班部门镜像树

def descendants(db, dept_id: int, active_only: bool = True) -> list[int]:
    """旧 GetDescendantIds: 递归含自身,仅启用节点。"""
    q = db.query(OvertimeDept.id, OvertimeDept.parent_id)
    if active_only:
        q = q.filter(OvertimeDept.is_active.is_(True))
    pairs = q.all()
    children = {}
    for i, p in pairs:
        children.setdefault(p, []).append(i)
    out, stack = [], [dept_id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out


def descendants_with_depth(db, dept_id: int, max_depth: int) -> list[int]:
    root = db.get(OvertimeDept, dept_id)
    if root is None or not root.is_active:
        return []
    max_level = (root.level or 1) + max_depth
    q = db.query(OvertimeDept.id, OvertimeDept.parent_id, OvertimeDept.level).filter(
        OvertimeDept.is_active.is_(True)
    ).all()
    children = {}
    levels = {}
    for i, p, lv in q:
        children.setdefault(p, []).append(i)
        levels[i] = lv or 1
    out, stack = [], [(dept_id, root.level or 1)]
    while stack:
        cur, lv = stack.pop()
        out.append(cur)
        if lv < max_level:
            for c in children.get(cur, []):
                stack.append((c, levels.get(c, lv + 1)))
    return out


def resolve_dept_ids(db, dept_id, max_depth) -> list[int] | None:
    """核销/汇总/人员的部门筛选:None=不过滤;0=仅本级;>0=限深;空=全部下级。"""
    if not dept_id or int(dept_id) <= 0:
        return None
    did = int(dept_id)
    if max_depth is None or max_depth == "":
        return descendants(db, did)
    md = int(max_depth)
    if md == 0:
        return [did]
    return descendants_with_depth(db, did, md)


def visible_ot_dept_ids(db, user: User):
    """旧 GetVisibleOtDeptIds: 按登录用户部门子树找镜像节点及其后代。

    返回 None 表示超管/无部门=不限;返回空集合表示该用户一个可见加班部门都没有。
    """
    scope = dept_scope_ids(db, user)
    if scope is None:
        return None
    nodes = (
        db.query(OvertimeDept.id)
        .filter(OvertimeDept.is_active.is_(True), OvertimeDept.sys_bumen_id.in_(scope))
        .all()
    )
    out = set()
    for (nid,) in nodes:
        out.update(descendants(db, nid))
    return out


def mirror_by_sys(db, sys_id):
    if not sys_id:
        return None
    return (
        db.query(OvertimeDept)
        .filter(OvertimeDept.sys_bumen_id == sys_id, OvertimeDept.is_active.is_(True))
        .order_by(OvertimeDept.level, OvertimeDept.id)
        .first()
    )


def user_primary_sys_dept(user: User):
    ds = list(user.departments or [])
    return ds[0].id if ds else None


def default_apply_dept_id(db, user: User):
    """旧 GetApplyDeptId: 本部门镜像,否则沿上级找祖先镜像,都无返回 None。"""
    from app.models.user import Department
    sys_id = user_primary_sys_dept(user)
    while sys_id:
        node = mirror_by_sys(db, sys_id)
        if node:
            return node.id
        d = db.get(Department, sys_id)
        sys_id = d.parent_id if d else None
    return None


def dept_tree(db, user: User, full: bool = False) -> list:
    """旧 GetOvertimeDeptTree 返回 EasyUI 树结构(id/text/displayText/fullPath/children)。"""
    rows = db.query(OvertimeDept).order_by(OvertimeDept.sort_order, OvertimeDept.id).all()
    by_parent = {}
    for d in rows:
        by_parent.setdefault(d.parent_id, []).append(d)

    def build(node):
        suffix = "" if node.is_active else " (已停用)"
        return {
            "id": node.id,
            "text": (node.name or "") + suffix,
            "displayText": (node.full_path or node.name or "") + suffix,
            "fullPath": node.full_path or node.name or "",
            "sysBumenId": node.sys_bumen_id,
            "isActive": bool(node.is_active),
            "children": [build(c) for c in by_parent.get(node.id, [])],
        }

    if full or is_admin(user):
        return [build(d) for d in by_parent.get(None, [])]
    sys_id = user_primary_sys_dept(user)
    node = mirror_by_sys(db, sys_id)
    return [build(node)] if node else []


def recalc_full_paths(db, root_id: int | None = None):
    """改名/移动后递归重算 full_path 与 level(旧 RecalcFullPath)。"""
    rows = db.query(OvertimeDept).all()
    by_id = {d.id: d for d in rows}
    by_parent = {}
    for d in rows:
        by_parent.setdefault(d.parent_id, []).append(d)

    def walk(node, parent_path: str, level: int):
        node.full_path = f"{parent_path}/{node.name}" if parent_path else (node.name or "")
        node.level = level
        for c in by_parent.get(node.id, []):
            walk(c, node.full_path, level + 1)

    roots = [by_id[root_id]] if root_id and root_id in by_id else by_parent.get(None, [])
    for r in roots:
        walk(r, "", 1)


def lca_dept(db, dept_ids) -> int | None:
    """旧 GetLCA: 取各节点根->自身路径的最近公共祖先。"""
    rows = {d.id: d for d in db.query(OvertimeDept).all()}
    paths = []
    for did in dict.fromkeys([x for x in dept_ids if x]):
        chain, cur, guard = [], did, 0
        while cur in rows and guard < 50:
            chain.append(cur)
            cur = rows[cur].parent_id
            guard += 1
        paths.append(list(reversed(chain)))
    if not paths:
        return None
    common = None
    for i in range(min(len(p) for p in paths)):
        vals = {p[i] for p in paths}
        if len(vals) == 1:
            common = next(iter(vals))
        else:
            break
    return common


# ---------------------------------------------------------------- 汇总时长 / 查重

def update_apply_total_hours(db, apply_id: int):
    total = (
        db.query(func.coalesce(func.sum(OvertimeTimeEntry.total_hours), 0))
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeApplyDetail.apply_id == apply_id)
        .scalar()
    )
    apply = db.get(OvertimeApply, apply_id)
    if apply:
        apply.total_hours = dec2(total or 0)
        apply.update_time = datetime.now()


def update_detail_total_hours(db, detail_id: int):
    total = db.query(func.coalesce(func.sum(OvertimeTimeEntry.total_hours), 0)).filter(
        OvertimeTimeEntry.detail_id == detail_id
    ).scalar()
    detail = db.get(OvertimeApplyDetail, detail_id)
    if detail:
        detail.total_hours = dec2(total or 0)


def monthly_total_hours(db, personnel_id: int, month: str):
    """旧 GetMonthlyTotalHours: 只累计无头部或头部 approved 的明细折算时长。"""
    q = (
        db.query(func.coalesce(func.sum(OvertimeApplyDetail.total_hours), 0))
        .outerjoin(OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id)
        .filter(
            OvertimeApplyDetail.personnel_id == personnel_id,
            OvertimeApplyDetail.apply_month == month,
        )
        .filter(
            (OvertimeApply.id.is_(None)) | (OvertimeApply.status == "approved")
        )
    )
    return D(q.scalar())


def check_entry_overlap(db, personnel_id, work_date, start, end, is_exclusive,
                        exclude_entry_id=0, exclude_apply_id=0):
    """旧 CheckEntryOverlap(第三层 DB 查重): 会扫描独立个人明细。

    返回冲突文案或 None。
    """
    q = (
        db.query(OvertimeTimeEntry, OvertimeApplyDetail)
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(
            OvertimeApplyDetail.personnel_id == personnel_id,
            OvertimeTimeEntry.work_date == as_date(work_date),
        )
    )
    if exclude_entry_id:
        q = q.filter(OvertimeTimeEntry.id != exclude_entry_id)
    if exclude_apply_id:
        q = q.filter(
            (OvertimeApplyDetail.apply_id.is_(None))
            | (OvertimeApplyDetail.apply_id != exclude_apply_id)
        )
    apply_ids = {}
    candidates = []
    for e, d in q.all():
        if d.apply_id:
            if d.apply_id not in apply_ids:
                a = db.get(OvertimeApply, d.apply_id)
                apply_ids[d.apply_id] = (a.status if a else None)
            if apply_ids[d.apply_id] == "rejected":
                continue
        elif (d.status or "") == "grouped":
            continue
        candidates.append(e)
    p = db.get(OvertimePersonnel, personnel_id)
    name = p.name if p else "该人员"
    ds = fmt_d(work_date)
    has_excl = any(is_exclusive_entry(e.is_full_day, e.shift_type) for e in candidates)
    if is_exclusive and candidates:
        return f"{name}在{ds}已有其他加班记录，独占类型/全天加班不可重复录入"
    if not is_exclusive and has_excl:
        return f"{name}在{ds}已有独占类型/全天加班记录，当日不可录其他类别"
    if not is_exclusive:
        for e in candidates:
            if has_time_overlap(start, end, e.start_time, e.end_time):
                s = e.start_time.strftime("%H:%M") if e.start_time else ""
                t = e.end_time.strftime("%H:%M") if e.end_time else ""
                return f"{name}在{ds}的时段与已有记录重叠({s}-{t})"
    return None


def find_overlap_for_detail(db, detail_id: int) -> str | None:
    """旧 FindOverlappingEntriesForDetail: 提交个人记录时逐条查重。"""
    detail = db.get(OvertimeApplyDetail, detail_id)
    if not detail:
        return "记录不存在"
    p = db.get(OvertimePersonnel, detail.personnel_id)
    name = p.name if p else "该人员"
    entries = (
        db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == detail_id).all()
    )
    for e in entries:
        others = (
            db.query(OvertimeTimeEntry, OvertimeApplyDetail)
            .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
            .filter(
                OvertimeApplyDetail.personnel_id == detail.personnel_id,
                OvertimeTimeEntry.work_date == e.work_date,
                OvertimeTimeEntry.id != e.id,
            )
            .all()
        )
        for o, od in others:
            if od.apply_id:
                a = db.get(OvertimeApply, od.apply_id)
                if a and a.status == "rejected":
                    continue
            elif (od.status or "") == "grouped":
                continue
            excl = is_exclusive_entry(e.is_full_day, e.shift_type) or is_exclusive_entry(
                o.is_full_day, o.shift_type
            )
            if excl or has_time_overlap(e.start_time, e.end_time, o.start_time, o.end_time):
                s = e.start_time.strftime("%Y-%m-%d %H:%M") if e.start_time else ""
                et = e.end_time.strftime("%H:%M") if e.end_time else ""
                os = o.start_time.strftime("%m-%d %H:%M") if o.start_time else ""
                oe = o.end_time.strftime("%H:%M") if o.end_time else ""
                return (
                    f"{name} 的时段 {s}~{et} 存在重叠：与 [已有记录] {os}~{oe} 冲突"
                    if excl else
                    f"{name} 的时段 {s}~{et} 存在重叠：与 [{os}~{oe}] 冲突"
                )
    return None


# ---------------------------------------------------------------- 补休余额

def comp_leave_balance(db, personnel_id: int) -> Decimal:
    """旧 CalcCompLeaveBalance: 近 12 个月 raw_hours 累计 - 全部已登记补休,下限 0。"""
    cutoff = datetime.now().date() - timedelta(days=365)
    earned = (
        db.query(func.coalesce(func.sum(OvertimeTimeEntry.raw_hours), 0))
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .outerjoin(OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id)
        .filter(
            OvertimeApplyDetail.personnel_id == personnel_id,
            OvertimeTimeEntry.work_date >= cutoff,
            ((OvertimeApplyDetail.settle_type == SETTLE_COMP)
             | (OvertimeApply.settle_type == SETTLE_COMP)),
        )
        .scalar()
    )
    used = db.query(func.coalesce(func.sum(OvertimeCompLeave.hours), 0)).filter(
        OvertimeCompLeave.personnel_id == personnel_id
    ).scalar()
    return max(Decimal("0"), dec2(D(earned) - D(used)))


# ---------------------------------------------------------------- 状态

def personal_display_status(detail, apply) -> str:
    """旧 GetMyPersonalRecords 展示态: 无头部用 detail.status;有头部且 draft/空显示 grouped。"""
    if apply is None:
        return detail.status or "draft"
    st = apply.status or ""
    return "grouped" if st in ("", "draft") else st


def summary_status(detail_status, apply_status) -> str:
    """旧 GetSummaryStatus 的状态优先级。"""
    priority = {
        "verified": 5, "approved": 5, "printed": 4, "pending": 4,
        "grouped": 3, "submitted": 2, "rejected": 1,
    }
    a, d = apply_status or "", detail_status or ""
    if a in ("verified", "approved", "printed", "pending", "rejected"):
        return a
    return a if priority.get(a, 0) >= priority.get(d, 0) else d


def entry_time_slots(db, detail_ids) -> dict:
    """旧 timeSlots: 'MM-dd(周X) HH:mm-HH:mm reason',多条 <br> 连接。"""
    if not detail_ids:
        return {}
    rows = (
        db.query(OvertimeTimeEntry)
        .filter(OvertimeTimeEntry.detail_id.in_(detail_ids))
        .order_by(OvertimeTimeEntry.work_date, OvertimeTimeEntry.start_time)
        .all()
    )
    week = "一二三四五六日"
    out = {}
    for e in rows:
        if not e.work_date:
            continue
        wd = week[e.work_date.weekday()]
        s = e.start_time.strftime("%H:%M") if e.start_time else ""
        t = e.end_time.strftime("%H:%M") if e.end_time else ""
        txt = f"{e.work_date.strftime('%m-%d')}(周{wd}) {s}-{t} {e.reason or ''}".rstrip()
        out.setdefault(e.detail_id, []).append(txt)
    return {k: "<br>".join(v) for k, v in out.items()}


def entry_totals(db, detail_ids) -> dict:
    """按 detail 汇总 raw_hours / overtime_amount。"""
    if not detail_ids:
        return {}
    rows = (
        db.query(
            OvertimeTimeEntry.detail_id,
            func.coalesce(func.sum(OvertimeTimeEntry.raw_hours), 0),
            func.coalesce(func.sum(OvertimeTimeEntry.overtime_amount), 0),
        )
        .filter(OvertimeTimeEntry.detail_id.in_(detail_ids))
        .group_by(OvertimeTimeEntry.detail_id)
        .all()
    )
    return {did: (D(raw), D(amount)) for did, raw, amount in rows}
