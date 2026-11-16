"""用户表迁移 smoke 测试:验证旧系统账号在新系统能直接登录(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_users

覆盖:
- 数据完整性:199 个旧账号全部到位、用户名唯一、密码哈希非空、部门/角色已挂、停用账号 4 个
- 真实旧哈希:直接用库里的 bb_user 原始哈希校验(不写数据),证明 MD5/PBKDF2 两种老格式都认
- 登录链路:旧 MD5 账号、旧 PBKDF2 账号、手机号登录、停用账号 403、初始密码强制改密
- 透明升级:旧格式账号登录一次后,库里应变成 Argon2id(v1)且原密码仍可用
"""

from base64 import b64encode
from datetime import datetime

import pymysql
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    CURRENT_PASSWORD_VERSION,
    LEGACY_MD5_VERSION,
    LEGACY_PBKDF2_VERSION,
    hash_password,
    verify_password,
)
from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
TEMP_PREFIX = "smoke_u_"
TEMP_USERS = [TEMP_PREFIX + s for s in ("md5", "pbkdf2", "phone", "off", "init")]
SMOKE_PWD = "Smoke@12345"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def db():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )


def old_md5_unicode(plain):
    """旧系统无盐 MD5:.NET Encoding.Unicode + 逐字节 ToString("x")(丢前导零)"""
    import hashlib

    digest = hashlib.md5(plain.encode("utf-16-le")).digest()
    return "".join(format(b, "x") for b in digest)


def old_pbkdf2(plain, iterations=20000):
    """旧系统 PasswordHasher 的存储格式(旧源码 whl.common/PasswordHasher.cs)"""
    import base64
    import hashlib
    import os

    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha1", plain.encode("utf-8"), salt, iterations, 32)
    return "pbkdf2${}${}${}".format(
        iterations, base64.b64encode(salt).decode(), base64.b64encode(derived).decode()
    )


def encrypt(pubkey, plain):
    return b64encode(pubkey.encrypt(
        plain.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None),
    )).decode()


def login(ident, plain, pubkey):
    return client.post("/api/auth/login", json={"username": ident, "password": encrypt(pubkey, plain)})


def seed_temp_users(cur):
    """按旧系统两种哈希各造一个账号,外加手机号/停用/初始密码三个场景账号"""
    rows = [
        (TEMP_PREFIX + "md5", old_md5_unicode(SMOKE_PWD), LEGACY_MD5_VERSION, "", "", 1, 0),
        (TEMP_PREFIX + "pbkdf2", old_pbkdf2(SMOKE_PWD), LEGACY_PBKDF2_VERSION, "", "", 1, 0),
        (TEMP_PREFIX + "phone", old_md5_unicode(SMOKE_PWD), LEGACY_MD5_VERSION, "", "18800001111", 1, 0),
        (TEMP_PREFIX + "off", old_md5_unicode(SMOKE_PWD), LEGACY_MD5_VERSION, "", "", 0, 0),
        (TEMP_PREFIX + "init", hash_password(settings.INITIAL_PASSWORD), CURRENT_PASSWORD_VERSION,
         "", "", 1, 1),
    ]
    for username, pwd_hash, ver, zw, phone, active, must in rows:
        cur.execute(
            "INSERT INTO users (username, password_hash, password_version, real_name, phone, zw, "
            "is_active, is_superuser, must_change_password, failed_attempts, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,0,NOW())",
            (username, pwd_hash, ver, "smoke测试", phone, zw, active, must),
        )


def cleanup():
    conn = db()
    try:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(TEMP_USERS))
        cur.execute(f"SELECT id FROM users WHERE username IN ({placeholders})", TEMP_USERS)
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            cur.execute(f"DELETE FROM user_role WHERE user_id IN ({ph})", ids)
            cur.execute(f"DELETE FROM user_department WHERE user_id IN ({ph})", ids)
            cur.execute(f"DELETE FROM users WHERE id IN ({ph})", ids)
        conn.commit()
        if ids:
            print(f"  已清理 {len(ids)} 个测试账号")
    finally:
        conn.close()


