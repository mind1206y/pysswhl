"""车辆管理短信功能 smoke(TestClient,跑完自动清理)。

覆盖:
- 手动发送 POST /api/vehicles/{id}/sms:年检提醒(固定文案发驾驶员+车管)、
  其他提醒(部门-操作员前缀,驾驶员记「车辆提醒」、车管记所选类别)、内容为空 400
- 定时任务 run_nianjian_job:进入 7 天窗口的车辆发「7天紧急提醒」并推进
  ReminderLevel/LastReminderDate;已标注年检进入 90 天窗口的重置进新周期
- 短信网关用本地回环替换(验证加密/解密/落库,不真发)

用法(backend 目录下):
    python -m scripts.smoke_vehicle_sms
"""

from base64 import b64encode
from datetime import date, datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.sms import SmsRecord
from app.models.user import Department, User
from app.models.vehicle import ClChe
from app.services import sms as sms_service
from app.services.nianjian_job import SMS_SWITCH_NAME, run_nianjian_job
from app.services.vehicle_common import _add_months_safe

client = TestClient(app)
PASS = 0
FAIL = 0
USER = "smoke_veh_sms"
MANAGER = "smoke_veh_gz"
PASSWD = "Smoke@12345"
CHEHAO = "闽Asmoke"
PHONE = "13800000001"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


# 短信网关不可达,用本地回环替换 HTTP 调用
sms_service._post = lambda encrypted: sms_service.encrypt('{"code":"0","msg":"ok"}')


