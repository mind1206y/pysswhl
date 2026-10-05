import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# 复杂密码要求:至少 8 位,且同时包含大写字母、小写字母、数字、符号
_PASSWORD_RULES = [
    (r".{8,}", "至少 8 位"),
    (r"[A-Z]", "需包含大写字母"),
    (r"[a-z]", "需包含小写字母"),
    (r"\d", "需包含数字"),
    (r"[^A-Za-z0-9]", "需包含符号"),
]


def password_issues(password: str) -> list:
    """校验密码复杂度,返回不满足项的列表;全部通过则返回空列表"""
    issues = []
    for pattern, message in _PASSWORD_RULES:
        if not re.search(pattern, password or ""):
            issues.append(message)
    return issues


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """token 无效或过期时抛出 jwt.PyJWTError"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
