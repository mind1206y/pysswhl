from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.user import Department, User

router = APIRouter()


class DepartmentIn(BaseModel):
    name: str
    parent_id: int = 0  # 0/空 = 顶级部门
    remark: str = ""


def check_parent(db: Session, parent_id: int, self_id: int = 0) -> int:
    """校验上级部门,返回规范后的 parent_id(0 表示顶级);自己不能是自己的上级,也不能挂在 own 子级下(防环)"""
    if not parent_id:
        return 0
    parent = db.get(Department, parent_id)
    if parent is None:
        raise HTTPException(status_code=400, detail="上级部门不存在")
    node, depth = parent, 0
    while node is not None:
        if node.id == self_id:
            raise HTTPException(status_code=400, detail="上级部门不能是自己或自己的下级")
        node, depth = node.parent_id and db.get(Department, node.parent_id), depth + 1
        if depth > 50:
            raise HTTPException(status_code=400, detail="部门层级异常")
    return parent_id


@router.get("")
def list_departments(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return [d.to_dict() for d in db.query(Department).order_by(Department.id).all()]


@router.post("")
def create_department(
    data: DepartmentIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:dept:manage")),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="部门名称不能为空")
    if db.query(Department).filter(Department.name == name).first():
        raise HTTPException(status_code=400, detail="部门名称已存在")
    parent_id = check_parent(db, data.parent_id)
    dept = Department(name=name, parent_id=parent_id or None, remark=data.remark.strip())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept.to_dict()


@router.put("/{dept_id}")
def update_department(
    dept_id: int,
    data: DepartmentIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:dept:manage")),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="部门名称不能为空")
    dup = db.query(Department).filter(Department.name == name, Department.id != dept_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="部门名称已存在")
    parent_id = check_parent(db, data.parent_id, self_id=dept_id)
    dept.name = name
    dept.parent_id = parent_id or None
    dept.remark = data.remark.strip()
    db.commit()
    return dept.to_dict()


@router.delete("/{dept_id}")
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:dept:manage")),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    if dept.users:
        raise HTTPException(status_code=400, detail="该部门下仍有关联用户,请先在用户管理中移除")
    if db.query(Department).filter(Department.parent_id == dept_id).first():
        raise HTTPException(status_code=400, detail="该部门下仍有子部门,请先删除或转移子部门")
    db.delete(dept)
    db.commit()
    return {"message": "已删除"}
