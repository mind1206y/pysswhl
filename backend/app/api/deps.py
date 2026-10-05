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
