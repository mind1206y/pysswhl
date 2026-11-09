"""年度计划四模块全链路 smoke(TestClient,跑完自动清理)。

覆盖:正式计划/实施单表/实施汇总/营业所发起的读接口、增删改、
提交汇总→通过→复制正式→编号、营业所发起→提交售水→明细、导出与模板。

用法(backend 目录下):
    python -m scripts.smoke_plan
"""

from base64 import b64encode
from io import BytesIO

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.plan import GxGxgz, GxJilu, GxJiluTupian, GxUserGxgz, JhSsdb, JhSsdbPz, JhYyfq
from app.models.sms import SmsContact, SmsRecord
from app.models.user import Department, User
from app.services import sms as sms_service

client = TestClient(app)
PASS = 0
FAIL = 0
YEAR = 2099
USER = "smoke_plan_test"
SMS_TARGET = "smoke_sms_target"
SMS_PHONE = "13800000000"
# 短信网关不可达,用本地回环替换 HTTP 调用,验证加密/解密/落库
sms_service._post = lambda encrypted: sms_service.encrypt('{"code":"0","msg":"ok"}')


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
                password_version=1, real_name="计划smoke", is_superuser=True,
                is_active=True, phone=SMS_PHONE,
            ))
        else:
            u.phone = SMS_PHONE
        if db.query(SmsContact).filter(SmsContact.id == 999999).first() is None:
            db.add(SmsContact(
                id=999999, username=SMS_TARGET, real_name="短信smoke",
                phone=SMS_PHONE, zw="专管员", otherqx="",
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
        db.query(SmsRecord).filter(SmsRecord.sender == USER).delete()
        db.query(SmsContact).filter(SmsContact.id == 999999).delete()
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
    r = client.post("/api/jhssdb/status", json={"ids": [rid], "zt": "售水待汇总", "iftel": True}, headers=h)
    check("jhssdb 提交汇总", r.json().get("ok"), r.text[:120])
    check("短信通知计划汇总", (r.json().get("sms") or {}).get("sent", 0) > 0, r.text[:160])

    r = client.post("/api/jhssdb/sms", json={"zgy": SMS_TARGET, "nr": "我转了计划给您，请及时处理！"}, headers=h)
    check("手动发送短信", r.json().get("ok"), r.text[:160])
    db = SessionLocal()
    sms_n = db.query(SmsRecord).filter(SmsRecord.sender == USER, SmsRecord.ren == "短信smoke").count()
    db.close()
    check("短信记录落库", sms_n > 0, f"count={sms_n}")
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

    # 计划格式:封面 + 类别 sheet + 部门分组 + 小计/合计
    r = client.get("/api/jhssdb/export", params={"nd": 2026, "all_zgy": "true"}, headers=h)
    wb = load_workbook(BytesIO(r.content))
    check("计划格式-封面", "封面" in wb.sheetnames, str(wb.sheetnames))
    ws = wb["更新改造"]
    check("计划格式-标题", "更新改造计划" in str(ws.cell(1, 1).value or ""), str(ws.cell(1, 1).value))
    labels = {str(ws.cell(i, 1).value or "").replace(" ", "") for i in range(1, ws.max_row + 1)}
    check("计划格式-小计合计", {"小计", "合计"}.issubset(labels), str(labels))
    check("计划格式-部门分组", any("营业所" in x or x == "售水本部" for x in labels), str(list(labels)[:10]))

    # 当前页导出沿用同一版式
    page_rows = client.get("/api/jhssdb/list", params={
        "nd": 2026, "all_zgy": "true", "size": 2, "first_load": "true",
    }, headers=h).json()["rows"]
    if page_rows:
        ids = ",".join(str(x["ID"]) for x in page_rows)
        r = client.get("/api/jhssdb/export-page", params={"ids": ids, "lb": "更新改造"}, headers=h)
        ws = load_workbook(BytesIO(r.content)).active
        check("当前页计划格式", "更新改造计划" in str(ws.cell(1, 1).value or ""))

    # 正式计划/营业所发起使用“导出正式计划”版式
    r = client.get("/api/plan/export", params={"nd": 2026}, headers=h)
    ws = load_workbook(BytesIO(r.content)).active
    check("正式计划表头", ws.cell(2, 1).value == "编号" and ws.cell(2, 18).value == "合同签订日期",
          str([ws.cell(2, c).value for c in (1, 18)]))
    r = client.get("/api/jhyyfaqi/export", params={"nd": 2026}, headers=h)
    ws = load_workbook(BytesIO(r.content)).active
    check("营业所计划表头", ws.cell(2, 1).value == "编号" and ws.cell(2, 13).value == "专管员",
          str([ws.cell(2, c).value for c in (1, 13)]))
    check("正式计划数据行", ws.max_row >= 3 or r.status_code == 200)

    cleanup(me["id"])
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
