"""加班申请审批 - 配置管理路由(人员池 / 加班部门镜像树 / 审批层级 / 审批人)。

路径前缀同为 /api/overtime。部门树的增删改只允许 is_admin(旧 IsAdmin)。
"""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.overtime import (
    OvertimeApprovalLevel,
    OvertimeApprover,
    OvertimeDept,
    OvertimePersonnel,
)
from app.models.user import Department, User
from app.services import overtime_common as oc

router = APIRouter()


def _tree_node(node, rows_by_parent):
    suffix = "" if node.is_active else " (已停用)"
    return {
        "id": node.id, "text": (node.name or "") + suffix,
        "displayText": (node.full_path or node.name or "") + suffix,
        "fullPath": node.full_path or node.name or "",
        "sysBumenId": node.sys_bumen_id, "isField": bool(node.is_field),
        "isActive": bool(node.is_active), "level": node.level,
        "parentId": node.parent_id, "sortOrder": node.sort_order,
        "children": [_tree_node(c, rows_by_parent) for c in rows_by_parent.get(node.id, [])],
    }


def _full_tree(db):
    rows = db.query(OvertimeDept).order_by(OvertimeDept.sort_order, OvertimeDept.id).all()
    by_parent = {}
    for d in rows:
        by_parent.setdefault(d.parent_id, []).append(d)
    return [_tree_node(d, by_parent) for d in by_parent.get(None, [])]


# ================================================================ 人员池

@router.get("/personnel")
def list_personnel(search: str = "", dept_id: int | None = None,
                   show_inactive: bool = False, max_depth: int | str | None = None,
                   page: int = 1, rows: int = 50,
                   db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(OvertimePersonnel)
    visible = oc.visible_ot_dept_ids(db, current)
    if visible is not None:
        q = q.filter(OvertimePersonnel.bb_bumen_id.in_(visible or [-1]))
    if not show_inactive:
        q = q.filter(OvertimePersonnel.is_active.is_(True))
    if dept_id:
        ids = oc.resolve_dept_ids(db, dept_id, max_depth)
        q = q.filter(OvertimePersonnel.bb_bumen_id.in_(ids or [-1]))
    if search.strip():
        kw = f"%{search.strip()}%"
        q = q.filter(or_(OvertimePersonnel.name.like(kw),
                         OvertimePersonnel.employee_no.like(kw)))
    total = q.count()
    items = q.order_by(OvertimePersonnel.is_active.desc(),
                       OvertimePersonnel.name, OvertimePersonnel.id).offset(
        (page - 1) * rows).limit(rows).all()
    paths = oc.dept_paths(db)
    names = oc.user_names(db)
    return {"total": total, "rows": [
        {**p.to_dict(), "deptName": paths.get(p.bb_bumen_id, ""),
         "userName": names.get(p.bb_user_id, "")}
        for p in items
    ]}


@router.get("/personnel/active")
def active_personnel(dept_id: int | None = None, db: Session = Depends(get_db),
                     current=Depends(get_current_user)):
    q = db.query(OvertimePersonnel).filter(OvertimePersonnel.is_active.is_(True))
    visible = oc.visible_ot_dept_ids(db, current)
    if visible is not None:
        q = q.filter(OvertimePersonnel.bb_bumen_id.in_(visible or [-1]))
    if dept_id:
        q = q.filter(OvertimePersonnel.bb_bumen_id.in_(oc.descendants(db, dept_id)))
    return [p.to_dict() for p in q.order_by(OvertimePersonnel.name).all()]


@router.get("/personnel/sibling")
def sibling_personnel(db: Session = Depends(get_db), current=Depends(get_current_user)):
    if not oc.is_verifier(current):
        return []
    mirror = oc.mirror_by_sys(db, oc.user_primary_sys_dept(current))
    if not mirror:
        return []
    children = db.query(OvertimeDept.id).filter(
        OvertimeDept.parent_id == mirror.id, OvertimeDept.is_active.is_(True)).all()
    ids = [mirror.id] + [c[0] for c in children]
    return [p.to_dict() for p in db.query(OvertimePersonnel).filter(
        OvertimePersonnel.bb_bumen_id.in_(ids),
        OvertimePersonnel.is_active.is_(True)).order_by(OvertimePersonnel.name).all()]


@router.get("/personnel/my")
def my_personnel(db: Session = Depends(get_db), current=Depends(get_current_user)):
    p = db.query(OvertimePersonnel).filter(
        OvertimePersonnel.bb_user_id == current.id,
        OvertimePersonnel.is_active.is_(True)).first()
    if not p:
        return {"found": False, "msg": "当前用户未匹配加班人员，请联系管理员在配置管理中绑定系统用户"}
    return {"found": True, "id": p.id, "name": p.name, "employee_no": p.employee_no,
            "daily_wage": oc.fnum(p.daily_wage), "dept_id": p.bb_bumen_id}


@router.post("/personnel/save")
def save_personnel(payload: dict = Body(...), db: Session = Depends(get_db),
                   current=Depends(get_current_user)):
    oc.ensure_perm(current, oc.PERM_HR, oc.PERM_MANAGE)
    rid = int(payload.get("id") or 0)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "姓名不能为空")
    if rid:
        p = db.get(OvertimePersonnel, rid)
        if not p:
            raise HTTPException(400, "人员不存在")
    else:
        p = OvertimePersonnel(is_active=True, create_time=datetime.now())
        db.add(p)
    p.name = name
    p.employee_no = payload.get("employee_no") or ""
    p.bb_user_id = payload.get("bb_user_id") or None
    p.bb_bumen_id = payload.get("bb_bumen_id") or None
    p.parent_id = payload.get("parent_id") or None
    p.daily_wage = oc.dec2(payload.get("daily_wage") or 0)
    db.commit()
    return {"success": True, "msg": "保存成功", "id": p.id}


