from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import settings
from app.core.security import CURRENT_PASSWORD_VERSION, hash_password
from app.db.session import get_db
from app.models.user import Department, Role, User

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    real_name: str = ""
    department_ids: List[int] = []
    phone: str = ""
    is_active: bool = True


class UserUpdate(BaseModel):
    real_name: str = ""
    department_ids: Optional[List[int]] = None
    phone: str = ""


class StatusIn(BaseModel):
    is_active: bool


class RolesIn(BaseModel):
    role_ids: List[int]


@router.get("")
def list_users(
    page: int = 1,
    size: int = 10,
    keyword: str = "",
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:user:manage")),
):
    query = db.query(User)
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        query = query.filter(or_(User.username.like(kw), User.real_name.like(kw)))
    total = query.count()
    users = query.order_by(User.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [u.to_dict() for u in users]}


@router.post("")
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:user:manage")),
):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    # 创建时不设密码,统一发初始密码,用户首次登录强制修改
    user = User(
        username=username,
        password_hash=hash_password(settings.INITIAL_PASSWORD),
        password_version=CURRENT_PASSWORD_VERSION,
        must_change_password=True,
        real_name=data.real_name.strip(),
        phone=data.phone.strip(),
        is_active=data.is_active,
    )
    if data.department_ids:
        user.departments = db.query(Department).filter(Department.id.in_(data.department_ids)).all()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.put("/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:user:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.real_name = data.real_name.strip()
    if data.department_ids is not None:
        user.departments = db.query(Department).filter(Department.id.in_(data.department_ids)).all()
    user.phone = data.phone.strip()
    db.commit()
    return user.to_dict()


@router.put("/{user_id}/status")
def set_user_status(
    user_id: int,
    data: StatusIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("system:user:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id and not data.is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    user.is_active = data.is_active
    db.commit()
    return user.to_dict()


@router.put("/{user_id}/password")
def reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:user:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 重置回初始密码,并要求用户下次登录先改密码
    user.password_hash = hash_password(settings.INITIAL_PASSWORD)
    user.password_version = CURRENT_PASSWORD_VERSION
    user.must_change_password = True
    db.commit()
    return {"message": "已重置为初始密码,该用户下次登录须先修改密码"}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("system:user:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.is_superuser:
        raise HTTPException(status_code=400, detail="超级管理员账号不能删除,可改为停用")
    # user_role / user_department 外键均为 CASCADE,角色与部门关联随之清除
    db.delete(user)
    db.commit()
    return {"message": "已删除"}


@router.put("/{user_id}/roles")
def set_user_roles(
    user_id: int,
    data: RolesIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("system:user:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.roles = db.query(Role).filter(Role.id.in_(data.role_ids)).all()
    db.commit()
    return user.to_dict()
