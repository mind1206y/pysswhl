"""材料结算单查看模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_jiesuan
覆盖:超管/仅 view 权限、总数与 DB 口径一致、关键字过滤、分页、字段结构。
"""

from base64 import b64encode

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_js"
SMOKE_VIEW_USER = "smoke_js_view"
SMOKE_NO_PERM = "smoke_js_noperm"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _mk_user(username, perm_code=None):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import Permission, Role, User

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is not None:
            return
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=perm_code is None, is_active=True)
        if perm_code is not None:
            code = f"smoke_js_role_{perm_code.replace(':', '_')}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == perm_code).first()
                role = Role(name=f"smoke结算查看{perm_code}", code=code, permissions=[perm])
                db.add(role)
                db.flush()
            user.roles.append(role)
        db.add(user)
        db.commit()
    finally:
        db.close()


def _login(username):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pub_pem = client.get("/api/auth/public-key").json()["publicKey"].encode()
    pubkey = serialization.load_pem_public_key(pub_pem)
    encrypted = pubkey.encrypt(
        "Smoke@12345".encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None),
    )
    res = client.post("/api/auth/login", json={
        "username": username, "password": b64encode(encrypted).decode()})
    if res.status_code != 200 or "token" not in res.json():
        raise SystemExit(f"登录失败: {res.status_code} {res.text[:200]}")
    return res.json()["token"]


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        for name in (SMOKE_USER, SMOKE_VIEW_USER, SMOKE_NO_PERM):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_js_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def main():
    _mk_user(SMOKE_USER, None)
    _mk_user(SMOKE_VIEW_USER, "jiesuan:view")
    _mk_user(SMOKE_NO_PERM, "jiesuandan:view")
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}
        hn = {"Authorization": f"Bearer {_login(SMOKE_NO_PERM)}"}

        from app.db.session import SessionLocal
        from app.models.lingliao import LingLiao, LingLiaoDetail

        db = SessionLocal()
        try:
            expected = (
                db.query(LingLiaoDetail)
                .join(LingLiao, LingLiaoDetail.lingliaoid == LingLiao.id)
                .filter(LingLiao.shzt.in_((2, 5, 6)))
                .count()
            )
        finally:
            db.close()

        r = client.get("/api/jiesuan/details", headers=h, params={"page": 1, "size": 20})
        check("GET details 200", r.status_code == 200, r.text[:200])
        data = r.json()
        check("总数与 DB 口径一致", data["total"] == expected,
              f"{data['total']} != {expected}")
        check("首页返回 20 条", len(data["rows"]) == min(20, expected),
              str(len(data["rows"])))
        first = data["rows"][0]
        check("字段结构完整", all(k in first for k in (
            "danno", "gongyingshang", "llname", "model", "spec", "unit",
            "renum", "jiesuannum", "shengyu", "jsrq", "id", "MaterialId", "beizhu",
        )), str(sorted(first.keys())))
        check("剩余可结算=可结算-已结算",
              abs(float(first["shengyu"])
                  - (float(first["renum"]) - float(first["jiesuannum"]))) < 1e-6)

        r = client.get("/api/jiesuan/details", headers=h, params={"page": 1, "size": 5})
        check("size=5 生效", len(r.json()["rows"]) <= 5, str(len(r.json()["rows"])))

        keyword = first["llname"] or first["danno"]
        r = client.get("/api/jiesuan/details", headers=h,
                       params={"page": 1, "size": 20, "keyword": keyword})
        kw = r.json()
        check("关键字过滤命中", r.status_code == 200 and kw["total"] >= 1,
              str(kw.get("total")))
        if kw["rows"]:
            row = kw["rows"][0]
            hit = keyword in "".join(str(row.get(k) or "") for k in (
                "llname", "danno", "gongyingshang", "materialname", "beizhu"))
            check("关键字命中字段", hit, str(row))

        r = client.get("/api/jiesuan/details", headers=hv)
        check("仅 jiesuan:view 用户可访问", r.status_code == 200, str(r.status_code))
        r = client.get("/api/jiesuan/details", headers=hn)
        check("无 jiesuan:view 用户 403", r.status_code == 403, str(r.status_code))

        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
