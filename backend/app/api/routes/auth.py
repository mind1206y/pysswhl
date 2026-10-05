from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    create_access_token,
    decrypt_password,
    get_public_key_pem,
    hash_password,
    password_issues,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str  # 前端用 RSA 公钥加密后的 base64 密文


class ChangePasswordIn(BaseModel):
    old_password: str  # 均为 RSA 加密密文
    new_password: str


def user_permissions(user: User) -> List[str]:
    if user.is_superuser:
        return ["*"]
    return sorted({p.code for role in user.roles for p in role.permissions})


def build_user_info(user: User) -> dict:
    info = user.to_dict()
    info["permissions"] = user_permissions(user)
    return info


@router.get("/public-key")
def public_key():
    """下发 RSA 公钥,登录/改密页用它加密密码(公钥可公开)"""
    return {"publicKey": get_public_key_pem()}


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username.strip()).first()
    try:
        plain = decrypt_password(data.password)
    except (ValueError, TypeError):
        # 密文无效:多半是后端重启导致公钥更换,前端刷新后重新获取即可
        raise HTTPException(status_code=400, detail="密码解密失败,请刷新页面后重试")
    if user is None or not verify_password(plain, user.password_hash):
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
    try:
        old_plain = decrypt_password(data.old_password)
        new_plain = decrypt_password(data.new_password)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="密码解密失败,请刷新页面后重试")
    if not verify_password(old_plain, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    issues = password_issues(new_plain)
    if issues:
        raise HTTPException(
            status_code=400,
            detail="新密码强度不足:" + ",".join(issues) + "(需包含大写字母、小写字母、数字和符号)",
        )
    user.password_hash = hash_password(new_plain)
    user.must_change_password = False
    db.commit()
    return {"message": "密码修改成功"}
