"""短信发送记录页 smoke(TestClient,跑完自动清理)。

覆盖:
- GET /api/sms-records:分页/模糊搜索(mohu 六字段)/倒序
- 权限:超管 200;无权限用户 403;补授 legacy_sms_view 后 200

用法(backend 目录下):
    python -m scripts.smoke_sms_records
"""

from base64 import b64encode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient
from pymysql.converters import escape_str  # noqa: F401  仅确保 pymysql 已装

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)
PASS = 0
FAIL = 0
SUPER = "smoke_sms_super"
PLAIN = "smoke_sms_plain"
PASSWD = "Smoke@12345"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _headers(username: str) -> dict:
    pub = serialization.load_pem_public_key(
        client.get("/api/auth/public-key").json()["publicKey"].encode()
    )
    enc = pub.encrypt(
        PASSWD.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None),
    )
    r = client.post("/api/auth/login", json={
        "username": username, "password": b64encode(enc).decode(),
    })
    return {"Authorization": f"Bearer {r.json()['token']}"}


def setup_users():
    db = SessionLocal()
    try:
        for username, is_super in ((SUPER, True), (PLAIN, False)):
            u = db.query(User).filter(User.username == username).first()
            if u is None:
                db.add(User(username=username, password_hash=hash_password(PASSWD),
                            password_version=1, real_name=username,
                            is_active=True, is_superuser=is_super))
            else:
                u.password_hash, u.password_version = hash_password(PASSWD), 1
                u.is_active, u.is_superuser = True, is_super
        db.commit()
    finally:
        db.close()


def cleanup():
    db = SessionLocal()
    try:
        for username in (SUPER, PLAIN):
            u = db.query(User).filter(User.username == username).first()
            if u:
                db.delete(u)
        db.commit()
    finally:
        db.close()


def grant_role(username: str, role_code: str):
    """给临时用户绑定已有角色(照 grant_sms_perms 的 user_role 写法)。"""
    import pymysql

    from app.core.config import settings
    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            uid = cur.fetchone()[0]
            cur.execute("SELECT id FROM roles WHERE code=%s", (role_code,))
            row = cur.fetchone()
            if row:
                cur.execute("INSERT IGNORE INTO user_role (user_id, role_id) VALUES (%s,%s)",
                            (uid, row[0]))
        conn.commit()
    finally:
        conn.close()


def main():
    setup_users()
    try:
        hs = _headers(SUPER)
        r = client.get("/api/sms-records", headers=hs)
        check("超管 GET 200", r.status_code == 200, r.text[:200])
        data = r.json()
        check("返回 total/rows", "total" in data and "rows" in data, str(data)[:120])
        check("历史数据已迁移(total>1000)", data["total"] > 1000, str(data["total"]))
        check("按 riqi 倒序",
              all((a["riqi"] or "") >= (b["riqi"] or "") for a, b in zip(data["rows"], data["rows"][1:])))
        check("行含全部字段",
              all(k in data["rows"][0] for k in ("id", "lb", "riqi", "nr", "tel", "ren", "zt", "sender")))

        r = client.get("/api/sms-records", headers=hs, params={"page": 2, "size": 30})
        data2 = r.json()
        check("翻页不重叠", data2["rows"] and data2["rows"][0]["id"] != data["rows"][0]["id"])

        r = client.get("/api/sms-records", headers=hs, params={"mohu": "13800"})
        check("mohu 搜索 200", r.status_code == 200, r.text[:120])

        # 无权限 403
        hp = _headers(PLAIN)
        r = client.get("/api/sms-records", headers=hp)
        check("无权限用户 403", r.status_code == 403, str(r.status_code))

        # 补授 legacy_sms_view 后 200
        grant_role(PLAIN, "legacy_sms_view")
        r = client.get("/api/sms-records", headers=hp)
        check("授权后 200", r.status_code == 200, r.text[:200])
    finally:
        cleanup()
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
