"""加班申请审批 - 流程路由(审批流 / 核销 / 补休 / 汇总 / 打印 / Excel 导入导出)。

路径前缀同为 /api/overtime。写接口统一 {success, msg, ...},失败抛 400。
"""

from datetime import datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.overtime import (
    OvertimeApply,
    OvertimeApplyApproval,
    OvertimeApplyDetail,
    OvertimeApprovalLevel,
    OvertimeCompLeave,
    OvertimeDept,
    OvertimeMonthConfig,
    OvertimePersonnel,
    OvertimeTimeEntry,
)
from app.models.user import Department
from app.services import overtime_approval as engine
from app.services import overtime_common as oc
from app.services import overtime_excel as xls

router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel_response(wb, filename):
    return Response(
        content=xls.to_bytes(wb), media_type=XLSX_MEDIA,
        headers={"Content-Disposition": xls.content_disposition(filename)},
    )


def _ensure_verify(user):
    """旧 IsVerifier(): 核销三接口与补休登记统一校验。"""
    oc.ensure_perm(user, oc.PERM_VERIFY, oc.PERM_HR, oc.PERM_MANAGE, oc.PERM_APPLY)
    if not oc.is_verifier(user):
        raise HTTPException(403, "无核销权限")


# ================================================================ 审批开关 / 我的审批

@router.get("/approval-switch")
def get_approval_switch(db: Session = Depends(get_db),
                        current=Depends(get_current_user)):
    return {"enabled": oc.approval_enabled(db)}


@router.post("/approval-switch")
def set_approval_switch(payload: dict = Body(...), db: Session = Depends(get_db),
                        current=Depends(get_current_user)):
    if not oc.is_admin(current):
        raise HTTPException(403, "无权限，仅管理员可操作")
    if payload.get("enabled") is None:
        raise HTTPException(400, "缺少开关值 enabled")
    enabled = bool(payload.get("enabled"))
    row = db.query(OvertimeMonthConfig).filter(
        OvertimeMonthConfig.config_type == "approval_switch").first()
    if not row:
        row = OvertimeMonthConfig(config_type="approval_switch", start_day=0, end_day=0,
                                  description="审批流开关", is_active=enabled)
        db.add(row)
    else:
        row.is_active = enabled
    db.commit()
    return {"success": True, "msg": "审批流程已启用" if enabled else "已切回核销直通模式"}


@router.get("/my-approvals")
def my_approvals(page: int = 1, rows: int = 50, db: Session = Depends(get_db),
                 current=Depends(get_current_user)):
    """旧 GetMyPendingApprovals: 只按 approver_id + pending,不按 step 过滤。"""
    from .overtime import _apply_row
    q = db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.approver_id == current.id,
        OvertimeApplyApproval.status == "pending")
    total = q.count()
    items = q.order_by(OvertimeApplyApproval.id.desc()).offset(
        (page - 1) * rows).limit(rows).all()
    levels = {l.id: l.level_name for l in db.query(OvertimeApprovalLevel).all()}
    names, paths = oc.user_names(db), oc.dept_paths(db)
    out = []
    for ap in items:
        a = db.get(OvertimeApply, ap.apply_id)
        if not a:
            continue
        row = _apply_row(db, a, names, paths)
        row.update({
            "approval_id": ap.id, "apply_id": a.id, "step_order": ap.step_order,
            "levelName": levels.get(ap.approval_level_id, ""),
        })
        out.append(row)
    return {"total": total, "rows": out}


@router.post("/approval/submit")
def submit_for_approval(payload: dict = Body(...), db: Session = Depends(get_db),
                        current=Depends(get_current_user)):
    try:
        n = engine.submit_apply(db, int(payload.get("id") or 0))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"success": True, "msg": f"已提交审批，共 {n} 个审批节点"}


@router.post("/approval/approve")
def approve_apply(payload: dict = Body(...), db: Session = Depends(get_db),
                  current=Depends(get_current_user)):
    try:
        engine.approve_node(db, int(payload.get("approvalId") or 0), current.id,
                            bool(payload.get("approved", True)), payload.get("comment") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"success": True, "msg": "已通过" if payload.get("approved", True) else "已驳回"}