@router.post("/personnel/delete")
def delete_personnel(payload: dict = Body(...), db: Session = Depends(get_db),
                     current=Depends(get_current_user)):
    oc.ensure_perm(current, oc.PERM_HR, oc.PERM_MANAGE)
    p = db.get(OvertimePersonnel, int(payload.get("id") or 0))
    if not p:
        raise HTTPException(400, "人员不存在")
    p.is_active = False
    db.commit()
    return {"success": True, "msg": "已停用"}


@router.post("/personnel/restore")
def restore_personnel(payload: dict = Body(...), db: Session = Depends(get_db),
                      current=Depends(get_current_user)):
    oc.ensure_perm(current, oc.PERM_HR, oc.PERM_MANAGE)
    p = db.get(OvertimePersonnel, int(payload.get("id") or 0))
    if not p:
        raise HTTPException(400, "人员不存在")
    p.is_active = True
    db.commit()
    return {"success": True, "msg": "已恢复"}


# ================================================================ 加班部门树

@router.get("/depts/tree")
def dept_tree(full: bool = False, db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    return oc.dept_tree(db, current, full=full or oc.is_admin(current))


@router.get("/depts/sys-list")
def sys_dept_list(db: Session = Depends(get_db), current=Depends(get_current_user)):
    """新系统部门下拉(审批层级指定部门 / 审批人管辖部门)。"""
    return [{"id": d.id, "text": d.name} for d in db.query(Department).order_by(
        Department.id).all()]


@router.get("/depts/top-sys")
def top_sys_depts(db: Session = Depends(get_db), current=Depends(get_current_user)):
    if not oc.is_admin(current):
        raise HTTPException(403, "无权限")
    mirrored = {d.sys_bumen_id for d in db.query(OvertimeDept.sys_bumen_id).all()}
    roots = db.query(Department).filter(Department.parent_id.is_(None)).order_by(
        Department.id).all()
    return [{"id": d.id, "text": d.name} for d in roots
            if d.id not in mirrored and d.name not in ("超级", "停用部门")]


@router.get("/depts/mirror-children")
def mirror_children(parentOtNodeId: int, db: Session = Depends(get_db),
                    current=Depends(get_current_user)):
    if not oc.is_admin(current):
        raise HTTPException(403, "无权限")
    node = db.get(OvertimeDept, parentOtNodeId)
    if not node or not node.sys_bumen_id:
        return []
    mirrored = {d.sys_bumen_id for d in db.query(OvertimeDept.sys_bumen_id).all()}
    children = db.query(Department).filter(
        Department.parent_id == node.sys_bumen_id).order_by(Department.id).all()
    return [{"id": d.id, "text": d.name} for d in children if d.id not in mirrored]


def _admin_only(current):
    if not oc.is_admin(current):
        raise HTTPException(403, "无权限，仅管理员可操作")


@router.post("/depts/save")
def save_dept(payload: dict = Body(...), db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    _admin_only(current)
    name = (payload.get("name") or "").strip()
    parent_id = int(payload.get("parentId") or 0) or None
    if not name:
        raise HTTPException(400, "部门名称不能为空")
    parent = db.get(OvertimeDept, parent_id) if parent_id else None
    if parent_id and not parent:
        raise HTTPException(400, "父部门不存在")
    node = OvertimeDept(name=name, parent_id=parent_id,
                        full_path=f"{parent.full_path}/{name}" if parent else name,
                        level=(parent.level or 1) + 1 if parent else 1,
                        sort_order=0, is_active=True, sys_bumen_id=None,
                        create_time=datetime.now())
    db.add(node)
    db.commit()
    return {"success": True, "msg": "保存成功", "id": node.id}


@router.post("/depts/mirror")
def add_mirror(payload: dict = Body(...), db: Session = Depends(get_db),
               current=Depends(get_current_user)):
    _admin_only(current)
    sys_id = int(payload.get("sysBumenId") or 0)
    parent_id = int(payload.get("parentId") or 0)
    parent = db.get(OvertimeDept, parent_id)
    if not parent:
        raise HTTPException(400, "父部门不存在")
    if db.query(OvertimeDept.id).filter(OvertimeDept.sys_bumen_id == sys_id).first():
        raise HTTPException(400, "该系统部门已镜像")
    d = db.get(Department, sys_id)
    if not d:
        raise HTTPException(400, "系统部门不存在")
    node = OvertimeDept(
        name=d.name, parent_id=parent.id, sys_bumen_id=sys_id,
        full_path=f"{parent.full_path}/{d.name}", level=(parent.level or 1) + 1,
        sort_order=0, is_active=True, is_field=False, create_time=datetime.now())
    db.add(node)
    db.commit()
    return {"success": True, "msg": "镜像成功", "id": node.id}


@router.post("/depts/mirror-root")
def add_mirror_root(payload: dict = Body(...), db: Session = Depends(get_db),
                    current=Depends(get_current_user)):
    _admin_only(current)
    sys_id = int(payload.get("sysBumenId") or 0)
    if db.query(OvertimeDept.id).filter(OvertimeDept.sys_bumen_id == sys_id).first():
        raise HTTPException(400, "该系统部门已镜像")
    d = db.get(Department, sys_id)
    if not d:
        raise HTTPException(400, "系统部门不存在")
    node = OvertimeDept(name=d.name, parent_id=None, sys_bumen_id=sys_id,
                        full_path=d.name, level=1, sort_order=0, is_active=True,
                        is_field=False, create_time=datetime.now())
    db.add(node)
    db.commit()
    return {"success": True, "msg": "镜像成功", "id": node.id}


@router.post("/depts/rename")
def rename_dept(payload: dict = Body(...), db: Session = Depends(get_db),
                current=Depends(get_current_user)):
    _admin_only(current)
    node = db.get(OvertimeDept, int(payload.get("id") or 0))
    if not node:
        raise HTTPException(400, "部门不存在")
    if node.parent_id is None:
        raise HTTPException(400, "根部门不允许改名")
    if node.sys_bumen_id:
        raise HTTPException(400, "镜像节点名称跟随系统部门，不允许手动改名")
    node.name = (payload.get("newName") or "").strip() or node.name
    oc.recalc_full_paths(db)
    db.commit()
    return {"success": True, "msg": "已改名"}


@router.post("/depts/toggle")
def toggle_dept(payload: dict = Body(...), db: Session = Depends(get_db),
                current=Depends(get_current_user)):
    _admin_only(current)
    node = db.get(OvertimeDept, int(payload.get("id") or 0))
    if not node:
        raise HTTPException(400, "部门不存在")
    if node.parent_id is None:
        raise HTTPException(400, "根部门不允许停用")
    if node.sys_bumen_id:
        raise HTTPException(400, "镜像节点跟随系统部门，不允许手动停用")
    node.is_active = not bool(node.is_active)
    db.commit()
    return {"success": True, "msg": "已启用" if node.is_active else "已停用"}


@router.post("/depts/move")
def move_dept(payload: dict = Body(...), db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    _admin_only(current)
    node = db.get(OvertimeDept, int(payload.get("id") or 0))
    if not node:
        raise HTTPException(400, "部门不存在")
    new_parent = int(payload.get("newParentId") or 0) or None
    if not node.parent_id:
        raise HTTPException(400, "该部门已经是根部门")
    if new_parent == node.id:
        raise HTTPException(400, "不能将部门移动到自身下")
    if new_parent:
        parent = db.get(OvertimeDept, new_parent)
        if not parent:
            raise HTTPException(400, "目标父部门不存在")
        if not parent.is_active:
            raise HTTPException(400, "目标父部门已停用")
        if new_parent in oc.descendants(db, node.id):
            raise HTTPException(400, "不能将部门移动到其子部门下")
    node.parent_id = new_parent
    db.flush()
    oc.recalc_full_paths(db)
    db.commit()
    return {"success": True, "msg": "已移动"}


@router.post("/depts/sort")
def sort_dept(payload: dict = Body(...), db: Session = Depends(get_db),
              current=Depends(get_current_user)):
    _admin_only(current)
    for item in payload.get("items") or []:
        node = db.get(OvertimeDept, int(item.get("id") or 0))
        if node:
            node.sort_order = int(item.get("sort_order") or 0)
    db.commit()
    return {"success": True, "msg": "排序已保存"}


# ================================================================ 审批层级 / 审批人

@router.get("/levels")
def list_levels(db: Session = Depends(get_db), current=Depends(get_current_user)):
    sys_names = {d.id: d.name for d in db.query(Department).all()}
    rows = db.query(OvertimeApprovalLevel).order_by(
        OvertimeApprovalLevel.level_order, OvertimeApprovalLevel.id).all()
    return [{**r.to_dict(), "deptName": sys_names.get(r.mapped_bumen_id, "")}
            for r in rows]


@router.post("/levels/save")
def save_level(payload: dict = Body(...), db: Session = Depends(get_db),
               current=Depends(get_current_user)):
    _admin_only(current)
    if not (payload.get("level_name") or "").strip():
        raise HTTPException(400, "层级名称不能为空")
    rid = int(payload.get("id") or 0)
    row = db.get(OvertimeApprovalLevel, rid) if rid else None
    if rid and not row:
        raise HTTPException(400, "层级不存在")
    if not row:
        row = OvertimeApprovalLevel(create_time=datetime.now())
        db.add(row)
    row.level_name = payload.get("level_name") or ""
    row.level_order = int(payload.get("level_order") or 0)
    row.dept_offset = int(payload.get("dept_offset") or 0)
    row.mapped_bumen_id = payload.get("mapped_bumen_id") or None
    row.approval_mode = payload.get("approval_mode") or "single"
    row.route_type = payload.get("route_type") or "all"
    row.is_active = bool(payload.get("is_active", True))
    db.commit()
    return {"success": True, "msg": "保存成功", "id": row.id}


@router.post("/levels/delete")
def delete_level(payload: dict = Body(...), db: Session = Depends(get_db),
                 current=Depends(get_current_user)):
    _admin_only(current)
    row = db.get(OvertimeApprovalLevel, int(payload.get("id") or 0))
    if not row:
        raise HTTPException(400, "层级不存在")
    row.is_active = False
    db.commit()
    return {"success": True, "msg": "已停用"}


@router.get("/approvers")
def list_approvers(level_id: int | None = None, page: int = 1, rows: int = 50,
                   db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(OvertimeApprover).filter(OvertimeApprover.is_active.is_(True))
    if level_id:
        q = q.filter(OvertimeApprover.approval_level_id == level_id)
    total = q.count()
    items = q.order_by(OvertimeApprover.id).offset((page - 1) * rows).limit(rows).all()
    levels = {l.id: l.level_name for l in db.query(OvertimeApprovalLevel).all()}
    sys_names = {d.id: d.name for d in db.query(Department).all()}
    names = oc.user_names(db)
    return {"total": total, "rows": [
        {**a.to_dict(), "userName": names.get(a.bb_user_id, ""),
         "levelName": levels.get(a.approval_level_id, ""),
         "scopeDeptName": sys_names.get(a.scope_bumen_id, "全局" if not a.scope_bumen_id else "")}
        for a in items
    ]}


@router.post("/approvers/save")
def save_approver(payload: dict = Body(...), db: Session = Depends(get_db),
                  current=Depends(get_current_user)):
    _admin_only(current)
    if not int(payload.get("bb_user_id") or 0) or not int(payload.get("approval_level_id") or 0):
        raise HTTPException(400, "请选择审批人和审批层级")
    rid = int(payload.get("id") or 0)
    row = db.get(OvertimeApprover, rid) if rid else None
    if rid and not row:
        raise HTTPException(400, "审批人不存在")
    if not row:
        dup = db.query(OvertimeApprover.id).filter(
            OvertimeApprover.bb_user_id == int(payload.get("bb_user_id") or 0),
            OvertimeApprover.approval_level_id == int(payload.get("approval_level_id") or 0),
            OvertimeApprover.is_active.is_(True),
            OvertimeApprover.work_type == (payload.get("work_type") or "")).first()
        if dup:
            raise HTTPException(400, "该审批层级下已有此用户")
        row = OvertimeApprover(is_active=True, create_time=datetime.now())
        db.add(row)
    row.bb_user_id = int(payload.get("bb_user_id") or 0) or None
    row.approval_level_id = int(payload.get("approval_level_id") or 0) or None
    row.scope_bumen_id = payload.get("scope_bumen_id") or None
    row.work_type = payload.get("work_type") or ""
    db.commit()
    return {"success": True, "msg": "保存成功", "id": row.id}


@router.post("/approvers/delete")
def delete_approver(payload: dict = Body(...), db: Session = Depends(get_db),
                    current=Depends(get_current_user)):
    _admin_only(current)
    row = db.get(OvertimeApprover, int(payload.get("id") or 0))
    if not row:
        raise HTTPException(400, "审批人不存在")
    row.is_active = False
    db.commit()
    return {"success": True, "msg": "已停用"}
