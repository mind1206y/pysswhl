"""领料结算模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_jiesuandan
覆盖:字典/新增结算单/列表/可结算明细/新增明细(状态与库存联动)/修改明细/
      越权拦截/导出销售结算表/采购申请单+验收单/打印数据/附件上传下载删除/
      删除明细(领料状态回滚)/删除结算单。
"""

import io
from base64 import b64encode

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_jsd"
SMOKE_VIEW_USER = "smoke_jsd_view"
SUPPLIER = "SMOKE结算供应商"
SETTLE_IDS = []
LINGLIAO_ID = None
MATERIAL_ID = None
STOCK_BEFORE = 0.0
LASTDANJIA_BEFORE = None


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _mk_user(username, is_superuser):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import Permission, Role, User

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is not None:
            return
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=is_superuser, is_active=True)
        if not is_superuser:
            role = db.query(Role).filter(Role.code == "smoke_jsd_view_role").first()
            if role is None:
                perm = db.query(Permission).filter(
                    Permission.code == "jiesuandan:view").first()
                role = Role(name="smoke结算view角色", code="smoke_jsd_view_role",
                            permissions=[perm])
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


def _db_state():
    from app.db.session import SessionLocal
    from app.models.jiesuandan import JiesuanCailiao
    from app.models.lingliao import LingLiao, LingLiaoDetail

    db = SessionLocal()
    try:
        detail = (db.query(LingLiaoDetail)
                  .filter(LingLiaoDetail.lingliaoid == LINGLIAO_ID).first())
        main = db.get(LingLiao, LINGLIAO_ID)
        return {
            "jiesuannum": round(float(detail.jiesuannum or 0), 4) if detail else None,
            "jiesuanzt": detail.jiesuanzt if detail else None,
            "lingliao_shzt": main.shzt if main else None,
        }
    finally:
        db.close()


def _cleanup():
    from pathlib import Path

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.jiesuandan import CailiaoFujian, JiesuanCailiao, JiesuanDetail
    from app.models.lingliao import LingLiao, LingLiaoDetail
    from app.models.material import InStockRecord, MaterialLibrary
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        for order_id in SETTLE_IDS:
            for detail in db.query(JiesuanDetail).filter(
                    JiesuanDetail.jiesuanid == order_id).all():
                db.delete(detail)
            for row in db.query(CailiaoFujian).filter(
                    CailiaoFujian.jiesuancailiao_id == order_id).all():
                try:
                    (Path(settings.UPLOAD_DIR) / row.filepath).unlink(missing_ok=True)
                except OSError:
                    pass
                db.delete(row)
            order = db.get(JiesuanCailiao, order_id)
            if order is not None:
                db.delete(order)
        # 恢复 smoke 领料单造成的库存与结算数量
        if LINGLIAO_ID:
            for detail in db.query(LingLiaoDetail).filter(
                    LingLiaoDetail.lingliaoid == LINGLIAO_ID).all():
                for record in db.query(InStockRecord).filter(
                        InStockRecord.lingliao_detail_id == detail.id).all():
                    material = db.get(MaterialLibrary, detail.material_id)
                    if material is not None:
                        material.num = round(
                            float(material.num or 0) - float(record.quantity or 0), 1)
                    db.delete(record)
                db.delete(detail)
            order = db.get(LingLiao, LINGLIAO_ID)
            if order is not None:
                db.delete(order)
        if MATERIAL_ID:
            material = db.get(MaterialLibrary, MATERIAL_ID)
            if material is not None:
                material.num = STOCK_BEFORE
                material.lastdanjia = LASTDANJIA_BEFORE
        db.commit()
        for name in (SMOKE_USER, SMOKE_VIEW_USER):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        role = db.query(Role).filter(Role.code == "smoke_jsd_view_role").first()
        if role is not None:
            db.delete(role)
            db.commit()
    finally:
        db.close()