@router.post("/approval/reject")
def reject_apply(payload: dict = Body(...), db: Session = Depends(get_db),
                 current=Depends(get_current_user)):
    try:
        engine.approve_node(db, int(payload.get("approvalId") or 0), current.id,
                            False, payload.get("comment") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"success": True, "msg": "已驳回"}


@router.post("/approval/resubmit")
def resubmit_apply(payload: dict = Body(...), db: Session = Depends(get_db),
                   current=Depends(get_current_user)):
    try:
        engine.resubmit_apply(db, int(payload.get("id") or 0))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"success": True, "msg": "已重新提交为草稿"}


# ================================================================ 核销

@router.post("/verify/batch")
def batch_verify(payload: dict = Body(...), db: Session = Depends(get_db),
                 current=Depends(get_current_user)):
    _ensure_verify(current)
    ids = [int(x) for x in (payload.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "请选择要核销的申请单")
    rows = db.query(OvertimeApply).filter(
        OvertimeApply.id.in_(ids), OvertimeApply.status == "printed").all()
    if not rows:
        raise HTTPException(400, "未找到可核销的申请单（仅已打印状态可核销）")
    for a in rows:
        a.status = "verified"
        a.verify_time = datetime.now()
        a.verify_user_id = current.id
        a.update_time = datetime.now()
    db.commit()
    return {"success": True, "msg": f"已核销{len(rows)}张申请单"}


@router.post("/verify/unverify")
def unverify(payload: dict = Body(...), db: Session = Depends(get_db),
             current=Depends(get_current_user)):
    _ensure_verify(current)
    a = db.query(OvertimeApply).filter(
        OvertimeApply.id == int(payload.get("id") or 0),
        OvertimeApply.status == "verified").first()
    if not a:
        raise HTTPException(400, "未找到已核销的申请单")
    a.status = "printed"
    a.verify_time = None
    a.verify_user_id = None
    a.update_time = datetime.now()
    db.commit()
    return {"success": True, "msg": "已反核销"}


@router.post("/verify/revert")
def revert_to_draft(payload: dict = Body(...), db: Session = Depends(get_db),
                    current=Depends(get_current_user)):
    _ensure_verify(current)
    a = db.query(OvertimeApply).filter(
        OvertimeApply.id == int(payload.get("id") or 0),
        OvertimeApply.status == "printed").first()
    if not a:
        raise HTTPException(400, "未找到已打印的申请单")
    db.query(OvertimeApplyDetail).filter(OvertimeApplyDetail.apply_id == a.id).update(
        {OvertimeApplyDetail.apply_id: None, OvertimeApplyDetail.status: "submitted"},
        synchronize_session=False)
    db.query(OvertimeApply).filter(OvertimeApply.id == a.id).delete()
    db.commit()
    return {"success": True, "msg": "已退回，人员记录已回到待汇总池，申请单已自动销毁"}


# ================================================================ 补休

@router.get("/comp-leave/balance")
def comp_balance(personnelId: int, db: Session = Depends(get_db),
                 current=Depends(get_current_user)):
    return {"success": True, "balance": oc.fnum(oc.comp_leave_balance(db, personnelId))}


@router.get("/comp-leave/list")
def comp_list(personnelId: int, db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    rows = db.query(OvertimeCompLeave).filter(
        OvertimeCompLeave.personnel_id == personnelId).order_by(
        OvertimeCompLeave.leave_date.desc()).all()
    return {"total": len(rows), "rows": [x.to_dict() for x in rows]}


@router.post("/comp-leave/save")
def comp_save(payload: dict = Body(...), db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    _ensure_verify(current)
    pid = int(payload.get("personnelId") or 0)
    hours = oc.D(payload.get("hours") or 0)
    if pid <= 0:
        raise HTTPException(400, "请选择人员")
    if hours <= 0:
        raise HTTPException(400, "补休时长必须大于0")
    balance = oc.comp_leave_balance(db, pid)
    if hours > balance:
        raise HTTPException(400, f"补休时长不足：本次登记{float(hours):.1f}h，剩余余额仅{float(balance):.1f}h")
    leave_date = oc.as_date(payload.get("leaveDate")) if payload.get("leaveDate") else datetime.now().date()
    if isinstance(leave_date, datetime):
        leave_date = leave_date.date()
    if leave_date > (datetime.now() + timedelta(days=365)).date():
        raise HTTPException(400, "补休日期不能超过一年")
    row = OvertimeCompLeave(
        personnel_id=pid, leave_date=leave_date,
        start_time=oc.parse_dt(payload.get("startTime")),
        end_time=oc.parse_dt(payload.get("endTime")),
        hours=oc.dec2(hours), leave_type=payload.get("leaveType") or "全天",
        reason=payload.get("reason") or "", create_user_id=current.id,
        create_time=datetime.now())
    db.add(row)
    db.commit()
    return {"success": True, "msg": "登记成功", "id": row.id,
            "balance": oc.fnum(oc.comp_leave_balance(db, pid))}


@router.post("/comp-leave/delete")
def comp_delete(payload: dict = Body(...), db: Session = Depends(get_db),
                current=Depends(get_current_user)):
    _ensure_verify(current)
    row = db.get(OvertimeCompLeave, int(payload.get("id") or 0))
    if not row:
        raise HTTPException(400, "记录不存在")
    db.delete(row)
    db.commit()
    return {"success": True, "msg": "删除成功"}


# ================================================================ 加班汇总

@router.get("/summary")
def summary(month: str = "", dept_id: int | None = None, keyword: str = "",
            work_type: str = "all", status: str = "all", max_depth: int | str | None = None,
            sort_by_raw: bool = False, page: int = 1, rows: int = 50,
            db: Session = Depends(get_db), current=Depends(get_current_user)):
    """旧 GetOvertimeSummary: 按 人员+类别+结算 分组,footer 对全量结果求和。"""
    q = (db.query(OvertimeTimeEntry, OvertimeApplyDetail, OvertimePersonnel, OvertimeApply)
         .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
         .join(OvertimePersonnel, OvertimeApplyDetail.personnel_id == OvertimePersonnel.id)
         .outerjoin(OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id))
    root = dept_id or (oc.mirror_by_sys(db, oc.user_primary_sys_dept(current)).id
                       if oc.mirror_by_sys(db, oc.user_primary_sys_dept(current)) else None)
    if root and not oc.is_admin(current):
        ids = oc.resolve_dept_ids(db, root, max_depth)
        q = q.filter(OvertimePersonnel.bb_bumen_id.in_(ids or [-1]))
    q = q.filter(or_(OvertimeApplyDetail.status.is_(None),
                     OvertimeApplyDetail.status != "draft"))
    if month and month != "all":
        if len(month) == 4:
            q = q.filter(OvertimeTimeEntry.accounting_month.like(f"{month}%"))
        else:
            q = q.filter(OvertimeTimeEntry.accounting_month == month)
    if work_type and work_type != "all":
        q = q.filter(OvertimeTimeEntry.work_type == work_type)
    if status and status != "all":
        if status in ("submitted", "grouped"):
            q = q.filter(OvertimeApplyDetail.status == status)
        else:
            q = q.filter(OvertimeApply.status == status)
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.filter(or_(OvertimePersonnel.name.like(kw),
                         OvertimePersonnel.employee_no.like(kw),
                         OvertimeTimeEntry.reason.like(kw)))
    data = q.all()
    paths, names = oc.dept_paths(db), oc.user_names(db)
    groups = {}
    for e, d, p, a in data:
        settle = (a.settle_type if a and a.settle_type else d.settle_type) or oc.SETTLE_PAY
        key = (p.id, p.name or "", p.employee_no or "",
               paths.get(p.bb_bumen_id, ""), e.work_type or "", settle)
        g = groups.setdefault(key, {"raw": oc.D(0), "total": oc.D(0), "count": 0,
                                    "reasons": [], "wage": oc.D(p.daily_wage or 0),
                                    "entry_wage": oc.D(0), "status": "", "user_id": d.apply_user_id})
        g["raw"] += oc.D(e.raw_hours)
        g["total"] += oc.D(e.total_hours)
        g["count"] += 1
        g["entry_wage"] = max(g["entry_wage"], oc.D(e.daily_wage or 0))
        if e.start_time and e.reason and len(g["reasons"]) < 10:
            t = f"{e.start_time.strftime('%Y-%m-%d %H:%M')}-{e.end_time.strftime('%H:%M') if e.end_time else ''} {e.reason}"
            if t not in g["reasons"]:
                g["reasons"].append(t)
        g["status"] = oc.summary_status(d.status, a.status if a else None)
    person_raw, person_amount = {}, {}
    for key, g in groups.items():
        person_raw[key[0]] = person_raw.get(key[0], oc.D(0)) + g["raw"]
        if key[5] != oc.SETTLE_COMP:
            person_amount[key[0]] = person_amount.get(key[0], oc.D(0)) + oc.compute_overtime_amount(
                g["total"], g["wage"] if g["wage"] > 0 else g["entry_wage"])
    out = []
    for key, g in groups.items():
        pid, pname, emp_no, dept_name, wt, settle = key
        wage = g["wage"] if g["wage"] > 0 else g["entry_wage"]
        out.append({
            "personnelId": pid, "personnelName": pname, "employeeNo": emp_no,
            "deptName": dept_name, "workType": wt, "settleType": settle,
            "rawHours": oc.fnum(g["raw"]), "totalHours": oc.fnum(g["total"]),
            "totalAmount": oc.fnum(oc.compute_overtime_amount(g["total"], wage)) if settle != oc.SETTLE_COMP else 0,
            "personRawTotal": oc.fnum(person_raw.get(pid, 0)),
            "personAmountTotal": oc.fnum(person_amount.get(pid, 0)),
            "entryCount": g["count"], "reasons": "；".join(g["reasons"]),
            "applyUserName": names.get(g["user_id"], ""), "status": g["status"],
        })
    if sort_by_raw:
        out.sort(key=lambda x: (-x["personRawTotal"], x["deptName"], x["personnelName"], x["workType"]))
    else:
        out.sort(key=lambda x: (x["deptName"], x["personnelName"], x["workType"]))
    over36 = len([pid for pid, v in person_raw.items() if v > 36])
    footer = [{
        "personnelName": "合计", "rawHours": oc.fnum(sum(oc.D(x["rawHours"]) for x in out)),
        "totalHours": oc.fnum(sum(oc.D(x["totalHours"]) for x in out)),
        "totalAmount": oc.fnum(sum(oc.D(x["totalAmount"]) for x in out)),
        "entryCount": sum(x["entryCount"] for x in out), "over36Count": over36,
    }]
    return {"total": len(out), "rows": out[(page - 1) * rows:page * rows], "footer": footer}


@router.get("/summary/detail")
def summary_detail(personnelId: int, work_type: str = "", month: str = "",
                   status: str = "", keyword: str = "",
                   db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = (db.query(OvertimeTimeEntry, OvertimeApplyDetail, OvertimeApply)
         .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
         .outerjoin(OvertimeApply, OvertimeApplyDetail.apply_id == OvertimeApply.id)
         .filter(OvertimeApplyDetail.personnel_id == personnelId)
         .filter(or_(OvertimeApplyDetail.status.is_(None),
                     OvertimeApplyDetail.status != "draft")))
    if work_type == "all" or not work_type:
        pass
    else:
        q = q.filter(OvertimeTimeEntry.work_type == work_type)
    if month and month != "all":
        if len(month) == 4:
            q = q.filter(OvertimeTimeEntry.accounting_month.like(f"{month}%"))
        else:
            q = q.filter(OvertimeTimeEntry.accounting_month == month)
    if status and status != "all":
        if status in ("submitted", "grouped"):
            q = q.filter(OvertimeApplyDetail.status == status)
        else:
            q = q.filter(OvertimeApply.status == status)
    if keyword.strip():
        q = q.filter(OvertimeTimeEntry.reason.like(f"%{keyword.strip()}%"))
    rows = q.order_by(OvertimeTimeEntry.work_date, OvertimeTimeEntry.start_time).all()
    out = []
    for e, d, a in rows:
        out.append({
            "entryId": e.id, "workType": e.work_type or "", "workDate": oc.fmt_d(e.work_date),
            "startTime": e.start_time.strftime("%Y-%m-%d %H:%M") if e.start_time else "",
            "endTime": e.end_time.strftime("%Y-%m-%d %H:%M") if e.end_time else "",
            "rawHours": oc.fnum(e.raw_hours), "totalHours": oc.fnum(e.total_hours),
            "amount": oc.fnum(e.overtime_amount), "reason": e.reason or "",
            "work_order_no": e.work_order_no or "", "address": e.address or "",
            "multiplier": oc.fnum(e.multiplier), "daily_wage": oc.fnum(e.daily_wage),
            "status": oc.summary_status(d.status, a.status if a else None),
        })
    return {"rows": out}


# ================================================================ 打印数据(有副作用)

@router.get("/print-data")
def print_data(id: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    a = db.get(OvertimeApply, id)
    if not a:
        return {"success": False, "msg": "记录不存在"}
    has_detail = db.query(OvertimeApplyDetail.id).filter(
        OvertimeApplyDetail.apply_id == id).first()
    if not has_detail:
        return {"success": False, "msg": "该申请单未添加任何加班记录，无法查看打印"}
    if oc.approval_enabled(db) and a.status not in ("approved", "printed"):
        return {"success": False, "msg": "已启用审批流程，仅审批通过后可打印"}
    if a.status in ("draft", "approved"):
        a.status = "printed"
        a.update_time = datetime.now()
        db.commit()
    from .overtime import _apply_row
    names, paths = oc.user_names(db), oc.dept_paths(db)
    details = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.apply_id == id).order_by(
        OvertimeApplyDetail.sort_order, OvertimeApplyDetail.id).all()
    dids = [d.id for d in details]
    entries = db.query(OvertimeTimeEntry).filter(
        OvertimeTimeEntry.detail_id.in_(dids or [-1])).order_by(
        OvertimeTimeEntry.work_date, OvertimeTimeEntry.start_time).all()
    pmap, dmap = oc.personnel_map(db), {d.id: d for d in details}
    detail_rows = []
    for d in details:
        p = pmap.get(d.personnel_id)
        es = [e for e in entries if e.detail_id == d.id]
        raw = sum(oc.D(e.raw_hours) for e in es)
        total = sum(oc.D(e.total_hours) for e in es)
        wage = oc.D(130) if a.work_type == oc.TS_WORK_TYPE else (
            oc.D(es[0].daily_wage) if es and es[0].daily_wage else oc.D(p.daily_wage if p else 0))
        detail_rows.append({
            "personnelName": p.name if p else "", "employeeNo": p.employee_no if p else "",
            "accounting_month": d.accounting_month or "",
            "daily_wage": oc.fnum(wage), "rawHours": oc.fnum(raw), "total_hours": oc.fnum(total),
            "total_amount": oc.fnum(sum(oc.D(e.overtime_amount) for e in es)),
            "days": None if a.work_type == oc.TS_WORK_TYPE else oc.fnum((total / oc.D(8)).quantize(oc.D("0.01"))),
            "total_multiplier": oc.fnum(sum(oc.D(e.multiplier) for e in es)),
        })
    entry_rows = []
    for e in entries:
        p = pmap.get(dmap[e.detail_id].personnel_id) if e.detail_id in dmap else None
        entry_rows.append({
            **e.to_dict(), "personnelName": p.name if p else "",
            "start_time": e.start_time.strftime("%Y-%m-%d %H:%M") if e.start_time else "",
            "end_time": e.end_time.strftime("%Y-%m-%d %H:%M") if e.end_time else "",
        })
    approvals = db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.apply_id == id).order_by(
        OvertimeApplyApproval.step_order).all()
    levels = {l.id: l.level_name for l in db.query(OvertimeApprovalLevel).all()}
    return {
        "success": True,
        "apply": {**_apply_row(db, a, names, paths),
                  "leaderLabel": _leader_label(db, current)},
        "details": detail_rows, "timeEntries": entry_rows,
        "approvals": [
            {"step": ap.step_order, "levelName": levels.get(ap.approval_level_id, ""),
             "approverName": names.get(ap.approver_id, ""), "status": ap.status,
             "comment": ap.comment or "",
             "approve_time": ap.approve_time.strftime("%Y-%m-%d %H:%M") if ap.approve_time else ""}
            for ap in approvals
        ],
    }


def _leader_label(db, user) -> str:
    sys_id = oc.user_primary_sys_dept(user)
    d = db.get(Department, sys_id) if sys_id else None
    name = d.name if d else ""
    if "营业所" in name:
        return "营业所领导"
    if "事业部" in name:
        return "事业部领导"
    return "领导"


# ================================================================ Excel 导出 / 导入

@router.get("/export/apply")
def export_apply(id: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    try:
        wb, name = xls.apply_workbook(db, id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _excel_response(wb, name)


@router.get("/export/records")
def export_records(month: str = "", keyword: str = "", ids: str = "",
                   db: Session = Depends(get_db), current=Depends(get_current_user)):
    if not oc.is_admin(current):
        raise HTTPException(403, "无权限导出加班记录")
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()] or None
    wb, name = xls.records_workbook(db, month, keyword, id_list)
    return _excel_response(wb, name)


@router.get("/export/qx")
def export_qx(month: str = "", remark: str = "", db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    wb, name = xls.qx_workbook(db, month or oc.current_month(), remark)
    return _excel_response(wb, name)


@router.get("/import/template")
def download_template(names: str = "", employeeNos: str = "",
                      db: Session = Depends(get_db), current=Depends(get_current_user)):
    wb, name = xls.template_workbook(names, employeeNos)
    return _excel_response(wb, name)


@router.post("/import/personal")
async def import_personal(file: UploadFile = File(...), db: Session = Depends(get_db),
                          current=Depends(get_current_user)):
    raw = await file.read()
    try:
        items, errors = xls.read_import_rows(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    imported = 0
    for r in items:
        norm, err = xls.validate_import_row(db, r)
        if err:
            errors.append({"Row": r["row"], "Name": r["name"], "Msg": err})
            continue
        st, en = norm["start_time"], norm["end_time"]
        msg = oc.check_entry_overlap(db, norm["personnel_id"], norm["work_date"],
                                     st, en, bool(norm["shift_type"]))
        if msg:
            errors.append({"Row": r["row"], "Name": r["name"], "Msg": msg})
            continue
        detail = (db.query(OvertimeApplyDetail)
                  .filter(OvertimeApplyDetail.apply_id.is_(None),
                          OvertimeApplyDetail.personnel_id == norm["personnel_id"],
                          OvertimeApplyDetail.apply_month == norm["apply_month"],
                          OvertimeApplyDetail.work_type == norm["work_type"],
                          OvertimeApplyDetail.settle_type == norm["settle_type"],
                          OvertimeApplyDetail.status == "draft")
                  .order_by(OvertimeApplyDetail.id).first())
        if not detail:
            detail = OvertimeApplyDetail(
                apply_id=None, personnel_id=norm["personnel_id"],
                accounting_month=norm["apply_month"], apply_month=norm["apply_month"],
                apply_user_id=current.id, work_type=norm["work_type"], status="draft",
                settle_type=norm["settle_type"], sort_order=0, create_time=datetime.now())
            db.add(detail)
            db.flush()
        cnt = db.query(func.count(OvertimeTimeEntry.id)).filter(
            OvertimeTimeEntry.detail_id == detail.id).scalar() or 0
        db.add(OvertimeTimeEntry(
            detail_id=detail.id, work_type=norm["work_type"],
            work_date=norm["work_date"], start_time=st, end_time=en,
            raw_hours=norm["raw_hours"], multiplier=norm["multiplier"],
            total_hours=norm["total_hours"], daily_wage=norm["daily_wage"],
            overtime_amount=norm["overtime_amount"], reason=norm["reason"],
            work_order_no=norm["work_order_no"], address=norm["address"],
            accounting_month=norm["apply_month"], sort_order=cnt,
            is_full_day=False, shift_type=norm["shift_type"]))
        db.flush()
        oc.update_detail_total_hours(db, detail.id)
        imported += 1
    db.commit()
    return {"Success": True,
            "Msg": f"导入完成：成功 {imported} 条，跳过 {len(errors)} 条",
            "Imported": imported, "Skipped": len(errors), "Errors": errors}


@router.post("/import/personnel")
async def import_personnel(file: UploadFile = File(...), db: Session = Depends(get_db),
                           current=Depends(get_current_user)):
    from app.models.user import User
    raw = await file.read()
    try:
        items = xls.read_personnel_rows(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    added = filled = skipped = 0
    dept_notes = []
    users = {u.username.lower(): u for u in db.query(User).all()}
    depts = db.query(OvertimeDept).all()
    sys_names = {d.id: d.name for d in db.query(Department).all()}
    for r in items:
        node = next((d for d in depts if d.name == r["dept"]), None)
        if not node:
            sys_id = next((k for k, v in sys_names.items() if v == r["dept"]), None)
            if sys_id:
                root = next((d for d in depts if d.parent_id is None), None)
                if root:
                    node = OvertimeDept(name=r["dept"], parent_id=root.id, sys_bumen_id=sys_id,
                                        full_path=f"{root.full_path}/{r['dept']}",
                                        level=(root.level or 1) + 1, sort_order=0,
                                        is_active=True, create_time=datetime.now())
                    db.add(node)
                    db.flush()
                    depts.append(node)
            if not node:
                skipped += 1
                dept_notes.append(f'部门"{r["dept"]}"在系统中不存在')
                continue
        uid = users.get(r["name"].lower())
        existing = db.query(OvertimePersonnel).filter(
            OvertimePersonnel.name == r["name"],
            OvertimePersonnel.bb_bumen_id == node.id).first()
        if r["employee_no"] and db.query(OvertimePersonnel.id).filter(
                OvertimePersonnel.employee_no == r["employee_no"]).first():
            skipped += 1
            continue
        if existing and not existing.employee_no and r["employee_no"]:
            existing.employee_no = r["employee_no"]
            existing.bb_user_id = uid.id if uid else None
            filled += 1
        elif not existing:
            db.add(OvertimePersonnel(
                name=r["name"], employee_no=r["employee_no"],
                bb_user_id=uid.id if uid else None, bb_bumen_id=node.id,
                parent_id=None, daily_wage=0, is_active=True, create_time=datetime.now()))
            added += 1
        else:
            skipped += 1
    db.commit()
    tail = f"（部门：{'；'.join(dict.fromkeys(dept_notes))}）" if dept_notes else ""
    return {"Success": True,
            "Msg": f"导入完成：新增 {added} 条，补填编号 {filled} 条，跳过 {skipped} 条{tail}",
            "Imported": added, "Skipped": skipped}


@router.post("/summary/upload")
async def upload_summary(file: UploadFile = File(...), month: str = "",
                         workType: str = "", db: Session = Depends(get_db),
                         current=Depends(get_current_user)):
    if not month:
        raise HTTPException(400, "请先选择月份")
    if not workType or workType == "all":
        raise HTTPException(400, "请先选择具体加班类型")
    raw = await file.read()
    wb, matched, unmatched = xls.match_summary_workbook(raw, db, month, workType)
    name = f"加班汇总_{month}_{workType}_{xls._stamp()}.xlsx"
    return Response(
        content=xls.to_bytes(wb), media_type=XLSX_MEDIA,
        headers={"Content-Disposition": xls.content_disposition(name),
                 "X-Matched-Count": str(matched), "X-Unmatched-Count": str(unmatched)},
    )
