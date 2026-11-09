from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录已过期,请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号已停用")
    return user


def require_permission(code: str):
    """接口权限校验:超级管理员直接放行,否则要求其角色挂有该权限"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.is_superuser:
            return user
        owned = {p.code for role in user.roles for p in role.permissions}
        if code not in owned:
            raise HTTPException(status_code=403, detail="没有操作权限")
        return user

    return checker


def require_any_permission(*codes: str):
    """满足任一权限码即放行(用于登记/归集共用的附件下载等接口)。"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.is_superuser:
            return user
        owned = {p.code for role in user.roles for p in role.permissions}
        if not owned.intersection(codes):
            raise HTTPException(status_code=403, detail="没有操作权限")
        return user

    return checker


def dept_scope_ids(db, user) -> Optional[set]:
    """用户可见的部门 id 集合(照旧系统 bmcj 层级码前缀语义:本部门+全部子部门)。

    超级管理员或未挂部门的用户返回 None(不限定,看全部);
    否则只看 bmid 落在自己部门子树内的记录。各业务模块共用。
    """
    from app.models.user import Department

    if user.is_superuser or not user.departments:
        return None
    ids = {d.id for d in user.departments}
    while True:
        children = (
            db.query(Department.id)
            .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids))
            .all()
        )
        if not children:
            break
        ids |= {c[0] for c in children}
    return ids


def dept_name_map(db) -> dict:
    """部门 id → 名称(列表部门列、日志值、导出列共用)。"""
    from app.models.user import Department

    return {d.id: d.name for d in db.query(Department).all()}
