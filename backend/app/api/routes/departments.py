from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.user import Department, User

router = APIRouter()


class DepartmentIn(BaseModel):
    name: str
    remark: str = ""


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
    dept = Department(name=name, remark=data.remark.strip())
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
    dept.name = name
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
    db.delete(dept)
    db.commit()
    return {"message": "已删除"}
