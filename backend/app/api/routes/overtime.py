"""加班申请审批 - 主路由(字典 / 我的加班 / 申请单 / 时段明细 / 校验)。

1:1 复刻旧 OvertimeApplyController 的前半部分。所有写接口返回
{success, msg, ...};业务校验失败抛 400(detail 会被前端拦截器提示)。

路径前缀 /api/overtime,由 app/main.py 注册。静态子路径一律排在 /{id} 之前。
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.overtime import (
    OvertimeApply,
    OvertimeApplyDetail,
    OvertimeDept,
    OvertimePersonnel,
    OvertimeTimeEntry,
)
from app.models.user import User
from app.services import overtime_common as oc

router = APIRouter()


# ================================================================ 字典 / 上下文

@router.get("/dicts")
def get_dicts(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """页面初始化一次性拉齐月份/类别/状态/权限/部门树/人员池。"""
    people = (
        db.query(OvertimePersonnel)
        .filter(OvertimePersonnel.is_active.is_(True))
        .order_by(OvertimePersonnel.name, OvertimePersonnel.id)
        .all()
    )
    mine = next((p for p in people if p.bb_user_id == current.id), None)
    paths = oc.dept_paths(db)
    return {
        "months": oc.month_options(),
        "current_month": oc.current_month(),
        "work_types": oc.WORK_TYPES,
        "exclusive_work_types": oc.EXCLUSIVE_WORK_TYPES,
        "comp_leave_work_types": oc.COMP_LEAVE_WORK_TYPES,
        "multi_date_work_types": oc.MULTI_DATE_WORK_TYPES,
        "status_text": oc.STATUS_TEXT,
        "approval_status_text": oc.APPROVAL_STATUS_TEXT,
        "approval_enabled": oc.approval_enabled(db),
        "perms": {
            "is_admin": oc.is_admin(current),
            "is_verifier": oc.is_verifier(current),
            "is_hr": oc.is_hr(current),
            "is_approver": oc.is_approver(db, current),
            "can_apply": oc.has_any_perm(current, oc.PERM_APPLY, oc.PERM_VERIFY, oc.PERM_HR, oc.PERM_MANAGE),
            "can_verify": oc.has_any_perm(current, oc.PERM_VERIFY, oc.PERM_HR, oc.PERM_MANAGE),
            "can_summary": oc.is_hr(current),
            "can_config": oc.is_hr(current) or oc.is_admin(current),
        },
        "user": {"id": current.id, "name": current.real_name or current.username,
                 "dept_id": oc.user_primary_sys_dept(current)},
        "my_personnel": (
            {"id": mine.id, "name": mine.name, "employee_no": mine.employee_no,
             "daily_wage": oc.fnum(mine.daily_wage), "dept_id": mine.bb_bumen_id}
            if mine else None
        ),
        "dept_tree": oc.dept_tree(db, current),
        "dept_paths": paths,
        "personnel": [
            {"id": p.id, "name": p.name, "employee_no": p.employee_no,
             "dept_id": p.bb_bumen_id, "dept_name": paths.get(p.bb_bumen_id, ""),
             "daily_wage": oc.fnum(p.daily_wage), "bb_user_id": p.bb_user_id,
             "is_active": bool(p.is_active)}
            for p in people
        ],
        "users": [
            {"id": u.id, "name": u.real_name or u.username, "username": u.username}
            for u in db.query(User).order_by(User.id).all()
        ],
    }


@router.get("/gongdan")
def get_gongdan(no: str = "", db: Session = Depends(get_db),
                current: User = Depends(get_current_user)):
    """维抢修工单号 -> 地址/日期。旧库 WorkOrder 尚未迁移,返回空结果而不报错。"""
    if not no.strip():
        raise HTTPException(400, "工单号不能为空")
    return {"success": False, "msg": "工单不存在(工单模块尚未迁移)", "dizhi": "", "riqi": ""}


# ================================================================ 我的加班

def _my_record_row(db, detail, apply, names, paths, pmap, slots, totals):
    p = pmap.get(detail.personnel_id)
    raw, amount = totals.get(detail.id, (oc.D(0), oc.D(0)))
    month = (apply.apply_month if apply and apply.apply_month else detail.apply_month) or ""
    settle = (apply.settle_type if apply and apply.settle_type else detail.settle_type) or oc.SETTLE_PAY
    status = oc.personal_display_status(detail, apply)
    display_no = (
        (apply.apply_no if apply and apply.apply_no else "")
        or f"GR-{month}-{detail.id:04d}"
    )
    dept_id = None
    if p:
        dept_id = p.bb_bumen_id
    if apply and apply.apply_dept_id:
        dept_id = apply.apply_dept_id
    return {
        "id": detail.id,
        "apply_id": apply.id if apply else None,
        "apply_no": display_no,
        "record_type": "personal",
        "apply_month": month,
        "work_type": (apply.work_type if apply and apply.work_type else detail.work_type) or "",
        "settle_type": settle,
        "apply_date": oc.fmt_d(apply.apply_date) if apply else "",
        "total_hours": oc.fnum(detail.total_hours),
        "rawHours": oc.fnum(raw),
        "overtimeAmount": oc.fnum(amount),
        "status": status,
        "remark": oc.strip_source_ids(apply.remark) if apply else "",
        "create_time": oc.fmt_dt(detail.create_time or (apply.create_time if apply else None)),
        "applyUserName": names.get(apply.apply_user_id, "") if apply else names.get(detail.apply_user_id, ""),
        "deptName": paths.get(dept_id, ""),
        "personnelName": p.name if p else "",
        "employeeNo": p.employee_no if p else "",
        "timeSlots": slots.get(detail.id, ""),
    }


@router.get("/my-records")
def my_records(status: str = "all", month: str = "", keyword: str = "",
               page: int = 1, rows: int = 50,
               db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """旧 GetMyPersonalRecords: 同时覆盖"有头部个人记录"与"独立个人明细"两种载体。"""
    q = db.query(OvertimeApplyDetail, OvertimeApply).outerjoin(
        OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id
    )
    if not oc.is_admin(current):
        bound_personnel = [
            p.id for p in db.query(OvertimePersonnel.id).filter(
                OvertimePersonnel.bb_user_id == current.id
            ).all()
        ]
        conds = [OvertimeApply.apply_user_id == current.id,
                 OvertimeApplyDetail.apply_user_id == current.id]
        if bound_personnel:
            conds.append(OvertimeApplyDetail.personnel_id.in_(bound_personnel))
        q = q.filter(or_(*conds))
    if month:
        q = q.filter(func.coalesce(
            func.nullif(OvertimeApply.apply_month, ""), OvertimeApplyDetail.apply_month
        ) == month)
    if status and status != "all":
        if status in ("draft", "submitted"):
            q = q.filter(OvertimeApplyDetail.apply_id.is_(None),
                         OvertimeApplyDetail.status == status)
        elif status == "grouped":
            q = q.filter(OvertimeApplyDetail.apply_id.isnot(None))
        else:
            q = q.filter(OvertimeApplyDetail.apply_id.isnot(None),
                         OvertimeApply.status == status)
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        ids = [p.id for p in db.query(OvertimePersonnel.id).filter(
            OvertimePersonnel.name.like(kw)).all()]
        q = q.filter(OvertimeApplyDetail.personnel_id.in_(ids or [-1]))
    total = q.count()
    items = (
        q.order_by(OvertimeApplyDetail.create_time.desc(), OvertimeApplyDetail.id.desc())
        .offset((page - 1) * rows).limit(rows).all()
    )
    names, paths, pmap = oc.user_names(db), oc.dept_paths(db), oc.personnel_map(db)
    slots = oc.entry_time_slots(db, [d.id for d, _ in items])
    totals = oc.entry_totals(db, [d.id for d, _ in items])
    return {"total": total, "rows": [_my_record_row(db, d, a, names, paths, pmap, slots, totals)
                                     for d, a in items]}


def _detail_entries_payload(details):
    return [
        {
            "personnel_id": x.get("personnel_id"),
            "accounting_month": x.get("accounting_month", ""),
            "total_hours": x.get("total_hours", 0),
            "sort_order": x.get("sort_order", 0),
            "timeEntries": x.get("timeEntries", []),
        }
        for x in details
    ]


def _insert_details_entries(db, apply_id, details, user, month, work_type, settle):
    """旧 InsertDetailsAndEntries: 前端 DTO 的时长/金额直接落库,后端不重算。"""
    for idx, d in enumerate(details):
        detail = OvertimeApplyDetail(
            apply_id=apply_id,
            personnel_id=int(d.get("personnel_id") or 0),
            accounting_month=d.get("accounting_month") or month,
            apply_month=month,
            apply_user_id=user.id,
            total_hours=oc.dec2(d.get("total_hours") or 0),
            sort_order=d.get("sort_order", idx),
            work_type=work_type,
            status=None if apply_id else "draft",
            settle_type=settle,
            create_time=datetime.now(),
        )
        db.add(detail)
        db.flush()
        for j, te in enumerate(d.get("timeEntries") or []):
            db.add(OvertimeTimeEntry(
                detail_id=detail.id,
                work_type=te.get("work_type") or work_type,
                work_date=oc.as_date(te.get("work_date")) if te.get("work_date") else None,
                start_time=oc.parse_dt(te.get("start_time")),
                end_time=oc.parse_dt(te.get("end_time")),
                raw_hours=oc.dec2(te.get("raw_hours") or 0),
                multiplier=oc.D(te.get("multiplier") if te.get("multiplier") not in (None, "") else 1.5),
                total_hours=oc.dec2(te.get("total_hours") or 0),
                reason=te.get("reason") or "",
                daily_wage=oc.dec2(te.get("daily_wage") or 0) if te.get("daily_wage") is not None else None,
                overtime_amount=oc.dec2(te.get("overtime_amount") or 0) if te.get("overtime_amount") is not None else None,
                work_order_no=te.get("work_order_no") or "",
                address=te.get("address") or "",
                accounting_month=te.get("accounting_month") or month,
                sort_order=te.get("sort_order", j),
                is_full_day=bool(te.get("is_full_day")),
                shift_type=oc.normalize_shift(te.get("shift_type")),
            ))
        if apply_id is None:
            oc.update_detail_total_hours(db, detail.id)


@router.post("/personal-record")
def save_personal_record(payload: dict = Body(...), db: Session = Depends(get_db),
                         current: User = Depends(get_current_user)):
    """旧 SavePersonalRecord(新建个人记录头 + 明细,前端 DTO 值直落)。"""
    details = payload.get("details") or []
    month = (payload.get("apply_month") or "").strip()
    work_type = (payload.get("work_type") or "").strip()
    if not details or not (details[0].get("timeEntries") or []):
        raise HTTPException(400, "请至少添加一条加班时段")
    if not month:
        raise HTTPException(400, "请选择所属月份")
    if not work_type:
        raise HTTPException(400, "请选择加班类型")
    if len(details) > 1:
        raise HTTPException(400, "个人加班记录只能包含一个人员")
    pid = int(details[0].get("personnel_id") or 0)
    if not pid:
        raise HTTPException(400, "请选择加班人员")
    for te in details[0].get("timeEntries") or []:
        if te.get("work_type") and te["work_type"] != work_type:
            raise HTTPException(400, "时段类型与记录类型不一致")
    person = db.get(OvertimePersonnel, pid)
    if not person:
        raise HTTPException(400, "人员不存在")
    rid = int(payload.get("id") or 0)
    settle = oc.SETTLE_PAY  # 旧代码两分支都返回"加班费",1:1 保留
    if rid:
        apply = db.get(OvertimeApply, rid)
        if not apply:
            raise HTTPException(400, "记录不存在")
        if apply.status != "draft":
            raise HTTPException(400, "只能编辑草稿状态的记录")
        for d in db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == rid).all():
            _delete_detail(db, d.id)
        apply.apply_month = month
        apply.work_type = work_type
        apply.remark = payload.get("remark") or ""
        apply.update_time = datetime.now()
    else:
        dup = (
            db.query(OvertimeApply.id)
            .join(OvertimeApplyDetail, OvertimeApplyDetail.apply_id == OvertimeApply.id)
            .filter(OvertimeApply.record_type == "personal",
                    OvertimeApplyDetail.personnel_id == pid,
                    OvertimeApply.apply_month == month, OvertimeApply.work_type == work_type)
            .first()
        )
        if dup:
            raise HTTPException(400, "该人员在本月已有同类型同结算方式的加班记录，不能重复创建")
        apply = OvertimeApply(
            apply_no=oc.generate_personal_no(db, month), record_type="personal",
            apply_month=month, work_type=work_type, apply_user_id=current.id,
            apply_dept_id=person.bb_bumen_id, apply_date=oc.parse_dt(payload.get("apply_date"), datetime.now()),
            status="draft", remark=payload.get("remark") or "", create_time=datetime.now(),
            settle_type=settle,
        )
        db.add(apply)
        db.flush()
        rid = apply.id
    _insert_details_entries(db, rid, details, current, month, work_type, settle)
    oc.update_apply_total_hours(db, rid)
    db.commit()
    return {"success": True, "msg": "保存成功", "id": rid}


def _delete_detail(db, detail_id):
    db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == detail_id).delete()
    db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.id == detail_id).delete()


def _get_personal_detail_or_404(db, detail_id):
    d = db.get(OvertimeApplyDetail, detail_id)
    if not d:
        raise HTTPException(400, "记录不存在")
    return d


@router.post("/personal/records/{detail_id}/submit")
def submit_personal(detail_id: int, db: Session = Depends(get_db),
                    current: User = Depends(get_current_user)):
    d = _get_personal_detail_or_404(db, detail_id)
    if (d.status or "draft") != "draft":
        raise HTTPException(400, "只有草稿状态可提交")
    conflict = oc.find_overlap_for_detail(db, detail_id)
    if conflict:
        raise HTTPException(400, conflict)
    d.status = "submitted"
    hours = oc.monthly_total_hours(db, d.personnel_id, d.apply_month or "")
    msg = "已提交，等待班长汇总"
    warn = ""
    if hours > 36:
        p = db.get(OvertimePersonnel, d.personnel_id)
        warn = f"警告：{p.name if p else ''}本月累计已超36小时({float(hours):.1f}h)，已提交但请HR确认"
        msg = warn
    db.commit()
    return {"success": True, "msg": msg, "warning": warn}


@router.post("/personal/records/{detail_id}/recall")
def recall_personal(detail_id: int, db: Session = Depends(get_db),
                    current: User = Depends(get_current_user)):
    d = _get_personal_detail_or_404(db, detail_id)
    if d.status != "submitted":
        raise HTTPException(400, "只有已提交状态可撤回")
    d.status = "draft"
    db.commit()
    return {"success": True, "msg": "已撤回为草稿"}


@router.post("/personal/records/batch-submit")
def batch_submit_personal(payload: dict = Body(...), db: Session = Depends(get_db),
                          current: User = Depends(get_current_user)):
    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(400, "请选择要提交的记录")
    rows = db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.id.in_(ids)).all()
    if not rows:
        raise HTTPException(400, "未找到可提交的记录")
    if any((d.status or "draft") != "draft" for d in rows):
        raise HTTPException(400, "选中记录中存在非草稿状态，只能提交草稿记录")
    warns = []
    for d in rows:
        conflict = oc.find_overlap_for_detail(db, d.id)
        if conflict:
            raise HTTPException(400, conflict)
    for d in rows:
        d.status = "submitted"
        h = oc.monthly_total_hours(db, d.personnel_id, d.apply_month or "")
        if h > 36:
            p = db.get(OvertimePersonnel, d.personnel_id)
            warns.append(f"{p.name if p else ''}本月累计已超36小时({float(h):.1f}h)")
    msg = f"已提交{len(rows)}条记录，等待班长汇总"
    warn = ""
    if warns:
        warn = "警告：" + "；".join(warns) + "，已提交但请HR确认"
        msg = warn
    db.commit()
    return {"success": True, "msg": msg, "warning": warn}


@router.post("/personal/records/batch-delete")
def batch_delete_personal(payload: dict = Body(...), db: Session = Depends(get_db),
                          current: User = Depends(get_current_user)):
    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(400, "请选择要删除的记录")
    rows = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.id.in_(ids),
        OvertimeApplyDetail.apply_id.is_(None),
        OvertimeApplyDetail.status.in_(["draft", "submitted"]),
    ).all()
    if not rows:
        raise HTTPException(400, "未找到可删除的记录")
    for d in rows:
        _delete_detail(db, d.id)
    db.commit()
    return {"success": True, "msg": f"已删除{len(rows)}条记录"}


@router.post("/personal/records/{detail_id}/delete")
def delete_personal(detail_id: int, db: Session = Depends(get_db),
                    current: User = Depends(get_current_user)):
    d = _get_personal_detail_or_404(db, detail_id)
    if d.status not in ("draft", "submitted") or d.apply_id:
        raise HTTPException(400, "只能删除草稿或已提交状态的记录")
    _delete_detail(db, detail_id)
    db.commit()
    return {"success": True, "msg": "删除成功"}


@router.post("/personal/header")
def save_personal_header(payload: dict = Body(...), db: Session = Depends(get_db),
                         current: User = Depends(get_current_user)):
    """旧 SavePersonalHeader(注意:旧代码新建时用的是 JB- 前缀,1:1 保留)。"""
    month = (payload.get("apply_month") or "").strip()
    work_type = (payload.get("work_type") or "").strip()
    if not month:
        raise HTTPException(400, "请选择所属月份")
    if not work_type:
        raise HTTPException(400, "请选择加班类别")
    rid = int(payload.get("id") or 0)
    if rid:
        a = db.get(OvertimeApply, rid)
        if not a:
            raise HTTPException(400, "记录不存在")
        if a.status != "draft":
            raise HTTPException(400, "只能编辑草稿状态的记录")
        a.apply_month = month
        a.work_type = work_type
        a.apply_date = oc.parse_dt(payload.get("apply_date"), datetime.now())
        a.remark = payload.get("remark") or ""
        a.update_time = datetime.now()
        no = a.apply_no
    else:
        a = OvertimeApply(
            apply_no=oc.generate_apply_no(db, month), record_type="personal",
            apply_month=month, work_type=work_type, apply_user_id=current.id,
            apply_dept_id=oc.default_apply_dept_id(db, current),
            apply_date=oc.parse_dt(payload.get("apply_date"), datetime.now()),
            status="draft", remark=payload.get("remark") or "",
            create_time=datetime.now(), settle_type=oc.SETTLE_PAY,
        )
        db.add(a)
        db.flush()
        rid, no = a.id, a.apply_no
    db.commit()
    return {"success": True, "id": rid, "apply_no": no}


@router.get("/personal/records/{detail_id}/detail")
def personal_record_detail(detail_id: int, db: Session = Depends(get_db),
                           current: User = Depends(get_current_user)):
    """旧 GetPersonalRecordDetail: 明细表格与日历看板共用。"""
    d = db.get(OvertimeApplyDetail, detail_id)
    if not d:
        return {"rows": []}
    a = db.get(OvertimeApply, d.apply_id) if d.apply_id else None
    rows = (
        db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == detail_id)
        .order_by(OvertimeTimeEntry.work_date, OvertimeTimeEntry.start_time).all()
    )
    out = []
    for e in rows:
        out.append({
            "entryId": e.id, "workType": e.work_type or "未指定类型",
            "workDate": oc.fmt_d(e.work_date),
            "startTime": e.start_time.strftime("%Y-%m-%d %H:%M") if e.start_time else "",
            "endTime": e.end_time.strftime("%Y-%m-%d %H:%M") if e.end_time else "",
            "rawHours": oc.fnum(e.raw_hours), "totalHours": oc.fnum(e.total_hours),
            "amount": oc.fnum(e.overtime_amount), "reason": e.reason or "",
            "work_order_no": e.work_order_no or "", "address": e.address or "",
            "multiplier": oc.fnum(e.multiplier), "daily_wage": oc.fnum(e.daily_wage),
            "status": oc.summary_status(d.status, a.status if a else None),
        })
    return {"rows": out}


# ================================================================ 批量新建

def _batch_overlap_check(db, pid, entries):
    """旧 CheckBatchEntryOverlap: 先内存分组,再逐条 DB 查重。"""
    by_day = {}
    for te in entries:
        day = oc.as_date(te.get("work_date"))
        by_day.setdefault(day, []).append(te)
    for day, group in by_day.items():
        excl = [x for x in group if oc.is_exclusive_entry(x.get("is_full_day"), x.get("shift_type"))]
        if len(excl) > 1:
            return f"{day} 独占类型/全天加班不可重复录入"
        if excl and len(group) > 1:
            return f"{day} 独占类型/全天加班独占当日"
        normals = [x for x in group if x not in excl]
        for i in range(len(normals)):
            for j in range(i + 1, len(normals)):
                a, b = normals[i], normals[j]
                if oc.has_time_overlap(oc.parse_dt(a.get("start_time")), oc.parse_dt(a.get("end_time")),
                                       oc.parse_dt(b.get("start_time")), oc.parse_dt(b.get("end_time"))):
                    return f"{day} 时段重叠"
    for te in entries:
        st = oc.parse_dt(te.get("start_time"))
        en = oc.parse_dt(te.get("end_time"))
        excl = oc.is_exclusive_entry(te.get("is_full_day"), te.get("shift_type"))
        msg = oc.check_entry_overlap(db, pid, te.get("work_date"), st, en, excl)
        if msg:
            return msg
    return None


@router.post("/batch-records")
def save_batch_records(payload: dict = Body(...), db: Session = Depends(get_db),
                       current: User = Depends(get_current_user)):
    """旧 SaveBatchPersonalRecord: 人员 x 时段 笛卡尔积,后端重算时长/金额。"""
    pids = list(dict.fromkeys(int(x) for x in (payload.get("personnelIds") or [])))
    entries = payload.get("timeEntries") or []
    month = (payload.get("apply_month") or "").strip()
    work_type = (payload.get("work_type") or "").strip()
    settle = payload.get("settle_type") or oc.SETTLE_PAY
    if not pids:
        raise HTTPException(400, "请选择至少一个人员")
    if not entries:
        raise HTTPException(400, "请至少添加一条加班时段")
    if not month:
        raise HTTPException(400, "请选择所属月份")
    if not work_type:
        raise HTTPException(400, "请选择加班类型")
    pmap = oc.personnel_map(db)
    if not oc.is_verifier(current):
        mine = {p.id for p in pmap.values() if p.bb_user_id == current.id}
        if not mine or not set(pids).issubset(mine):
            raise HTTPException(403, "无权操作")
    created, warnings, hour_warnings = [], [], []
    for pid in pids:
        p = pmap.get(pid)
        if not p or not p.is_active:
            warnings.append({"name": f"ID:{pid}", "reason": "人员不存在或已停用"})
            continue
        existing = (
            db.query(OvertimeApplyDetail)
            .filter(OvertimeApplyDetail.apply_id.is_(None),
                    OvertimeApplyDetail.personnel_id == pid,
                    OvertimeApplyDetail.apply_month == month,
                    OvertimeApplyDetail.work_type == work_type,
                    OvertimeApplyDetail.settle_type == settle)
            .order_by(OvertimeApplyDetail.id).first()
        )
        if existing and (existing.status or "") != "draft":
            st = "已提交" if existing.status == "submitted" else "已汇总"
            warnings.append({"name": p.name, "reason": f"本月已有同类型{st}记录"})
            continue
        conflict = _batch_overlap_check(db, pid, entries)
        if conflict:
            warnings.append({"name": p.name, "reason": conflict})
            continue
        if existing:
            detail = existing
            detail.settle_type = settle
        else:
            detail = OvertimeApplyDetail(
                apply_id=None, personnel_id=pid, accounting_month=month, apply_month=month,
                apply_user_id=current.id, work_type=work_type, status="draft",
                settle_type=settle, sort_order=0, create_time=datetime.now(),
            )
            db.add(detail)
            db.flush()
        count = db.query(func.count(OvertimeTimeEntry.id)).filter(
            OvertimeTimeEntry.detail_id == detail.id).scalar() or 0
        for j, te in enumerate(entries):
            wage = oc.D(te.get("daily_wage") or 0)
            if wage <= 0:
                wage = oc.D(p.daily_wage)
            f = oc.compute_entry_fields(
                work_type=te.get("work_type") or work_type,
                work_date=te.get("work_date"),
                start_time=oc.parse_dt(te.get("start_time")),
                end_time=oc.parse_dt(te.get("end_time")),
                multiplier=te.get("multiplier") if te.get("multiplier") not in (None, "") else
                    (3 if oc.is_exclusive_entry(te.get("is_full_day"), te.get("shift_type")) else 1.5),
                daily_wage=wage, settle_type=settle,
                is_full_day=bool(te.get("is_full_day")),
                shift_type=oc.normalize_shift(te.get("shift_type")),
                full_day_end=te.get("full_day_end") or "18:00",
            )
            if settle == oc.SETTLE_COMP:
                f["multiplier"] = oc.D(1)
                f["total_hours"] = f["raw_hours"]
                f["overtime_amount"] = oc.D(0)
            db.add(OvertimeTimeEntry(
                detail_id=detail.id, work_type=te.get("work_type") or work_type,
                work_date=oc.as_date(te.get("work_date")),
                start_time=f["start_time"], end_time=f["end_time"],
                raw_hours=f["raw_hours"], multiplier=f["multiplier"],
                total_hours=f["total_hours"], daily_wage=f["daily_wage"],
                overtime_amount=f["overtime_amount"],
                reason=te.get("reason") or "", work_order_no=te.get("work_order_no") or "",
                address=te.get("address") or "", accounting_month=month,
                sort_order=count + j, is_full_day=bool(te.get("is_full_day")),
                shift_type=oc.normalize_shift(te.get("shift_type")),
            ))
        db.flush()
        oc.update_detail_total_hours(db, detail.id)
        h = oc.monthly_total_hours(db, pid, month)
        if h > 36:
            hour_warnings.append({"name": p.name,
                                 "reason": f"本月累计{float(h):.1f}h已超36小时，请HR确认"})
        created.append(p.name)
    db.commit()
    skipped = len(warnings)
    msg = (f"已为{len(created)}人创建加班记录" +
           (f"，跳过{skipped}人" if skipped else "")) if created else "未创建任何记录"
    return {"success": True, "msg": msg, "created": len(created), "skipped": skipped,
            "warnings": warnings, "hourWarnings": hour_warnings}


# ================================================================ 待汇总记录

@router.get("/submitted-records")
def submitted_records(month: str = "", dept_id: int | None = None, work_type: str = "all",
                      page: int = 1, rows: int = 50,
                      db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    oc.ensure_perm(current, oc.PERM_APPLY, oc.PERM_VERIFY, oc.PERM_HR, oc.PERM_MANAGE)
    q = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.apply_id.is_(None),
        OvertimeApplyDetail.status == "submitted",
    )
    if month:
        q = q.filter(OvertimeApplyDetail.apply_month == month)
    if work_type and work_type != "all":
        q = q.filter(OvertimeApplyDetail.work_type == work_type)
    if dept_id:
        ids = oc.descendants(db, dept_id)
        pids = [p.id for p in db.query(OvertimePersonnel.id).filter(
            OvertimePersonnel.bb_bumen_id.in_(ids)).all()]
        q = q.filter(OvertimeApplyDetail.personnel_id.in_(pids or [-1]))
    if not oc.is_admin(current):
        q = q.filter(OvertimeApplyDetail.apply_user_id == current.id)
    total = q.count()
    items = q.order_by(OvertimeApplyDetail.create_time.desc(),
                       OvertimeApplyDetail.id.desc()).offset((page - 1) * rows).limit(rows).all()
    names, paths, pmap = oc.user_names(db), oc.dept_paths(db), oc.personnel_map(db)
    slots = oc.entry_time_slots(db, [d.id for d in items])
    totals = oc.entry_totals(db, [d.id for d in items])
    out = []
    for d in items:
        p = pmap.get(d.personnel_id)
        raw, _ = totals.get(d.id, (oc.D(0), oc.D(0)))
        out.append({
            "id": d.id,
            "apply_no": f"GR-{d.apply_month}-{d.id:04d}",
            "applyUserName": names.get(d.apply_user_id, ""),
            "personnelName": p.name if p else "",
            "deptName": paths.get(p.bb_bumen_id, "") if p else "",
            "work_type": d.work_type or "", "settle_type": d.settle_type or oc.SETTLE_PAY,
            "apply_month": d.apply_month or "", "total_hours": oc.fnum(d.total_hours),
            "rawHours": oc.fnum(raw), "timeSlots": slots.get(d.id, ""),
            "create_time": oc.fmt_dt(d.create_time),
        })
    return {"total": total, "rows": out}


# ================================================================ 申请单列表 / 详情

def _apply_amount(db, apply_id):
    """旧 GetApplyList.total_amount: 按人分组后用 ComputeOvertimeAmount 累加。"""
    rows = (
        db.query(OvertimeApplyDetail.personnel_id,
                 func.coalesce(func.sum(OvertimeTimeEntry.total_hours), 0),
                 func.max(OvertimeTimeEntry.daily_wage))
        .join(OvertimeTimeEntry, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeApplyDetail.apply_id == apply_id)
        .group_by(OvertimeApplyDetail.personnel_id).all()
    )
    pmap = oc.personnel_map(db)
    total = oc.D(0)
    for pid, hours, wage in rows:
        w = oc.D(wage or 0)
        if w <= 0 and pid in pmap:
            w = oc.D(pmap[pid].daily_wage)
        total += oc.compute_overtime_amount(hours, w)
    return total


def _apply_row(db, a, names, paths):
    raw = (
        db.query(func.coalesce(func.sum(OvertimeTimeEntry.raw_hours), 0))
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeApplyDetail.apply_id == a.id).scalar()
    )
    wages = (
        db.query(OvertimeTimeEntry.daily_wage)
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeApplyDetail.apply_id == a.id,
                OvertimeTimeEntry.daily_wage > 0)
        .distinct().all()
    )
    wage_txt = "、".join(str(oc.fnum(w[0])) for w in sorted(wages, key=lambda x: x[0] or 0))
    return {
        "id": a.id, "apply_no": a.apply_no or "", "record_type": a.record_type or "apply",
        "apply_month": a.apply_month or "", "work_type": a.work_type or "",
        "apply_user_id": a.apply_user_id, "apply_dept_id": a.apply_dept_id,
        "apply_date": oc.fmt_d(a.apply_date), "total_hours": oc.fnum(a.total_hours),
        "status": a.status or "", "raw_hours": oc.fnum(raw),
        "total_amount": oc.fnum(_apply_amount(db, a.id)),
        "days": oc.fnum((oc.D(a.total_hours) / oc.D(8)).quantize(oc.D("0.01"))),
        "daily_wage": wage_txt, "verify_time": oc.fmt_dt(a.verify_time),
        "verifyUserName": names.get(a.verify_user_id, ""),
        "settle_type": a.settle_type or oc.SETTLE_PAY,
        "remark": oc.strip_source_ids(a.remark), "create_time": oc.fmt_dt(a.create_time),
        "applyUserName": names.get(a.apply_user_id, ""),
        "deptName": paths.get(a.apply_dept_id, ""),
    }


@router.get("/applies")
def list_applies(status: str = "all", month: str = "", dept_id: int | None = None,
                 work_type: str = "all", max_depth: int | str | None = None,
                 page: int = 1, rows: int = 50,
                 db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """旧 GetApplyList,含 status='verify_mgmt' 的三处特判。"""
    q = db.query(OvertimeApply).filter(OvertimeApply.record_type == "apply")
    verify_mgmt = status == "verify_mgmt"
    if not oc.is_admin(current):
        if verify_mgmt:
            visible = oc.visible_ot_dept_ids(db, current)
            q = q.filter(OvertimeApply.apply_dept_id.in_(visible or [-1]))
        else:
            q = q.filter(OvertimeApply.apply_user_id == current.id)
    if status and status != "all":
        if verify_mgmt:
            q = q.filter(OvertimeApply.status.in_(["printed", "verified"]))
        else:
            q = q.filter(OvertimeApply.status == status)
    if dept_id and int(dept_id) > 0:
        ids = oc.resolve_dept_ids(db, dept_id, max_depth) if verify_mgmt else [int(dept_id)]
        q = q.filter(OvertimeApply.apply_dept_id.in_(ids or [-1]))
    if month:
        q = q.filter(OvertimeApply.apply_month == month)
    if work_type and work_type != "all":
        q = q.filter(OvertimeApply.work_type == work_type)
    total = q.count()
    items = q.order_by(OvertimeApply.apply_month.desc(), OvertimeApply.id.desc()).offset(
        (page - 1) * rows).limit(rows).all()
    names, paths = oc.user_names(db), oc.dept_paths(db)
    return {"total": total, "rows": [_apply_row(db, a, names, paths) for a in items]}


@router.get("/applies/{apply_id}")
def apply_info(apply_id: int, record_type: str = "apply",
               db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    """旧 GetApplyInfo: 返回 apply / details / timeEntries / approvals。"""
    from app.models.overtime import OvertimeApplyApproval, OvertimeApprovalLevel
    a = db.get(OvertimeApply, apply_id)
    if not a:
        return {"success": False, "msg": "记录不存在"}
    details = (
        db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == apply_id)
        .order_by(OvertimeApplyDetail.sort_order, OvertimeApplyDetail.id).all()
    )
    dids = [d.id for d in details]
    entries = (
        db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id.in_(dids or [-1]))
        .order_by(OvertimeTimeEntry.sort_order, OvertimeTimeEntry.work_date,
                  OvertimeTimeEntry.start_time).all()
    )
    pmap, dmap = oc.personnel_map(db), {d.id: d for d in details}
    approvals = (
        db.query(OvertimeApplyApproval).filter(OvertimeApplyApproval.apply_id == apply_id)
        .order_by(OvertimeApplyApproval.step_order, OvertimeApplyApproval.id).all()
    )
    level_names = {l.id: l.level_name for l in db.query(OvertimeApprovalLevel).all()}
    names, paths = oc.user_names(db), oc.dept_paths(db)
    return {
        "success": True,
        "apply": {
            **_apply_row(db, a, names, paths),
            "status_text": oc.STATUS_TEXT.get(a.status or "", a.status or ""),
        },
        "details": [
            {"id": d.id, "personnel_id": d.personnel_id,
             "accounting_month": d.accounting_month or "", "total_hours": oc.fnum(d.total_hours),
             "sort_order": d.sort_order, "personnelName": pmap[d.personnel_id].name if d.personnel_id in pmap else "",
             "personnelNo": pmap[d.personnel_id].employee_no if d.personnel_id in pmap else ""}
            for d in details
        ],
        "timeEntries": [
            {**e.to_dict(), "personnelId": dmap[e.detail_id].personnel_id if e.detail_id in dmap else None,
             "personnelName": pmap[dmap[e.detail_id].personnel_id].name
             if e.detail_id in dmap and dmap[e.detail_id].personnel_id in pmap else ""}
            for e in entries
        ],
        "approvals": [
            {**ap.to_dict(), "levelName": level_names.get(ap.approval_level_id, ""),
             "approverName": names.get(ap.approver_id, "")}
            for ap in approvals
        ],
    }


@router.post("/applies/from-personal")
def create_apply_from_personal(payload: dict = Body(...), db: Session = Depends(get_db),
                               current: User = Depends(get_current_user)):
    oc.ensure_perm(current, oc.PERM_APPLY, oc.PERM_VERIFY, oc.PERM_HR, oc.PERM_MANAGE)
    ids = [int(x) for x in (payload.get("personalRecordIds") or [])]
    head = payload.get("apply") or {}
    if not ids:
        raise HTTPException(400, "请至少选择一条个人加班记录")
    work_type = (head.get("work_type") or "").strip()
    if not work_type:
        raise HTTPException(400, "请选择加班类型")
    rows = db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.id.in_(ids)).all()
    if len(rows) != len(ids):
        raise HTTPException(400, "部分记录不存在或已被处理")
    types = {d.work_type for d in rows}
    if len(types) > 1:
        raise HTTPException(400, "选中记录的加班类型不一致，请分批创建")
    if work_type not in types:
        raise HTTPException(400, "申请单类型与选中记录类型不一致")
    settles = {d.settle_type or oc.SETTLE_PAY for d in rows}
    if len(settles) > 1:
        raise HTTPException(400, "选中记录的结算方式不一致（加班费/补休），请分批创建")
    if any(d.status != "submitted" or d.apply_id for d in rows):
        raise HTTPException(400, "部分记录不是已提交状态")
    month = (head.get("apply_month") or rows[0].apply_month or "").strip()
    pmap = oc.personnel_map(db)
    for d in rows:
        dup = (
            db.query(OvertimeApply.id)
            .join(OvertimeApplyDetail, OvertimeApplyDetail.apply_id == OvertimeApply.id)
            .filter(OvertimeApply.record_type == "apply",
                    OvertimeApplyDetail.personnel_id == d.personnel_id,
                    OvertimeApply.apply_month == month, OvertimeApply.work_type == work_type,
                    OvertimeApply.settle_type == (d.settle_type or oc.SETTLE_PAY)).first()
        )
        if dup:
            raise HTTPException(400, f"{pmap[d.personnel_id].name if d.personnel_id in pmap else ''} 在本月已有同类型同结算方式的申请单记录")
    dept_ids = [pmap[d.personnel_id].bb_bumen_id for d in rows if d.personnel_id in pmap]
    dept_id = oc.lca_dept(db, dept_ids) or oc.default_apply_dept_id(db, current)
    apply = OvertimeApply(
        apply_no=oc.generate_apply_no(db, month), record_type="apply", apply_month=month,
        work_type=work_type, apply_user_id=current.id, apply_dept_id=dept_id,
        apply_date=oc.parse_dt(head.get("apply_date"), datetime.now()),
        status="draft", total_hours=0, create_time=datetime.now(),
        settle_type=next(iter(settles)) if settles else oc.SETTLE_PAY,
        remark=oc.encode_source_ids(ids, head.get("remark") or ""),
    )
    db.add(apply)
    db.flush()
    # 同人多条合并到 id 最小的 master
    seen = {}
    sort_idx = 0
    for d in sorted(rows, key=lambda x: x.id):
        if d.personnel_id in seen:
            master = seen[d.personnel_id]
            db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == d.id).update(
                {OvertimeTimeEntry.detail_id: master.id}, synchronize_session=False)
            _delete_detail_only(db, d.id)
        else:
            d.apply_id = apply.id
            d.status = None
            d.sort_order = sort_idx
            sort_idx += 1
            seen[d.personnel_id] = d
    db.flush()
    oc.update_apply_total_hours(db, apply.id)
    db.commit()
    return {"success": True, "msg": f"已从{len(rows)}条个人明细生成申请单（{len(seen)}人）", "id": apply.id}


def _delete_detail_only(db, detail_id):
    db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.id == detail_id).delete()


@router.post("/applies")
def save_apply(payload: dict = Body(...), db: Session = Depends(get_db),
               current: User = Depends(get_current_user)):
    """旧 SaveApply(带完整明细的新建/编辑申请单,前端 DTO 值直落)。"""
    details = payload.get("details") or []
    month = (payload.get("apply_month") or "").strip()
    work_type = (payload.get("work_type") or "").strip()
    if not details:
        raise HTTPException(400, "请至少添加一个人员的加班明细")
    if not month:
        raise HTTPException(400, "请选择申请单所属月份")
    if not work_type:
        raise HTTPException(400, "请选择加班类型")
    for d in details:
        for te in d.get("timeEntries") or []:
            if te.get("work_type") and te["work_type"] != work_type:
                raise HTTPException(400, f"加班时段类型「{te['work_type']}」与申请单类型「{work_type}」不一致，请分不同申请单提交")
    adate = oc.parse_dt(payload.get("apply_date"), datetime.now())
    start, end = oc.month_date_range(month, db, "apply")
    if not (start <= adate <= end):
        raise HTTPException(400, "申请日期不在所属月份范围内")
    pmap = oc.personnel_map(db)
    dept_ids = {pmap[int(d.get("personnel_id") or 0)].bb_bumen_id
                for d in details if int(d.get("personnel_id") or 0) in pmap}
    if len(dept_ids) > 1:
        raise HTTPException(400, "同一申请单内的加班人必须属于同一部门")
    settle = payload.get("settle_type") or oc.SETTLE_PAY
    for d in details:
        pid = int(d.get("personnel_id") or 0)
        dup = (
            db.query(OvertimeApply.id)
            .join(OvertimeApplyDetail, OvertimeApplyDetail.apply_id == OvertimeApply.id)
            .filter(OvertimeApply.record_type == "apply",
                    OvertimeApplyDetail.personnel_id == pid,
                    OvertimeApply.apply_month == month, OvertimeApply.work_type == work_type,
                    OvertimeApply.settle_type == settle).first()
        )
        if dup and dup[0] != int(payload.get("id") or 0):
            raise HTTPException(400, f"{pmap[pid].name if pid in pmap else ''} 在本月已有同类型同结算方式的申请单记录")
    rid = int(payload.get("id") or 0)
    if rid:
        a = db.get(OvertimeApply, rid)
        if not a:
            raise HTTPException(400, "申请单不存在")
        if a.status != "draft":
            raise HTTPException(400, "只能编辑草稿状态的申请单（已打印或已核销不可编辑）")
        for d in db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == rid).all():
            _delete_detail(db, d.id)
        a.apply_month = month
        a.work_type = work_type
        a.apply_date = adate
        a.remark = oc.preserve_source_prefix(a.remark, payload.get("remark") or "")
        a.settle_type = settle
        a.update_time = datetime.now()
    else:
        a = OvertimeApply(
            apply_no=oc.generate_apply_no(db, month), record_type="apply",
            apply_month=month, work_type=work_type, apply_user_id=current.id,
            apply_dept_id=next(iter(dept_ids), None) if dept_ids else oc.default_apply_dept_id(db, current),
            apply_date=adate, status="draft", total_hours=0, create_time=datetime.now(),
            settle_type=settle, remark=payload.get("remark") or "",
        )
        db.add(a)
        db.flush()
        rid = a.id
    _insert_details_entries(db, rid, details, current, month, work_type, settle)
    oc.update_apply_total_hours(db, rid)
    db.commit()
    return {"success": True, "msg": "保存成功", "id": rid}


@router.post("/applies/header")
def save_apply_header(payload: dict = Body(...), db: Session = Depends(get_db),
                      current: User = Depends(get_current_user)):
    month = (payload.get("apply_month") or "").strip()
    work_type = (payload.get("work_type") or "").strip()
    if not month:
        raise HTTPException(400, "请选择所属月份")
    if not work_type:
        raise HTTPException(400, "请选择加班类别")
    rid = int(payload.get("id") or 0)
    if rid:
        a = db.get(OvertimeApply, rid)
        if not a:
            raise HTTPException(400, "申请单不存在")
        if a.status != "draft":
            raise HTTPException(400, "只能编辑草稿状态的申请单")
        a.apply_month = month
        a.work_type = work_type
        a.apply_date = oc.parse_dt(payload.get("apply_date"), datetime.now())
        a.remark = oc.preserve_source_prefix(a.remark, payload.get("remark") or "")
        a.update_time = datetime.now()
        no = a.apply_no
    else:
        a = OvertimeApply(
            apply_no=oc.generate_apply_no(db, month), record_type="apply",
            apply_month=month, work_type=work_type, apply_user_id=current.id,
            apply_dept_id=oc.default_apply_dept_id(db, current),
            apply_date=oc.parse_dt(payload.get("apply_date"), datetime.now()),
            status="draft", total_hours=0, remark=payload.get("remark") or "",
            create_time=datetime.now(), settle_type=oc.SETTLE_PAY,
        )
        db.add(a)
        db.flush()
        rid, no = a.id, a.apply_no
    db.commit()
    return {"success": True, "id": rid, "apply_no": no}


@router.post("/applies/{apply_id}/records")
def add_records_to_apply(apply_id: int, payload: dict = Body(...),
                         db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    ids = [int(x) for x in (payload.get("detailIds") or [])]
    if not ids:
        raise HTTPException(400, "请选择要添加的记录")
    a = db.get(OvertimeApply, apply_id)
    if not a:
        raise HTTPException(400, "申请单不存在")
    if a.status != "draft":
        raise HTTPException(400, "只能向草稿状态的申请单添加记录")
    rows = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.id.in_(ids), OvertimeApplyDetail.apply_id.is_(None),
        OvertimeApplyDetail.status == "submitted").all()
    if not rows:
        raise HTTPException(400, "未找到可添加的记录（需为已提交且未被其他申请单使用）")
    for d in rows:
        if d.work_type and d.work_type != a.work_type:
            raise HTTPException(400, f"记录类型「{d.work_type}」与申请单类型「{a.work_type}」不一致")
        if d.apply_month and d.apply_month != a.apply_month:
            raise HTTPException(400, f"记录月份「{d.apply_month}」与申请单月份「{a.apply_month}」不一致")
        if (d.settle_type or oc.SETTLE_PAY) != (a.settle_type or oc.SETTLE_PAY):
            raise HTTPException(400, f"记录结算方式「{d.settle_type}」与申请单结算方式「{a.settle_type}」不一致")
    existing = {d.personnel_id: d for d in db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.apply_id == apply_id).all()}
    merged = 0
    for d in sorted(rows, key=lambda x: x.id):
        if d.personnel_id in existing:
            target = existing[d.personnel_id]
            db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == d.id).update(
                {OvertimeTimeEntry.detail_id: target.id}, synchronize_session=False)
            _delete_detail_only(db, d.id)
            merged += 1
        else:
            d.apply_id = apply_id
            d.status = None
            d.sort_order = len(existing)
            existing[d.personnel_id] = d
    db.flush()
    oc.update_apply_total_hours(db, apply_id)
    db.commit()
    extra = f"（其中{merged}条已合并到已有人员）" if merged else ""
    return {"success": True, "msg": f"已添加{len(rows)}条记录到申请单{extra}"}


@router.post("/applies/{apply_id}/dept")
def update_apply_dept(apply_id: int, payload: dict = Body(...),
                      db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    dept_id = int(payload.get("deptId") or 0)
    if not dept_id:
        raise HTTPException(400, "请选择部门")
    a = db.get(OvertimeApply, apply_id)
    if not a:
        raise HTTPException(400, "申请单不存在")
    if a.status != "draft":
        raise HTTPException(400, "只能修改草稿状态的申请单部门")
    visible = oc.visible_ot_dept_ids(db, current)
    if visible is not None and dept_id not in visible:
        raise HTTPException(400, "所选部门不在您可见范围内")
    node = db.get(OvertimeDept, dept_id)
    if not node:
        raise HTTPException(400, "部门不存在")
    a.apply_dept_id = dept_id
    a.update_time = datetime.now()
    db.commit()
    return {"success": True, "msg": "部门已更新", "deptName": node.full_path}


@router.post("/applies/{apply_id}/remark")
def update_apply_remark(apply_id: int, payload: dict = Body(...),
                        db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    a = db.get(OvertimeApply, apply_id)
    if not a:
        raise HTTPException(400, "申请单不存在")
    if a.status != "draft":
        raise HTTPException(400, "只能修改草稿状态的申请单备注")
    a.remark = oc.preserve_source_prefix(a.remark, payload.get("remark") or "")
    a.update_time = datetime.now()
    db.commit()
    return {"success": True, "msg": "备注已更新"}


@router.post("/applies/{apply_id}/delete")
def delete_apply(apply_id: int, db: Session = Depends(get_db),
                 current: User = Depends(get_current_user)):
    a = db.get(OvertimeApply, apply_id)
    if not a:
        raise HTTPException(400, "记录不存在")
    if a.record_type == "personal":
        if a.status not in ("draft", "submitted"):
            raise HTTPException(400, "只能删除草稿或已提交的个人记录")
    elif a.status != "draft":
        raise HTTPException(400, "只能删除草稿状态的申请单（已打印或已核销不可删除）")
    # 旧 RestorePersonalRecords: 备注里的源明细回到待汇总池
    src = oc.decode_source_ids(a.remark)
    if src:
        db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.id.in_(src)).update(
            {OvertimeApplyDetail.apply_id: None, OvertimeApplyDetail.status: "submitted"},
            synchronize_session=False)
        remaining = db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == apply_id).all()
        for d in remaining:
            _delete_detail(db, d.id)
    else:
        for d in db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == apply_id).all():
            d.apply_id = None
            d.status = "submitted"
    db.query(OvertimeApply).filter(OvertimeApply.id == apply_id).delete()
    db.commit()
    return {"success": True, "msg": "删除成功"}


# ================================================================ 时段明细 CRUD

@router.get("/entries")
def entry_list(apply_id: int, record_type: str = "apply",
               db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    q = db.query(OvertimeTimeEntry, OvertimeApplyDetail).join(
        OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
    if record_type == "personal":
        q = q.filter(OvertimeApplyDetail.id == apply_id)
    else:
        q = q.filter(OvertimeApplyDetail.apply_id == apply_id)
    rows = q.order_by(OvertimeApplyDetail.sort_order, OvertimeTimeEntry.sort_order,
                      OvertimeTimeEntry.work_date).all()
    pmap = oc.personnel_map(db)
    out = []
    for e, d in rows:
        p = pmap.get(d.personnel_id)
        out.append({
            **e.to_dict(), "personnelId": d.personnel_id,
            "personnelName": p.name if p else "", "employeeNo": p.employee_no if p else "",
        })
    return {"total": len(out), "rows": out}


@router.post("/entries")
def save_entry(payload: dict = Body(...), db: Session = Depends(get_db),
               current: User = Depends(get_current_user)):
    """旧 SaveEntry: 单条录入(后端重算),支持 personal 独立明细 / apply 申请单。"""
    pid = int(payload.get("personnelId") or 0)
    person = db.get(OvertimePersonnel, pid)
    if not person:
        raise HTTPException(400, "人员不存在")
    record_type = payload.get("recordType") or "personal"
    apply_id = int(payload.get("applyId") or 0)
    entry_id = int(payload.get("entryId") or 0)
    month = (payload.get("applyMonth") or oc.current_month()).strip()
    work_type = (payload.get("workType") or "").strip()
    settle = payload.get("settleType") or oc.SETTLE_PAY
    is_full_day = bool(payload.get("isFullDay"))
    shift = oc.normalize_shift(payload.get("shiftLabel"))
    work_date = payload.get("workDate")
    st = oc.parse_dt(payload.get("startTime"))
    en = oc.parse_dt(payload.get("endTime"))
    if en <= st:
        en = en + timedelta(days=1)
    wage = oc.D(payload.get("dailyWage") or 0)
    f = oc.compute_entry_fields(
        work_type=work_type, work_date=work_date, start_time=st, end_time=en,
        multiplier=payload.get("multiplier") if payload.get("multiplier") not in (None, "") else 1.5,
        daily_wage=wage, settle_type=settle, is_full_day=is_full_day, shift_type=shift,
        full_day_end=payload.get("fullDayEnd") or "18:00",
    )
    if settle == oc.SETTLE_COMP:
        f["multiplier"] = oc.D(1)
        f["total_hours"] = f["raw_hours"]
        f["overtime_amount"] = oc.D(0)
    excl = oc.is_exclusive_entry(is_full_day, shift)
    overlap = oc.check_entry_overlap(db, pid, work_date, f["start_time"], f["end_time"],
                                     excl, entry_id, apply_id if record_type == "apply" else 0)
    if overlap:
        raise HTTPException(400, overlap)

    if record_type == "personal":
        detail = None
        if apply_id:  # 旧代码把 detailId 复用在 applyId 上
            detail = db.get(OvertimeApplyDetail, apply_id)
            if not detail:
                raise HTTPException(400, "记录不存在")
            if (detail.status or "draft") != "draft":
                raise HTTPException(400, "只能编辑草稿状态的记录")
        else:
            detail = (
                db.query(OvertimeApplyDetail)
                .filter(OvertimeApplyDetail.apply_id.is_(None),
                        OvertimeApplyDetail.personnel_id == pid,
                        OvertimeApplyDetail.apply_month == month,
                        OvertimeApplyDetail.work_type == work_type,
                        OvertimeApplyDetail.settle_type == settle,
                        OvertimeApplyDetail.status == "draft",
                        OvertimeApplyDetail.apply_user_id == current.id)
                .order_by(OvertimeApplyDetail.id).first()
            )
        if detail and detail.apply_month != month:
            dup = db.query(OvertimeApplyDetail.id).filter(
                OvertimeApplyDetail.apply_id.is_(None),
                OvertimeApplyDetail.personnel_id == pid,
                OvertimeApplyDetail.apply_month == month,
                OvertimeApplyDetail.work_type == work_type,
                OvertimeApplyDetail.settle_type == settle).first()
            if dup:
                raise HTTPException(400, "该人员在新月份已有同类型同结算方式加班记录，不能修改月份")
        if not detail:
            detail = OvertimeApplyDetail(
                apply_id=None, personnel_id=pid, accounting_month=month, apply_month=month,
                apply_user_id=current.id, work_type=work_type, status="draft",
                settle_type=settle, sort_order=0, create_time=datetime.now())
            db.add(detail)
            db.flush()
        detail.apply_month = month
        detail.accounting_month = month
        detail.personnel_id = pid
        detail.work_type = work_type
        detail.settle_type = settle
        db.query(OvertimeTimeEntry).filter(OvertimeTimeEntry.detail_id == detail.id).update(
            {OvertimeTimeEntry.accounting_month: month}, synchronize_session=False)
        target_detail_id = detail.id
        new_apply_no = ""
    else:
        a = db.get(OvertimeApply, apply_id) if apply_id else None
        if not a:
            a = OvertimeApply(
                apply_no=oc.generate_apply_no(db, month), record_type="apply",
                apply_month=month, work_type=work_type, apply_user_id=current.id,
                apply_dept_id=person.bb_bumen_id,
                apply_date=oc.parse_dt(payload.get("applyDate"), datetime.now()),
                status="draft", total_hours=0, create_time=datetime.now(),
                settle_type=settle, remark=payload.get("remark") or "")
            db.add(a)
            db.flush()
            apply_id = a.id
        else:
            if a.status != "draft":
                raise HTTPException(400, "只能编辑草稿状态的申请单")
            if work_type != a.work_type:
                raise HTTPException(400, "明细类别与申请单类别不一致")
            if settle != (a.settle_type or oc.SETTLE_PAY):
                raise HTTPException(400, "结算方式与申请单不一致，请分批创建申请单（补休/加班费）")
            if a.apply_month != month:
                a.apply_no = oc.generate_apply_no(db, month)
                a.apply_month = month
                a.update_time = datetime.now()
                db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == a.id).update(
                    {OvertimeApplyDetail.apply_month: month,
                     OvertimeApplyDetail.accounting_month: month}, synchronize_session=False)
        detail = (
            db.query(OvertimeApplyDetail)
            .filter(OvertimeApplyDetail.apply_id == a.id,
                    OvertimeApplyDetail.personnel_id == pid).first()
        )
        if not detail:
            detail = OvertimeApplyDetail(
                apply_id=a.id, personnel_id=pid, accounting_month=month, apply_month=month,
                apply_user_id=current.id, work_type=work_type, status=None,
                settle_type=settle, sort_order=0, create_time=datetime.now())
            db.add(detail)
            db.flush()
        target_detail_id = detail.id
        new_apply_no = a.apply_no

    if entry_id:
        e = db.get(OvertimeTimeEntry, entry_id)
        if not e:
            raise HTTPException(400, "明细不存在")
    else:
        e = OvertimeTimeEntry(detail_id=target_detail_id,
                              sort_order=db.query(func.count(OvertimeTimeEntry.id)).filter(
                                  OvertimeTimeEntry.detail_id == target_detail_id).scalar() or 0)
        db.add(e)
    e.detail_id = target_detail_id
    e.work_type = work_type
    e.work_date = oc.as_date(work_date)
    e.start_time = f["start_time"]
    e.end_time = f["end_time"]
    e.raw_hours = f["raw_hours"]
    e.multiplier = f["multiplier"]
    e.total_hours = f["total_hours"]
    e.daily_wage = f["daily_wage"]
    e.overtime_amount = f["overtime_amount"]
    e.reason = payload.get("reason") or ""
    e.work_order_no = payload.get("workOrderNo") or ""
    e.address = payload.get("address") or ""
    e.accounting_month = month
    e.is_full_day = is_full_day
    e.shift_type = shift
    db.flush()
    if record_type == "personal":
        oc.update_detail_total_hours(db, target_detail_id)
        apply_id_out = target_detail_id  # 前端刷新抽屉用 detailId
    else:
        oc.update_apply_total_hours(db, apply_id)
        apply_id_out = apply_id
    h = oc.monthly_total_hours(db, pid, month)
    msg, warn = "保存成功", ""
    if h > 36:
        warn = f"警告：{person.name}本月累计已超36小时({float(h):.1f}h)，已保存但请HR确认"
        msg = warn
    db.commit()
    return {"success": True, "msg": msg, "warning": warn, "newId": e.id,
            "applyNo": new_apply_no, "detailId": apply_id_out}


@router.post("/entries/{entry_id}/delete")
def delete_entry(entry_id: int, db: Session = Depends(get_db),
                 current: User = Depends(get_current_user)):
    e = db.get(OvertimeTimeEntry, entry_id)
    if not e:
        raise HTTPException(400, "明细不存在")
    d = db.get(OvertimeApplyDetail, e.detail_id)
    if not d:
        raise HTTPException(400, "明细所属记录不存在")
    if d.apply_id:
        a = db.get(OvertimeApply, d.apply_id)
        if not a or a.status != "draft":
            raise HTTPException(400, "只能编辑草稿状态的申请单")
    elif (d.status or "draft") != "draft":
        raise HTTPException(400, "只能编辑草稿状态的记录")
    db.delete(e)
    db.flush()
    left = db.query(func.count(OvertimeTimeEntry.id)).filter(
        OvertimeTimeEntry.detail_id == d.id).scalar()
    if not left:
        _delete_detail_only(db, d.id)
    elif d.apply_id:
        oc.update_apply_total_hours(db, d.apply_id)
    else:
        oc.update_detail_total_hours(db, d.id)
    db.commit()
    return {"success": True, "msg": "删除成功"}


# ================================================================ 校验接口

@router.get("/check-duplicate")
def check_duplicate(personnelId: int, month: str, workType: str,
                    recordType: str = "apply", settleType: str = oc.SETTLE_PAY,
                    db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    a = (
        db.query(OvertimeApply)
        .join(OvertimeApplyDetail, OvertimeApplyDetail.apply_id == OvertimeApply.id)
        .filter(OvertimeApply.record_type == recordType,
                OvertimeApplyDetail.personnel_id == personnelId,
                OvertimeApply.apply_month == month, OvertimeApply.work_type == workType,
                OvertimeApply.settle_type == (settleType or oc.SETTLE_PAY)).first()
    )
    return ({"exists": True, "id": a.id, "status": a.status, "apply_no": a.apply_no}
            if a else {"exists": False})


@router.post("/check-overlap")
def check_overlap(payload: dict = Body(...), db: Session = Depends(get_db),
                  current: User = Depends(get_current_user)):
    st, en, work_date = oc.require_time_range(payload.get("start"), payload.get("end"))
    msg = oc.check_entry_overlap(db, int(payload.get("personnelId") or 0), work_date,
                                 st, en, False, int(payload.get("excludeEntryId") or 0))
    return {"hasOverlap": bool(msg), "msg": msg or ""}


@router.post("/check-overlaps")
def check_overlaps(payload: dict = Body(...), db: Session = Depends(get_db),
                   current: User = Depends(get_current_user)):
    conflicts = []
    for item in payload.get("items") or []:
        st, en, work_date = oc.require_time_range(item.get("start"), item.get("end"))
        msg = oc.check_entry_overlap(db, int(item.get("personnelId") or 0), work_date,
                                     st, en, False, int(item.get("excludeEntryId") or 0))
        if msg:
            conflicts.append({"personnelId": item.get("personnelId"),
                              "start": st.strftime("%Y-%m-%d %H:%M"),
                              "end": en.strftime("%Y-%m-%d %H:%M"), "msg": msg})
    return {"hasConflict": bool(conflicts), "conflicts": conflicts}


@router.post("/check-monthly-hours")
def check_monthly(payload: dict = Body(...), db: Session = Depends(get_db),
                  current: User = Depends(get_current_user)):
    total = oc.monthly_total_hours(db, int(payload.get("personnelId") or 0),
                                   payload.get("accountingMonth") or oc.current_month())
    return {"total": oc.fnum(total), "exceeded": total > 36}


@router.post("/check-monthly-hours-batch")
def check_monthly_batch(payload: dict = Body(...), db: Session = Depends(get_db),
                        current: User = Depends(get_current_user)):
    month = payload.get("accountingMonth") or oc.current_month()
    out = []
    for pid in dict.fromkeys(payload.get("personnelIds") or []):
        h = oc.monthly_total_hours(db, int(pid), month)
        out.append({"personnelId": pid, "totalHours": oc.fnum(h), "exceeded": h > 36})
    return out
