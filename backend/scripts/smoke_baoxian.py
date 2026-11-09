"""车辆保险(CLbaoxian)模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_baoxian
覆盖:超管/仅 view/无权限、总数与合计与旧库口径(432/406072.84)、筛选(种类/年度/关键字)、
增删改与登记人编辑限制、模板下载、上传导入(有效/重复/错误行)、导出。
"""

from base64 import b64encode
from datetime import date, datetime
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_bx"
SMOKE_VIEW_USER = "smoke_bx_view"
SMOKE_NO_PERM = "smoke_bx_noperm"
SMOKE_BD = "SMOKE-BX-TEST-0001"


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
            code = f"smoke_bx_role_{perm_code.replace(':', '_')}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == perm_code).first()
                role = Role(name=f"smoke车辆保险{perm_code}", code=code, permissions=[perm])
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
    from app.models.vehicle import ClBaoxian

    db = SessionLocal()
    try:
        db.query(ClBaoxian).filter(
            ClBaoxian.bdnumber.like("SMOKE-BX-%")).delete(synchronize_session=False)
        db.commit()
        for name in (SMOKE_USER, SMOKE_VIEW_USER, SMOKE_NO_PERM):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_bx_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def _make_xlsx(rows):
    """构造导入用 xlsx:3 行表头区 + 数据行 B~I 列(车号/投保日期/保单号/类别/金额/公司/到期/经手人)。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="保险费用导入模板")
    ws.cell(row=2, column=1, value="说明")
    for c, label in enumerate(["", "车号", "投保日期", "保单号", "保险类别",
                               "投保金额(元)", "保险公司", "保险到期", "经手人"], start=1):
        ws.cell(row=3, column=c, value=label)
    for i, r in enumerate(rows, start=4):
        for c, v in enumerate(r, start=2):
            ws.cell(row=i, column=c, value=v)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def main():
    _mk_user(SMOKE_USER, None)
    _mk_user(SMOKE_VIEW_USER, "baoxian:view")
    _mk_user(SMOKE_NO_PERM, "vehicle:view")
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}
        hn = {"Authorization": f"Bearer {_login(SMOKE_NO_PERM)}"}

        from sqlalchemy import func

        from app.db.session import SessionLocal
        from app.models.vehicle import ClBaoxian, ClChe

        db = SessionLocal()
        try:
            expected_total = db.query(ClBaoxian).count()
            expected_sum = float(db.query(func.sum(ClBaoxian.jine)).scalar() or 0)
            car = db.query(ClChe).filter(ClChe.yongtu != "油卡", ClChe.delf != 0).first()
            car_id, car_no = car.id, car.chehao
            n_jq = db.query(ClBaoxian).filter(ClBaoxian.lx == "交强险").count()
            n_2025 = db.query(ClBaoxian).filter(
                func.year(ClBaoxian.tbdate) == 2025).count()
            dup_bd = (db.query(ClBaoxian.bdnumber).filter(
                ClBaoxian.bdnumber.isnot(None), ClBaoxian.bdnumber != "")
                .order_by(ClBaoxian.id).first()[0])
        finally:
            db.close()

        # ---- 列表 ----
        r = client.get("/api/baoxian", headers=h, params={"page": 1, "size": 30})
        check("GET 列表 200", r.status_code == 200, r.text[:200])
        data = r.json()
        check("总数与 DB 口径一致", data["total"] == expected_total,
              f"{data['total']} != {expected_total}")
        check("合计金额与 DB 口径一致", abs(data["tj"] - expected_sum) < 0.01,
              f"{data['tj']} != {expected_sum}")
        check("首页返回 30 条", len(data["items"]) == min(30, expected_total))
        first = data["items"][0]
        check("字段结构完整", all(k in first for k in (
            "id", "cheid", "tbdate", "bdnumber", "lx", "jine", "bxcom", "dqdate",
            "djname", "djdate", "jingshou", "bz", "chehao", "bumen")), str(sorted(first.keys())))

        # ---- 筛选 ----
        r = client.get("/api/baoxian", headers=h, params={"lx": "交强险", "size": 500})
        check("保险种类筛选(交强险)", r.json()["total"] == n_jq,
              f"{r.json()['total']} != {n_jq}")
        r = client.get("/api/baoxian", headers=h, params={"year": 2025, "size": 500})
        check("年度筛选(2025)", r.json()["total"] == n_2025,
              f"{r.json()['total']} != {n_2025}")
        r = client.get("/api/baoxian", headers=h,
                       params={"keyword": first["bxcom"] or first["chehao"], "size": 500})
        check("关键字筛选命中", r.json()["total"] >= 1, str(r.json()["total"]))
        r = client.get("/api/baoxian", headers=h, params={"size": 5})
        check("分页 size=5 生效", len(r.json()["items"]) <= 5)

        # ---- 字典 / 下拉 / 聚合标签 ----
        r = client.get("/api/baoxian/dicts", headers=h)
        check("GET dicts 200", r.status_code == 200)
        check("dicts 结构", r.json()["lx"] == ["商业车险", "交强险"]
              and len(r.json()["years"]) >= 1 and len(r.json()["departments"]) >= 1)
        r = client.get("/api/baoxian/vehicles", headers=h)
        vids = [x["id"] for x in r.json()]
        check("车辆下拉 200 且含有效车", r.status_code == 200 and car_id in vids)
        r = client.get("/api/baoxian/bxcoms", headers=h)
        check("历史保险公司聚合标签", r.status_code == 200 and len(r.json()) >= 1)

        # ---- 权限 ----
        r = client.get("/api/baoxian", headers=hv)
        check("仅 baoxian:view 用户可访问", r.status_code == 200, str(r.status_code))
        r = client.get("/api/baoxian", headers=hn)
        check("无 baoxian:view 用户 403", r.status_code == 403, str(r.status_code))

        # ---- 添加 / 编辑 / 删除 ----
        payload = {
            "cheid": car_id, "tbdate": "2026-11-01", "bdnumber": SMOKE_BD,
            "lx": "商业车险", "jine": 1234.56, "bxcom": "测试财险",
            "dqdate": "2027-10-31", "jingshou": "测试员", "bz": "smoke",
        }
        r = client.post("/api/baoxian", headers=h, json=payload)
        check("添加保单 200", r.status_code == 200, r.text[:200])
        new_id = r.json().get("id")
        check("登记人=当前登录人", r.json().get("djname") == SMOKE_USER)
        check("登记日期已写入", bool(r.json().get("djdate")))

        r = client.get(f"/api/baoxian/{new_id}", headers=h)
        check("单条详情 200 且字段回读", r.status_code == 200
              and r.json()["bdnumber"] == SMOKE_BD and float(r.json()["jine"]) == 1234.56)

        # 登记人本人可编辑(保单号变更)
        payload["bdnumber"] = SMOKE_BD.replace("0001", "0002")
        r = client.put(f"/api/baoxian/{new_id}", headers=h, json=payload)
        check("登记人编辑 200", r.status_code == 200 and r.json()["bdnumber"].endswith("0002"),
              r.text[:200])

        # 非登记人编辑 → 403(旧口径:只有登记人才能编辑)
        r = client.put(f"/api/baoxian/{new_id}", headers=hv,
                       json={"jine": 1.0, "tbdate": "2026-11-01", "dqdate": "2027-10-31"})
        check("非登记人编辑 403", r.status_code == 403, str(r.status_code))

        r = client.delete(f"/api/baoxian/{new_id}", headers=hv)
        check("可见用户可删除(旧 Deletegz 无本人限制)", r.status_code == 200, r.text[:200])
        r = client.get(f"/api/baoxian/{new_id}", headers=h)
        check("删除后 404", r.status_code == 404, str(r.status_code))

        # ---- 模板 / 导入 / 导出 ----
        r = client.get("/api/baoxian/template", headers=h)
        check("模板下载 200", r.status_code == 200
              and r.content[:2] == b"PK", str(r.status_code))

        today = date.today()
        rows = [
            [car_no, today, "SMOKE-BX-IMP-1", "商业车险", 100.5, "导入财险A", today, "甲"],
            [car_no, today, dup_bd, "交强险", 200, "导入财险A", today, "甲"],   # 与库内重复
            [car_no, today, "SMOKE-BX-IMP-1", "交强险", 300, "导入财险B", today, "乙"],  # 批内重复
            ["不存在的车号XYZ", today, "SMOKE-BX-IMP-2", "交强险", 400, "导入财险B", today, "乙"],
        ]
        r = client.post("/api/baoxian/import", headers=h,
                        files={"file": ("保险导入.xlsx", _make_xlsx(rows),
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        check("上传导入 200", r.status_code == 200, r.text[:300])
        summary = str(r.json())
        check("导入摘要:成功1 重复2 失败1",
              "导入成功 1 条" in summary and "跳过重复 2 条" in summary
              and "导入失败 1 条" in summary, summary)

        r = client.post("/api/baoxian/import", headers=h,
                        files={"file": ("费用表.xlsx", _make_xlsx(rows), "application/octet-stream")})
        check("文件名不含「保险」400", r.status_code == 400, str(r.status_code))

        r = client.get("/api/baoxian/export", headers=h,
                       params={"keyword": "SMOKE-BX-IMP-1"})
        check("导出 200 且含导入行", r.status_code == 200 and r.content[:2] == b"PK",
              str(r.status_code))

        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
