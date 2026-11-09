"""审批引擎(1:1 复刻旧 whl.BLL/OvertimeApprovalEngine.cs)。

要点(与直觉不同,勿擅自"修正"):
- SubmitApply 一次性为所有层级的所有审批人生成 pending 记录,不存在"逐级激活"。
- approval_mode 只在 Approve 时决定本步骤是否完成。
- 只有最高 step_order 完成才把申请单置 approved;printed 由打印接口置。
- 驳回:申请单 rejected,其余 pending 节点 -> skipped;重提:物理删全部审批记录 + 回 draft。
- field/hq 路由:旧系统用 bb_bumen.C_parentId==1 判基层营业所。新系统把该判定
  固化在 overtime_dept.is_field(迁移脚本按旧 bb_bumen._parentId 计算),避免三套 id 空间混用。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.overtime import (
    OvertimeApply,
    OvertimeApplyApproval,
    OvertimeApplyDetail,
    OvertimeApprovalLevel,
    OvertimeApprover,
    OvertimeDept,
    OvertimePersonnel,
    OvertimeTimeEntry,
)
from app.models.user import Department
from app.services import overtime_common as oc


def _target_department(db, applicant_dept, offset: int, mapped_id):
    """旧 ResolveTargetDept: -1 指定部门 / 0 本级 / >=1 沿父链上溯 N 级。"""
    if offset == -1:
        if mapped_id:
            return db.get(Department, mapped_id)
        return applicant_dept
    dept = applicant_dept
    for _ in range(max(0, offset)):
        if dept is None or not dept.parent_id:
            break
        dept = db.get(Department, dept.parent_id)
    return dept or applicant_dept


def _find_approvers(db, level_id, target_dept_id, work_type):
    """旧 FindApprovers 五级优先级:部门+类别 > 仅部门 > 仅类别 > 全局 > 该层全部。"""
    rows = db.query(OvertimeApprover).filter(
        OvertimeApprover.approval_level_id == level_id,
        OvertimeApprover.is_active.is_(True),
    ).all()
    if target_dept_id or work_type:
        scoped = [a for a in rows
                  if (not target_dept_id or a.scope_bumen_id == target_dept_id)
                  and (not work_type or a.work_type == work_type)]
        if scoped:
            return scoped
        if target_dept_id:
            dept_only = [a for a in rows
                         if a.scope_bumen_id == target_dept_id and not a.work_type]
            if dept_only:
                return dept_only
        if work_type:
            type_only = [a for a in rows
                         if not a.scope_bumen_id and a.work_type == work_type]
            if type_only:
                return type_only
        glob = [a for a in rows if not a.scope_bumen_id and not a.work_type]
        if glob:
            return glob
    return rows


def _personnel_chain(db, personnel_id):
    """沿 personnel.parent_id 上溯,只收集绑定了系统用户(>0)的上级。"""
    chain, cur, guard = [], db.get(OvertimePersonnel, personnel_id), 0
    while cur and cur.parent_id and guard < 50:
        cur = db.get(OvertimePersonnel, cur.parent_id)
        guard += 1
        if cur and cur.bb_user_id and cur.bb_user_id > 0:
            chain.append(cur.bb_user_id)
    return chain


def submit_apply(db: Session, apply_id: int):
    """旧 Engine.SubmitApply: 允许 draft/rejected;先查时段重叠,再一次性生成审批节点。"""
    apply = db.get(OvertimeApply, apply_id)
    if not apply:
        raise ValueError("申请单不存在")
    if apply.status not in ("draft", "rejected"):
        raise ValueError("当前状态不可提交")
    entries = (
        db.query(OvertimeTimeEntry, OvertimeApplyDetail)
        .join(OvertimeApplyDetail, OvertimeTimeEntry.detail_id == OvertimeApplyDetail.id)
        .filter(OvertimeApplyDetail.apply_id == apply_id).all()
    )
    for e, d in entries:
        msg = oc.check_entry_overlap(db, d.personnel_id, e.work_date,
                                     e.start_time, e.end_time,
                                     oc.is_exclusive_entry(e.is_full_day, e.shift_type),
                                     e.id, apply_id)
        if msg:
            raise ValueError(msg)
    levels = (
        db.query(OvertimeApprovalLevel)
        .filter(OvertimeApprovalLevel.is_active.is_(True))
        .order_by(OvertimeApprovalLevel.level_order, OvertimeApprovalLevel.id).all()
    )
    if not levels:
        raise ValueError("未配置审批层级")
    ot_dept = db.get(OvertimeDept, apply.apply_dept_id) if apply.apply_dept_id else None
    applicant_dept = db.get(Department, ot_dept.sys_bumen_id) if ot_dept and ot_dept.sys_bumen_id else None
    route = "field" if (ot_dept and ot_dept.is_field) else "hq"
    levels = [l for l in levels if l.route_type in ("all", route)]
    if not levels:
        raise ValueError(f"未配置适用于「{'基层营业所' if route == 'field' else '本部'}」的审批层级")
    field_levels = [l for l in levels if l.route_type == "field"]
    shared_levels = [l for l in levels if l.route_type != "field"]

    details = db.query(OvertimeApplyDetail).filter(
        OvertimeApplyDetail.apply_id == apply_id).all()
    if field_levels:
        chains = {d.personnel_id: _personnel_chain(db, d.personnel_id) for d in details}
        level_users = {i: set() for i in range(len(field_levels))}
        for chain in chains.values():
            for i in range(min(len(field_levels), len(chain))):
                level_users[i].add(chain[i])
        for i, level in enumerate(field_levels):
            if not level_users[i]:
                raise ValueError(f"审批层级「{level.level_name}」：未能从人事链中找到任何审批人，请检查人员的上级绑定")
            for uid in level_users[i]:
                _add_node(db, apply, level, uid)

    for level in shared_levels:
        target = _target_department(db, applicant_dept, level.dept_offset or 0,
                                    level.mapped_bumen_id)
        approvers = _find_approvers(db, level.id, target.id if target else None, apply.work_type)
        if not approvers:
            raise ValueError(f"审批层级「{level.level_name}」未配置审批人")
        for ap in approvers:
            _add_node(db, apply, level, ap.bb_user_id)

    apply.status = "pending"
    apply.update_time = datetime.now()
    db.flush()
    return len(db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.apply_id == apply_id).all())


def _add_node(db, apply, level, user_id):
    db.add(OvertimeApplyApproval(
        apply_id=apply.id, step_order=level.level_order,
        approval_level_id=level.id, approver_id=user_id,
        status="pending", comment="", create_time=datetime.now(),
    ))


def approve_node(db: Session, approval_id: int, user_id: int, is_approved: bool,
                 comment: str = ""):
    """旧 Engine.Approve: 单节点通过/驳回,按 approval_mode 决定整步是否完成。"""
    node = db.get(OvertimeApplyApproval, approval_id)
    if not node:
        raise ValueError("审批记录不存在")
    if node.status != "pending":
        raise ValueError("该审批记录已处理")
    if node.approver_id != user_id:
        raise ValueError("您不是当前审批人")
    node.status = "approved" if is_approved else "rejected"
    node.comment = comment or ""
    node.approve_time = datetime.now()
    apply = db.get(OvertimeApply, node.apply_id)
    if not apply:
        raise ValueError("申请单不存在")
    if not is_approved:
        apply.status = "rejected"
        apply.update_time = datetime.now()
        (db.query(OvertimeApplyApproval)
         .filter(OvertimeApplyApproval.apply_id == node.apply_id,
                 OvertimeApplyApproval.status == "pending")
         .update({OvertimeApplyApproval.status: "skipped"}, synchronize_session=False))
        db.flush()
        return
    level = db.get(OvertimeApprovalLevel, node.approval_level_id) if node.approval_level_id else None
    mode = level.approval_mode if level else "single"
    same = db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.apply_id == node.apply_id,
        OvertimeApplyApproval.step_order == node.step_order).all()
    if mode == "all":
        finished = all(n.status == "approved" for n in same)
    elif mode == "any":
        finished = any(n.status == "approved" for n in same)
    else:
        finished = True
    if finished:
        steps = sorted({n.step_order for n in db.query(OvertimeApplyApproval).filter(
            OvertimeApplyApproval.apply_id == node.apply_id).all()})
        next_step = next((s for s in steps if s > node.step_order), 0)
        if next_step == 0:
            apply.status = "approved"
            apply.update_time = datetime.now()
    db.flush()


def resubmit_apply(db: Session, apply_id: int):
    apply = db.get(OvertimeApply, apply_id)
    if not apply:
        raise ValueError("申请单不存在")
    if apply.status != "rejected":
        raise ValueError("只有被驳回的申请单可以重新提交")
    db.query(OvertimeApplyApproval).filter(
        OvertimeApplyApproval.apply_id == apply_id).delete()
    apply.status = "draft"
    apply.update_time = datetime.now()
    db.flush()