def _token_headers(username: str) -> dict:
    pub = serialization.load_pem_public_key(
        client.get("/api/auth/public-key").json()["publicKey"].encode()
    )
    enc = pub.encrypt(
        PASSWD.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    r = client.post("/api/auth/login", json={"username": username, "password": b64encode(enc).decode()})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def login():
    db = SessionLocal()
    try:
        dept = db.query(Department).order_by(Department.id).first()
        for username, zw in ((USER, ""), (MANAGER, "设备管理员")):
            u = db.query(User).filter(User.username == username).first()
            if u is None:
                db.add(User(
                    username=username, password_hash=hash_password(PASSWD),
                    password_version=1, real_name=username, is_active=True,
                    is_superuser=(username == USER), phone=PHONE, zw=zw,
                    departments=[dept],
                ))
            else:
                u.phone, u.zw = PHONE, zw
                u.departments = [dept]
        db.commit()
    finally:
        db.close()
    return _token_headers(USER)


def cleanup(sms_id_floor=0):
    db = SessionLocal()
    try:
        db.query(SmsRecord).filter(
            (SmsRecord.id > sms_id_floor)
            | (SmsRecord.nr.like(f"%{CHEHAO}%"))
            | (SmsRecord.sender == USER)
        ).delete(synchronize_session=False)
        db.query(ClChe).filter(ClChe.chehao.like(f"{CHEHAO}%")).delete(synchronize_session=False)
        from app.models.plan import ConsolTb
        db.query(ConsolTb).filter(ConsolTb.conName == SMS_SWITCH_NAME).delete(synchronize_session=False)
        for username in (USER, MANAGER):
            u = db.query(User).filter(User.username == username).first()
            if u:
                db.delete(u)
        db.commit()
    finally:
        db.close()


def make_car(db, *, chuchang=None, inspected=False):
    car = ClChe(
        delf=1, lx="小型轿车", chehao=CHEHAO, jiashiyuan="smoke司机",
        telphone=PHONE, bmid=db.query(Department).order_by(Department.id).first().id,
        bm="", chuchang=chuchang, spzt="审批通过",
    )
    if inspected:
        car.IsInspected = True
        car.InspectionDate = date.today()
    db.add(car)
    db.commit()
    db.refresh(car)
    return car


def main():
    h = login()
    db = SessionLocal()
    # 记录 sms_record 现有最大 id:定时任务会给真实车辆落记录,统一按 id 快照清理
    sms_id_floor = db.query(SmsRecord.id).order_by(SmsRecord.id.desc()).first()
    sms_id_floor = sms_id_floor[0] if sms_id_floor else 0
    try:
        car = make_car(db, chuchang=date(2020, 6, 1))
        car_id = car.id

        # ---- 手动发送:年检提醒(固定文案,发驾驶员 + 车管) ----
        r = client.post(f"/api/vehicles/{car.id}/sms", headers=h, json={"lb": "年检提醒", "nr": ""})
        check("POST sms 年检提醒 200", r.status_code == 200, r.text[:200])
        db.commit()  # 结束当前快照事务,读取 TestClient 已提交的数据
        data = r.json()
        check("年检提醒发 2 条", data.get("total") == 2, str(data))
        recs = [x for x in db.query(SmsRecord).filter(SmsRecord.lb == "年检提醒").all() if CHEHAO in x.nr]
        check("年检提醒落库 2 条", len(recs) == 2, str(len(recs)))
        check("文案含固定语句", all("年检日期截止下月底" in x.nr for x in recs))
        check("记录带 (售水信息小助手) 前缀", all(x.nr.startswith("(售水信息小助手)") for x in recs))
        check("发送人为登录人", all(x.sender == USER for x in recs))
        check("发送成功状态", all("code" in (x.zt or "") for x in recs), str([x.zt for x in recs]))

        # ---- 手动发送:其他提醒(驾驶员记「车辆提醒」+ 车管记所选类别) ----
        r = client.post(f"/api/vehicles/{car.id}/sms", headers=h,
                        json={"lb": "违章提醒", "nr": "请尽快处理违章"})
        check("POST sms 其他提醒 200", r.status_code == 200, r.text[:200])
        db.commit()
        driver = (db.query(SmsRecord).filter(SmsRecord.lb == "车辆提醒", SmsRecord.nr.like(f"%{CHEHAO}%"))
                  .order_by(SmsRecord.id.desc()).first())
        check("驾驶员类别记「车辆提醒」", driver is not None and "请尽快处理违章" in (driver.nr or ""))
        check("前缀「-用户名给您发送提示信息:（车号）」",
              driver is not None and f"-{USER}给您发送提示信息:（{CHEHAO}）" in (driver.nr or ""),
              driver.nr if driver else "")
        gz = (db.query(SmsRecord).filter(SmsRecord.lb == "违章提醒", SmsRecord.nr.like(f"%{CHEHAO}%"))
              .order_by(SmsRecord.id.desc()).first())
        check("车管类别记所选 lb", gz is not None)

        # ---- 其他提醒:内容为空 400 ----
        r = client.post(f"/api/vehicles/{car.id}/sms", headers=h, json={"lb": "违章提醒", "nr": "  "})
        check("空内容 400", r.status_code == 400, str(r.status_code))
        db.commit()

        # ---- 定时任务:下次年检日落在 7 天内 → 3 级紧急提醒 + 推进状态 ----
        db.query(SmsRecord).filter(SmsRecord.id > sms_id_floor).delete(synchronize_session=False)
        db.commit()
        # 小型轿车车龄<10 年周期 24 个月:反推注册日使下次年检日 = 今天 + 3 天
        chuchang = _add_months_safe(date.today() + timedelta(days=3), -24)
        car2 = make_car(db, chuchang=chuchang)
        car2_id = car2.id
        db.commit()
        summary = run_nianjian_job(db)
        db.commit()
        check("任务返回 summary", all(k in summary for k in ("vehicles", "reset", "sent", "results")))
        hit = [r_ for r_ in summary["results"] if r_.get("id") == car2.id and r_.get("kind") == "3级提醒"]
        check("7 天窗口车辆命中 3 级提醒", bool(hit), str(summary["results"])[:200])
        rec3 = (db.query(SmsRecord).filter(SmsRecord.lb == "车辆年检提醒", SmsRecord.nr.like(f"%{CHEHAO}%"))
                .order_by(SmsRecord.id.desc()).first())
        check("3 级文案照旧", rec3 is not None and "（7天紧急提醒）" in (rec3.nr or "") and CHEHAO in rec3.nr,
              rec3.nr if rec3 else "")
        car2 = db.get(ClChe, car2_id)
        check("ReminderLevel 推进到 3", car2.ReminderLevel == 3, str(car2.ReminderLevel))
        check("LastReminderDate 落库", car2.LastReminderDate is not None)
        # 同级别今年已发过 → 重跑不再发送
        before = db.query(SmsRecord).filter(SmsRecord.id > sms_id_floor).count()
        run_nianjian_job(db)
        db.commit()
        after = db.query(SmsRecord).filter(SmsRecord.id > sms_id_floor).count()
        check("同年度同级别不重发", after == before, f"{before} -> {after}")

        # ---- 已标注年检 + 下次年检日进入 90 天窗口 → 重置进新周期 ----
        car = db.get(ClChe, car_id)
        car.IsInspected = True
        car.InspectionDate = date.today()
        car.NextInspectionDate = date.today() + timedelta(days=10)
        car.ReminderLevel = 1
        db.commit()
        summary2 = run_nianjian_job(db)
        db.commit()
        car = db.get(ClChe, car_id)
        check("进入 90 天窗口的已年检车被重置", car.IsInspected is False and car.ReminderLevel == 0,
              f"IsInspected={car.IsInspected}, level={car.ReminderLevel}")
        check("重置计数 > 0", summary2["reset"] >= 1, str(summary2["reset"]))

        # ---- 提醒短信开关:仅超管可读写;关闭后定时任务跳过 ----
        r = client.get("/api/vehicles/sms-switch", headers=h)
        check("GET sms-switch 超管 200 默认开",
              r.status_code == 200 and r.json()["enabled"] is True, r.text[:120])
        r = client.put("/api/vehicles/sms-switch", headers=h, json={"enabled": False})
        check("PUT sms-switch 关闭", r.status_code == 200 and r.json()["enabled"] is False, r.text[:120])
        r = client.get("/api/vehicles/sms-switch", headers=h)
        check("GET 关闭态生效", r.status_code == 200 and r.json()["enabled"] is False, r.text[:120])
        db.commit()  # 结束快照事务,读到 TestClient 提交的开关值
        summary3 = run_nianjian_job(db)
        db.commit()
        check("开关关闭 → 任务跳过不发短信",
              summary3.get("skipped") is True and summary3["sent"] == 0, str(summary3))
        # 非超管 403
        hm = _token_headers(MANAGER)
        r = client.get("/api/vehicles/sms-switch", headers=hm)
        check("GET sms-switch 非超管 403", r.status_code == 403, str(r.status_code))
        r = client.put("/api/vehicles/sms-switch", headers=hm, json={"enabled": False})
        check("PUT sms-switch 非超管 403", r.status_code == 403, str(r.status_code))
        # 恢复开启(落库行由 cleanup 清理)
        r = client.put("/api/vehicles/sms-switch", headers=h, json={"enabled": True})
        check("PUT sms-switch 恢复开启", r.status_code == 200 and r.json()["enabled"] is True, r.text[:120])
    finally:
        cleanup(sms_id_floor)
    print(f"\n{PASS} passed, {FAIL} failed")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