def main():
    global LINGLIAO_ID, MATERIAL_ID, STOCK_BEFORE, LASTDANJIA_BEFORE
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False)
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}

        # 1. 字典
        r = client.get("/api/jiesuandan/dicts", headers=h)
        check("GET dicts 200", r.status_code == 200, r.text[:200])
        d = r.json()
        check("超管 manage=true", d["perms"]["manage"] is True)
        rv = client.get("/api/jiesuandan/dicts", headers=hv)
        check("仅 view 用户 manage=false", rv.json()["perms"]["manage"] is False)
        r = client.get("/api/jiesuandan/create-init", headers=h)
        check("create-init 单号 JS 前缀",
              r.status_code == 200 and r.json()["jiesuandanno"].startswith("JS"))

        # 2. 造一张已审核、有实发的领料单(供应商 = SUPPLIER)
        from app.db.session import SessionLocal
        from app.models.material import MaterialLibrary

        mats = client.get("/api/lingliao/materials", headers=h).json()
        material = mats[0]
        MATERIAL_ID = material["MaterialId"]
        db = SessionLocal()
        try:
            m = db.get(MaterialLibrary, MATERIAL_ID)
            STOCK_BEFORE = round(float(m.num or 0), 1)
            LASTDANJIA_BEFORE = m.lastdanjia
        finally:
            db.close()
        payload = {
            "id": 0, "sqriqi": "2026-11-09", "gongyingshang": SUPPLIER,
            "shuoming": "smoke结算", "Details": [{
                "id": 0, "MaterialId": MATERIAL_ID,
                "materialname": material["materialname"],
                "model": material["model"], "spec": material["spec"],
                "unit": material["unit"], "num": 10, "beizhu": "smoke",
            }], "files": [],
        }
        r = client.post("/api/lingliao/orders/save", headers=h, json=payload)
        LINGLIAO_ID = r.json()["id"]
        ling_detail_id = client.get(
            f"/api/lingliao/orders/{LINGLIAO_ID}/details", headers=h
        ).json()[0]["id"]
        client.post(f"/api/lingliao/orders/{LINGLIAO_ID}/submit", headers=h)
        client.post(f"/api/lingliao/orders/{LINGLIAO_ID}/audit", headers=h)
        client.post(
            f"/api/lingliao/orders/{LINGLIAO_ID}/details/{ling_detail_id}/renum",
            headers=h, json={"renum": 10},
        )
        state = _db_state()
        check("领料单已审核且有实发", state["lingliao_shzt"] == 2, str(state))

        # 3. 新增结算单
        r = client.post("/api/jiesuandan/orders/save", headers=h, json={
            "id": 0, "jiesuandanno": "", "gongyingshang": SUPPLIER,
            "jiesuanriqi": "2026-11-09", "beizhu": "smoke结算单",
        })
        check("新增结算单 200", r.status_code == 200 and r.json().get("success"),
              r.text[:200])
        order_id = r.json()["id"]
        SETTLE_IDS.append(order_id)
        order = client.get(f"/api/jiesuandan/orders/{order_id}", headers=h).json()
        check("新增总额=0", float(order["zonge"]) == 0, str(order["zonge"]))

        # 4. 列表 / 可结算明细
        r = client.get("/api/jiesuandan/orders", headers=h,
                       params={"page": 1, "size": 10, "keyword": SUPPLIER})
        check("列表按供应商命中", r.status_code == 200 and r.json()["total"] >= 1)
        row = next(x for x in r.json()["rows"] if x["id"] == order_id)
        check("列表单号/创建人/附件数", row["jiesuandanno"].startswith("JS")
              and row["createuser"] == SMOKE_USER and row["fujianCount"] == 0)
        r = client.get("/api/jiesuandan/candidates", headers=h,
                       params={"page": 1, "size": 20, "gongyingshang": SUPPLIER})
        check("可结算明细命中", r.status_code == 200 and r.json()["total"] >= 1,
              r.text[:200])
        cand = next(x for x in r.json()["rows"] if x["id"] == ling_detail_id)
        check("剩余可结算=10", float(cand["shengyu"]) == 10, str(cand["shengyu"]))
        r = client.get("/api/jiesuandan/candidates", headers=h,
                       params={"gongyingshang": "不存在供应商XYZ"})
        check("供应商过滤隔离", r.json()["total"] == 0)

        # 5. 新增结算明细
        r = client.post(f"/api/jiesuandan/orders/{order_id}/details", headers=h,
                        json={"Details": [{
                            "LingliaoDetailId": ling_detail_id, "Num": 3, "Danjia": 5,
                        }]})
        check("新增明细 200", r.status_code == 200 and r.json().get("success"),
              r.text[:200])
        order = client.get(f"/api/jiesuandan/orders/{order_id}", headers=h).json()
        check("结算总额=15", float(order["zonge"]) == 15, str(order["zonge"]))
        state = _db_state()
        check("领料已结算=3 部分结算", state["jiesuannum"] == 3 and state["jiesuanzt"] == 1,
              str(state))
        check("领料主表=部分结算(5)", state["lingliao_shzt"] == 5, str(state))
        details = client.get(f"/api/jiesuandan/orders/{order_id}/details", headers=h).json()
        check("明细 1 条且金额=15", len(details) == 1
              and float(details[0]["jine"]) == 15, str(details[:1]))
        detail_id = details[0]["id"]
        cand2 = client.get("/api/jiesuandan/candidates", headers=h,
                           params={"gongyingshang": SUPPLIER}).json()
        cand = next(x for x in cand2["rows"] if x["id"] == ling_detail_id)
        check("剩余可结算=7", float(cand["shengyu"]) == 7, str(cand["shengyu"]))

        # 6. 越权:仅 view 用户不能改他人单
        r = client.post(f"/api/jiesuandan/orders/{order_id}/details", headers=hv,
                        json={"Details": [{
                            "LingliaoDetailId": ling_detail_id, "Num": 1, "Danjia": 1,
                        }]})
        check("非创建人新增明细 403", r.status_code == 403, str(r.status_code))
        r = client.delete(f"/api/jiesuandan/orders/{order_id}", headers=hv)
        check("非创建人删除结算单 403", r.status_code == 403, str(r.status_code))
        r = client.get("/api/jiesuandan/orders", headers=hv)
        check("仅 view 用户可查列表", r.status_code == 200)

        # 7. 修改明细
        r = client.put(f"/api/jiesuandan/details/{detail_id}", headers=h,
                       json={"num": 5, "danjia": 4})
        check("修改明细 200", r.status_code == 200, r.text[:200])
        order = client.get(f"/api/jiesuandan/orders/{order_id}", headers=h).json()
        check("修改后总额=20", float(order["zonge"]) == 20, str(order["zonge"]))
        check("修改后已结算=5", _db_state()["jiesuannum"] == 5, str(_db_state()))
        r = client.put(f"/api/jiesuandan/details/{detail_id}", headers=h,
                       json={"num": 99, "danjia": 4})
        check("超可结算数量被拦截", r.status_code == 400)

        # 8. 导出销售结算表
        r = client.get(f"/api/jiesuandan/orders/{order_id}/export", headers=h)
        check("导出销售结算表 200", r.status_code == 200, r.text[:200])
        ws = load_workbook(io.BytesIO(r.content)).active
        check("销售结算表标题/表头", ws["A1"].value == "销售结算表"
              and ws["A4"].value == "序号" and ws["H4"].value == "数量")

        # 9. 采购申请单/验收单/打印数据
        r = client.get(f"/api/jiesuandan/orders/{order_id}/cg-excel", headers=h,
                       params={"type": 1, "sgbm": "测试部门", "sgyy": "测试原因"})
        check("下载申请单 200", r.status_code == 200, r.text[:200])
        ws = load_workbook(io.BytesIO(r.content)).active
        check("申请单标题含申请部门", "物资采购申请单" in str(ws["A1"].value)
              and ws["A4"].value == "序号")
        check("申请单底部三栏签字 审批/审核/申请人",
              ws["A7"].value == "审批：" and ws["C7"].value == "审核："
              and ws["F7"].value == "申请人：",
              str([ws.cell(row=7, column=c).value for c in range(1, 9)]))
        r = client.get(f"/api/jiesuandan/orders/{order_id}/cg-excel", headers=h,
                       params={"type": 2, "sgbm": "测试部门"})
        check("下载验收单 200", r.status_code == 200, r.text[:200])
        ws = load_workbook(io.BytesIO(r.content)).active
        check("验收单表头含验收情况", "物资采购验收单" in str(ws["A1"].value)
              and ws["H3"].value == "验收情况")
        check("验收单明细验收情况=完成", ws["H4"].value == "完成",
              str(ws["H4"].value))
        r = client.get(f"/api/jiesuandan/orders/{order_id}/print-data", headers=h,
                       params={"sgbm": "测试部门", "sgyy": "测试原因"})
        check("打印数据 200 且有明细", r.status_code == 200
              and r.json()["main"]["id"] == order_id and len(r.json()["rows"]) == 1,
              r.text[:200])

        # 10. 附件
        r = client.post(f"/api/jiesuandan/orders/{order_id}/attachments", headers=h,
                        files={"files": ("smoke.txt", b"hello jiesuandan", "text/plain")})
        check("附件上传 200", r.status_code == 200 and r.json().get("success"),
              r.text[:200])
        atts = client.get(f"/api/jiesuandan/orders/{order_id}/attachments", headers=h).json()
        check("附件列表 1 条", len(atts) == 1, str(len(atts)))
        r = client.get(atts[0]["downloadUrl"])
        check("附件短令牌下载 200", r.status_code == 200
              and r.content == b"hello jiesuandan")
        r = client.post(f"/api/jiesuandan/orders/{order_id}/attachments", headers=h,
                        files={"files": ("evil.aspx", b"x", "application/octet-stream")})
        check("脚本类附件被拦截", r.status_code == 400)
        r = client.delete(f"/api/jiesuandan/attachments/{atts[0]['id']}", headers=h)
        check("附件删除 200", r.status_code == 200)

        # 11. 删除明细 -> 领料状态回滚
        r = client.delete(f"/api/jiesuandan/details/{detail_id}", headers=h)
        check("删除明细 200", r.status_code == 200, r.text[:200])
        order = client.get(f"/api/jiesuandan/orders/{order_id}", headers=h).json()
        check("删除明细后总额=0", float(order["zonge"]) == 0, str(order["zonge"]))
        state = _db_state()
        check("删除后领料已结算=0 未结算",
              state["jiesuannum"] == 0 and state["jiesuanzt"] == 0
              and state["lingliao_shzt"] == 2, str(state))

        # 12. 删除结算单
        r = client.delete(f"/api/jiesuandan/orders/{order_id}", headers=h)
        check("删除结算单 200", r.status_code == 200, r.text[:200])
        r = client.get(f"/api/jiesuandan/orders/{order_id}", headers=h)
        check("删除后 404", r.status_code == 404)
        SETTLE_IDS.remove(order_id)

        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
