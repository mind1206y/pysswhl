from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, password_issues, verify_password
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


def user_permissions(user: User) -> List[str]:
    if user.is_superuser:
        return ["*"]
    return sorted({p.code for role in user.roles for p in role.permissions})


def build_user_info(user: User) -> dict:
    info = user.to_dict()
    info["permissions"] = user_permissions(user)
    return info


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username.strip()).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用,请联系管理员")
    user.last_login_at = datetime.now()
    db.commit()
    return {"token": create_access_token(user.id, user.username), "user": build_user_info(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return build_user_info(user)


@router.put("/password")
def change_password(
    data: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    issues = password_issues(data.new_password)
    if issues:
        raise HTTPException(
            status_code=400,
            detail="新密码强度不足:" + ",".join(issues) + "(需包含大写字母、小写字母、数字和符号)",
        )
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    db.commit()
    return {"message": "密码修改成功"}
