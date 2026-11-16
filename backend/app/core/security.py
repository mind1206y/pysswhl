import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings

# 密码哈希版本:
#   0 = bcrypt(新系统早期,已废弃)
#   1 = Argon2id + pepper(现行,新密码一律用它)
#   2 = 旧系统 PBKDF2-HMAC-SHA1:格式 pbkdf2$迭代次数$盐(Base64)$哈希(Base64),
#       对应旧 whl.common.PasswordHasher(.NET Rfc2898DeriveBytes),密码按 UTF-8 编码
#   3 = 旧系统无盐 MD5:.NET Encoding.Unicode(UTF-16LE) 求 MD5,且每字节 ToString("x")
#       会丢掉前导零,因此长度是 29~32 位十六进制而非固定 32 位
# 2/3 是旧系统用户表原样导入后的形态;任一格式验证通过后都会在登录时透明升级到 v1。
CURRENT_PASSWORD_VERSION = 1
LEGACY_PBKDF2_VERSION = 2
LEGACY_MD5_VERSION = 3
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
    """按存储时的版本校验密码(v1 现行,v0 bcrypt,v2 旧 PBKDF2,v3 旧 MD5)"""
    hashed = hashed or ""
    # 版本号优先,其次按哈希长相兜底:老数据版本号可能没写对,但格式是自描述的
    if version == LEGACY_PBKDF2_VERSION or hashed.startswith("pbkdf2$"):
        return verify_password_old_pbkdf2(plain, hashed)
    if version == LEGACY_MD5_VERSION or _LEGACY_MD5_RE.fullmatch(hashed):
        return verify_password_old_md5(plain, hashed)
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


# 旧系统 MD5 哈希的可识别长相:29~32 位十六进制(.NET ToString("x") 丢前导零,长度不固定)
_LEGACY_MD5_RE = re.compile(r"[0-9a-f]{29,32}", re.IGNORECASE)


def verify_password_old_pbkdf2(plain: str, hashed: str) -> bool:
    """旧系统 PBKDF2(pbkdf2$迭代$盐$哈希),与 .NET Rfc2898DeriveBytes(SHA1, UTF-8) 同口径"""
    parts = (hashed or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False
    try:
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2], validate=True)
        expected = base64.b64decode(parts[3], validate=True)
    except (ValueError, TypeError):
        return False
    if iterations <= 0 or not expected:
        return False
    derived = hashlib.pbkdf2_hmac("sha1", plain.encode("utf-8"), salt, iterations, len(expected))
    return hmac.compare_digest(derived, expected)


def verify_password_old_md5(plain: str, hashed: str) -> bool:
    """旧系统无盐 MD5:.NET Encoding.Unicode(UTF-16LE) 求 MD5,再逐字节 ToString("x") 转 hex"""
    digest = hashlib.md5(plain.encode("utf-16-le")).digest()
    legacy = "".join(format(b, "x") for b in digest)
    return hmac.compare_digest(legacy, (hashed or "").strip().lower())


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """token 无效或过期时抛出 jwt.PyJWTError"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def create_short_token(scope: str, payload: dict, minutes: int = 10) -> str:
    """短时效作用域令牌(如附件下载),避免长期登录令牌出现在 URL/访问日志里。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    body = {**payload, "typ": "short", "scope": scope, "exp": expire}
    return jwt.encode(body, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_short_token(token: str, expected_scope: str) -> dict:
    """校验短时效令牌;scope 不符视为无效(防止登录令牌/下载令牌互相冒用)。"""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if payload.get("typ") != "short" or payload.get("scope") != expected_scope:
        raise jwt.PyJWTError("令牌类型不符")
    return payload


# ===== 密码传输加密:前端用 RSA 公钥加密,后端内存私钥解密 =====

@lru_cache(maxsize=1)
def _rsa_private_key():
    """加载(首次则生成)RSA-2048 私钥,落盘到 backend/rsa_key.pem。

    落盘是为了多进程部署(如 uvicorn --workers N):各 worker 共用同一对密钥,
    否则取公钥和验证密文可能落在不同进程导致解密失败。保密级别同 .env。
    """
    key_file = Path(__file__).resolve().parents[2] / "rsa_key.pem"
    if key_file.exists():
        return serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key


def get_public_key_pem() -> str:
    return _rsa_private_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


# 内网用纯 HTTP(http://<ip>:端口,既不是 https 也不是 localhost)访问时,
# 浏览器不暴露 Web Crypto(crypto.subtle 为 undefined),前端无法做 RSA 加密,
# 会改发带该前缀的明文。判在前缀上,避免与合法 base64 密文混淆。
PLAIN_PASSWORD_PREFIX = "plain:"


def decrypt_password(encrypted_b64: str) -> str:
    """解密前端 RSA-OAEP(SHA-256) 加密的密码(base64 密文);无效密文抛 ValueError"""
    if encrypted_b64.startswith(PLAIN_PASSWORD_PREFIX):
        return encrypted_b64[len(PLAIN_PASSWORD_PREFIX):]
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
