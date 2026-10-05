import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings

# 密码哈希版本:v0 = bcrypt(历史遗留);v1 = Argon2id + pepper(现行)
# 老用户在下次登录成功时自动升级到 v1,无需重置密码。
CURRENT_PASSWORD_VERSION = 1
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def _peppered(plain: str) -> str:
    """把 pepper 以 HMAC 方式混入密码;pepper 只存在于后端配置,不进数据库"""
    return base64.b64encode(
        hmac.new(settings.PASSWORD_PEPPER.encode(), plain.encode(), hashlib.sha256).digest()
    ).decode()


def hash_password(plain: str) -> str:
    """生成当前版本(v1)的密码哈希"""
    return _ph.hash(_peppered(plain))


def verify_password(plain: str, hashed: str, version: int = CURRENT_PASSWORD_VERSION) -> bool:
    """按存储时的版本校验密码"""
    if version <= 0:
        return verify_password_legacy(plain, hashed)
    try:
        return _ph.verify(hashed, _peppered(plain))
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False

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


def verify_password_legacy(plain: str, hashed: str) -> bool:
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


# ===== 密码传输加密:前端用 RSA 公钥加密,后端内存私钥解密 =====

@lru_cache(maxsize=1)
def _rsa_private_key():
    """进程内生成并缓存 RSA-2048 密钥对;私钥只存在于后端内存,不落盘不入库"""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def get_public_key_pem() -> str:
    return _rsa_private_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def decrypt_password(encrypted_b64: str) -> str:
    """解密前端 RSA-OAEP(SHA-256) 加密的密码(base64 密文);无效密文抛 ValueError"""
    ciphertext = base64.b64decode(encrypted_b64)
    plaintext = _rsa_private_key().decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return plaintext.decode("utf-8")
