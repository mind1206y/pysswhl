"""年度计划四模块全链路 smoke(TestClient,跑完自动清理)。

覆盖:正式计划/实施单表/实施汇总/营业所发起的读接口、增删改、
提交汇总→通过→复制正式→编号、营业所发起→提交售水→明细、导出与模板。

用法(backend 目录下):
    python -m scripts.smoke_plan
"""

from base64 import b64encode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.plan import GxGxgz, GxJilu, GxJiluTupian, GxUserGxgz, JhSsdb, JhSsdbPz, JhYyfq
from app.models.user import Department, User

client = TestClient(app)
PASS = 0
FAIL = 0
YEAR = 2099
USER = "smoke_plan_test"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def login():
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == USER).first()
        if u is None:
            db.add(User(
                username=USER, password_hash=hash_password("Smoke@12345"),
                password_version=1, real_name="计划smoke", is_superuser=True, is_active=True,
            ))
            db.commit()
    finally:
        db.close()
    pub = serialization.load_pem_public_key(
        client.get("/api/auth/public-key").json()["publicKey"].encode()
    )
    enc = pub.encrypt(
        b"Smoke@12345",
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    r = client.post("/api/auth/login", json={
        "username": USER, "password": b64encode(enc).decode(),
    })
    return {"Authorization": f"Bearer {r.json()['token']}"}


def cleanup(user_id):
    db = SessionLocal()
    try:
        db.query(JhSsdb).filter(JhSsdb.niandu == YEAR).delete()
        db.query(JhYyfq).filter(JhYyfq.niandu == YEAR).delete()
        db.query(GxGxgz).filter(GxGxgz.nd == YEAR).delete()
        db.query(JhSsdbPz).filter(JhSsdbPz.niandu == YEAR).delete()
        f = db.query(GxUserGxgz).filter(
            GxUserGxgz.userid == user_id,
            GxUserGxgz.username == USER,
        ).all()
        for row in f:
            jids = [j.id for j in db.query(GxJilu).filter(GxJilu.guanzhuid == row.id).all()]
            if jids:
                db.query(GxJiluTupian).filter(GxJiluTupian.jiuid.in_(jids)).delete(synchronize_session=False)
                db.query(GxJilu).filter(GxJilu.id.in_(jids)).delete(synchronize_session=False)
            db.delete(row)
        db.commit()
        u = db.query(User).filter(User.username == USER).first()
        if u:
            db.delete(u)
        db.commit()
    finally:
        db.close()


def main():
    h = login()
    me = client.get("/api/auth/me", headers=h).json()
    db = SessionLocal()
    dept = db.query(Department).order_by(Department.id).first().id
    host = db.query(Department).filter(Department.dnnum > 0).order_by(Department.id).first()
    host_id = host.id if host else dept
    db.close()

    # 读接口
    for path in ("/api/plan/dicts", "/api/jhssdb/dicts", "/api/jhsshz/dicts", "/api/jhyyfaqi/dicts"):
        check(f"GET {path}", client.get(path, headers=h).status_code == 200)
    for path, params in (
        ("/api/plan/list", {"nd": 2026, "lb": "更新改造", "size": 2}),
        ("/api/jhssdb/list", {"nd": 2026, "all_zgy": "true", "size": 2}),
        ("/api/jhsshz/list", {"nd": 2026, "jhlb": "更新改造", "size": 2}),
        ("/api/jhyyfaqi/list", {"nd": 2026, "size": 2}),
        ("/api/jhyyfaqi/reported", {"nd": 2026, "size": 2}),
        ("/api/plan/calendar", {"year": 2025, "month": 6}),
    ):
        r = client.get(path, params=params, headers=h)
        check(f"GET {path}", r.status_code == 200 and "rows" in r.json() if "list" in path else r.status_code == 200)

    # 实施单 -> 汇总 -> 通过 -> 复制正式 -> 编号
    payload = {
        "niandu": YEAR, "jhlb": "更新改造", "ssbm": dept, "zb": host_id,
        "zgy": USER, "leibie": "生产类", "xuhao": "9.9", "daibanname": "SMOKE计划A",
        "jine": 12.5, "bz": "测试说明未完成", "startjine": 10,
    }
    r = client.post("/api/jhssdb/create", json=payload, headers=h)
    check("jhssdb 新增", r.json().get("ok"), r.text[:120])
    rid = r.json().get("id")
    r = client.post("/api/jhssdb/status", json={"ids": [rid], "zt": "售水待汇总"}, headers=h)
    check("jhssdb 提交汇总", r.json().get("ok"), r.text[:120])
    r = client.post("/api/jhsshz/status", json={"ids": [rid], "zt": "售水通过"}, headers=h)
    check("jhsshz 通过", r.json().get("ok"), r.text[:120])
    check("变更日志", client.get(f"/api/jhssdb/logs/{rid}", headers=h).json()["total"] > 0)
    r = client.post("/api/jhsshz/copy-to-official", json={"nd": YEAR, "lb": "更新改造"}, headers=h)
    check("复制正式计划", r.json().get("ok"), r.text[:120])
    check("gx_gxgz 落库", len(client.get("/api/plan/list", params={"nd": YEAR}, headers=h).json()["rows"]) == 1)
    check("编序号", client.post("/api/jhsshz/renumber", json={"ids": [rid]}, headers=h).json().get("ok"))

    # 营业所发起 -> 提交售水 -> 明细 -> 删除
    r = client.post("/api/jhyyfaqi/create", json={
        "bmid": dept, "niandu": YEAR, "jhlb": "更新改造", "zgy": USER,
        "faqiname": "SMOKE营业所计划", "jine": 5, "bz": "x",
    }, headers=h)
    check("jhyyfaqi 新增", r.json().get("ok"), r.text[:120])
    yid = r.json().get("id")
    check("jhyyfaqi 提交售水", client.post(
        "/api/jhyyfaqi/submit", json={"ids": [yid]}, headers=h).json().get("ok"))
    detail = client.get(f"/api/jhyyfaqi/detail/{yid}", headers=h).json()
    check("明细当前记录", detail.get("current") and detail["current"]["zt"] == "专管员落实")
    check("jhyyfaqi 删除", client.post(
        "/api/jhyyfaqi/delete", json={"ids": [yid]}, headers=h).json().get("ok"))

    # 正式计划关注/进度
    plan = client.get("/api/plan/list", params={"nd": 2026, "size": 1}, headers=h).json()["rows"][0]
    client.post("/api/plan/follow", json={"ids": [plan["ID"]]}, headers=h)
    jd = client.get("/api/plan/dicts", headers=h).json()["jindu"][0]
    r = client.post("/api/plan/progress", data={
        "gzid": plan["ID"], "guanzhuid": 0, "riqi": "2026-11-09",
        "zhuangtaiid": jd["id"], "miaoshu": "smoke", "fukuan": 1,
    }, headers=h)
    check("添加进度", r.status_code == 200 and r.json().get("ok"))

    # 导出/模板
    for path in (
        "/api/plan/export?nd=2026", "/api/plan/export-progress?nd=2025",
        "/api/jhssdb/export?nd=2026&all_zgy=true", "/api/jhsshz/export?nd=2026",
        "/api/jhyyfaqi/export?nd=2026", "/api/jhyyfaqi/export-reported?nd=2026",
        "/api/jhsshz/template", "/api/jhyyfaqi/template",
    ):
        r = client.get(path, headers=h)
        check(f"GET {path}", r.status_code == 200 and len(r.content) > 1000)

    cleanup(me["id"])
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