def main():
    print("== 1. 迁移数据完整性")
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE is_superuser = 0")
    normal = cur.fetchone()[0]
    check("普通账号数 >= 198", normal >= 198, f"实际 {normal}")
    cur.execute("SELECT username, COUNT(*) c FROM users GROUP BY username HAVING c > 1")
    check("用户名无重复", not cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM users WHERE password_hash IS NULL OR password_hash = ''")
    check("密码哈希无空值", cur.fetchone()[0] == 0)
    cur.execute("SELECT COUNT(*) FROM users WHERE is_active = 0")
    inactive = cur.fetchone()[0]
    check("停用账号 = 4(旧 zw 停用/退休)", inactive == 4, f"实际 {inactive}")
    cur.execute(
        "SELECT COUNT(*) FROM users u WHERE u.is_superuser = 0 "
        "AND NOT EXISTS (SELECT 1 FROM user_department ud WHERE ud.user_id = u.id)"
    )
    no_dept = cur.fetchone()[0]
    check("非超管账号都有部门", no_dept == 0, f"{no_dept} 个缺部门")
    cur.execute("SELECT COUNT(*) FROM roles WHERE LEFT(code, 7) = 'legacy_'")
    check("legacy_* 权限角色已建", cur.fetchone()[0] > 0)
    cur.execute(
        "SELECT COUNT(*) FROM roles r WHERE LEFT(r.code, 7) = 'legacy_' "
        "AND NOT EXISTS (SELECT 1 FROM role_permission rp WHERE rp.role_id = r.id)"
    )
    orphan = cur.fetchone()[0]
    check("legacy 角色都挂上了权限码(否则用户拿到空权限)", orphan == 0, f"{orphan} 个空角色")
    cur.execute("SELECT password_version, COUNT(*) FROM users GROUP BY password_version ORDER BY 1")
    dist = dict(cur.fetchall())
    print(f"     密码版本分布: {dist}(2=旧PBKDF2, 3=旧MD5, 1=Argon2id)")
    check("存在旧格式账号(2/3)", dist.get(2, 0) + dist.get(3, 0) > 0)

    print("== 2. 真实旧哈希直接校验(不写库)")
    cur.execute("SELECT username, password_hash FROM users WHERE password_version = 3 LIMIT 50")
    md5_samples = [(u, h) for u, h in cur.fetchall() if h]
    check("库里有旧 MD5 账号", bool(md5_samples))
    # 旧库里 陈毅清2 的口令是 123456,用他的真实哈希验证(log 过一次后会变成 v1,故按存储版本校验)
    cur.execute("SELECT password_hash, password_version FROM users WHERE username = '陈毅清2'")
    row = cur.fetchone()
    if row and row[0]:
        h, ver = row
        check(f"真实账号口令校验通过(陈毅清2/123456, version={ver})",
              verify_password("123456", h, ver))
        check("真实账号错误口令被拒", not verify_password("654321", h, ver))
    cur.execute("SELECT password_hash FROM users WHERE password_version = 2 LIMIT 1")
    row = cur.fetchone()
    if row and row[0]:
        check("旧 PBKDF2 哈希不认错口令", not verify_password("definitely-wrong", row[0],
                                                             LEGACY_PBKDF2_VERSION))
        check("旧 PBKDF2 哈希格式可解析", row[0].startswith("pbkdf2$"))

    print("== 3. 登录链路")
    seed_temp_users(cur)
    conn.commit()
    pub = serialization.load_pem_public_key(
        client.get("/api/auth/public-key").json()["publicKey"].encode()
    )

    res = login(TEMP_PREFIX + "md5", SMOKE_PWD, pub)
    check("旧 MD5 账号登录成功", res.status_code == 200 and "token" in res.json(), res.text[:120])
    md5_headers = {"Authorization": f"Bearer {res.json().get('token', '')}"}

    cur.execute("SELECT password_version, password_hash FROM users WHERE username = %s",
                (TEMP_PREFIX + "md5",))
    ver, phash = cur.fetchone()
    check("登录后旧 MD5 已升级为 v1", ver == CURRENT_PASSWORD_VERSION, f"version={ver}")
    check("升级后的哈希可校验原口令", verify_password(SMOKE_PWD, phash))

    res = login(TEMP_PREFIX + "pbkdf2", SMOKE_PWD, pub)
    check("旧 PBKDF2 账号登录成功", res.status_code == 200, res.text[:120])

    res = login("18800001111", SMOKE_PWD, pub)
    check("手机号登录成功", res.status_code == 200, res.text[:120])

    res = login(TEMP_PREFIX + "md5", "wrong-pass", pub)
    check("错误口令被拒(400)", res.status_code == 400, res.text[:120])

    res = login(TEMP_PREFIX + "off", SMOKE_PWD, pub)
    check("停用账号被拒(403)", res.status_code == 403, res.text[:120])

    res = login(TEMP_PREFIX + "init", settings.INITIAL_PASSWORD, pub)
    ok = res.status_code == 200 and res.json()["user"]["must_change_password"] is True
    check("初始密码账号可登录且要求改密", ok, res.text[:120])

    res = client.get("/api/auth/me", headers=md5_headers)
    check("登录后可取用户信息", res.status_code == 200 and "permissions" in res.json(),
          res.text[:120])

    print("== 4. 旧系统账号权限抽样")
    cur.execute(
        "SELECT u.username, COUNT(ur.role_id) n, GROUP_CONCAT(r.code) FROM users u "
        "JOIN user_role ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id "
        "WHERE u.username IN ('林春','陈毅清2','陈泽彬') GROUP BY u.id"
    )
    for username, n, codes in cur.fetchall():
        sample = (codes or "")[:80]
        print(f"     {username}: {n} 个角色 → {sample}")
    conn.close()

    # 真实账号(旧库口令 123456)走完整登录,确认权限码真的下发给前端
    res = login("陈毅清2", "123456", pub)
    check("真实旧账号可登录", res.status_code == 200, res.text[:120])
    if res.status_code == 200:
        perms = res.json()["user"]["permissions"]
        check("真实账号拿到权限码", bool(perms), f"permissions={perms}")
        headers = {"Authorization": f"Bearer {res.json()['token']}"}
        check("有权限的接口可访问", client.get("/api/plan/list", headers=headers).status_code == 200)
        check("无权限的接口仍 403",
              client.get("/api/workorder/orders", headers=headers).status_code == 403)

    cleanup()

    print(f"\n通过 {PASS},失败 {FAIL}")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
