from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import (
    CURRENT_PASSWORD_VERSION,
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


LOGIN_LOCK_THRESHOLD = 5
LOGIN_LOCK_MINUTES = 10

# ===== IP 级登录限速:每 IP 5 分钟内最多 20 次登录尝试(账号锁定之外的第二道闸) =====
# 仅内存计数:单进程/单机有效;多 worker 时各进程独立计数,阈值按 worker 数上调即可。
# nginx 反代部署时请配置 real_ip,使此处拿到真实客户端 IP。
LOGIN_RATE_LIMIT = 20
LOGIN_RATE_WINDOW = timedelta(minutes=5)
_login_attempts = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_login_rate(request: Request):
    ip = _client_ip(request)
    now = datetime.now()
    q = _login_attempts[ip]
    while q and now - q[0] > LOGIN_RATE_WINDOW:
        q.popleft()
    if len(q) >= LOGIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="登录尝试过于频繁,请 5 分钟后再试")
    q.append(now)


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    _check_login_rate(request)
    user = db.query(User).filter(User.username == data.username.strip()).first()
    try:
        plain = decrypt_password(data.password)
    except (ValueError, TypeError):
        # 密文无效:多半是后端重启导致公钥更换,前端刷新后重新获取即可
        raise HTTPException(status_code=400, detail="密码解密失败,请刷新页面后重试")
    if user is None:
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    # 锁定检查:锁定期内直接拒绝,不再做密码验证
    now = datetime.now()
    if user.locked_until:
        if user.locked_until > now:
            minutes = int((user.locked_until - now).total_seconds() // 60) + 1
            raise HTTPException(status_code=403, detail=f"账号已锁定,请 {minutes} 分钟后再试")
        # 锁定已过期,重新计数
        user.failed_attempts = 0
        user.locked_until = None

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用,请联系管理员")

    if not verify_password(plain, user.password_hash, user.password_version or 0):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= LOGIN_LOCK_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            user.failed_attempts = 0
            db.commit()
            raise HTTPException(
                status_code=403,
                detail=f"密码连续错误 {LOGIN_LOCK_THRESHOLD} 次,账号已锁定 {LOGIN_LOCK_MINUTES} 分钟",
            )
        db.commit()
        left = LOGIN_LOCK_THRESHOLD - user.failed_attempts
        raise HTTPException(
            status_code=400,
            detail=f"用户名或密码错误,已错 {user.failed_attempts} 次(再错 {left} 次将锁定 10 分钟)",
        )

    # 登录成功,清除错误计数与锁定状态
    user.failed_attempts = 0
    user.locked_until = None
    # 旧版本哈希透明升级到当前算法(无需用户重置密码)
    if (user.password_version or 0) < CURRENT_PASSWORD_VERSION:
        user.password_hash = hash_password(plain)
        user.password_version = CURRENT_PASSWORD_VERSION
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
    user.password_version = CURRENT_PASSWORD_VERSION
    user.must_change_password = False
    db.commit()
    return {"message": "密码修改成功"}
