from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.user import Permission, Role, User

router = APIRouter()


class RoleIn(BaseModel):
    name: str
    code: str
    remark: str = ""


class PermissionsIn(BaseModel):
    permission_ids: List[int]


@router.get("/all")
def list_all_roles(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return [r.to_dict() for r in db.query(Role).order_by(Role.id).all()]


@router.get("/permissions")
def list_all_permissions(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return [
        {"id": p.id, "code": p.code, "name": p.name, "remark": p.remark}
        for p in db.query(Permission).order_by(Permission.id).all()
    ]


@router.post("")
def create_role(
    data: RoleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:role:manage")),
):
    name, code = data.name.strip(), data.code.strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="角色名称和编码不能为空")
    if db.query(Role).filter(Role.name == name).first():
        raise HTTPException(status_code=400, detail="角色名称已存在")
    if db.query(Role).filter(Role.code == code).first():
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role = Role(name=name, code=code, remark=data.remark.strip())
    db.add(role)
    db.commit()
    db.refresh(role)
    return role.to_dict()


@router.put("/{role_id}")
def update_role(
    role_id: int,
    data: RoleIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:role:manage")),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    name, code = data.name.strip(), data.code.strip()
    dup = db.query(Role).filter(Role.name == name, Role.id != role_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="角色名称已存在")
    dup = db.query(Role).filter(Role.code == code, Role.id != role_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role.name, role.code, role.remark = name, code, data.remark.strip()
    db.commit()
    return role.to_dict()


@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:role:manage")),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.users:
        raise HTTPException(status_code=400, detail="该角色下仍有用户,请先移除")
    db.delete(role)
    db.commit()
    return {"message": "已删除"}


@router.put("/{role_id}/permissions")
def set_role_permissions(
    role_id: int,
    data: PermissionsIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:role:manage")),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    role.permissions = db.query(Permission).filter(Permission.id.in_(data.permission_ids)).all()
    db.commit()
    return role.to_dict()
