"""领料申请模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_lingliao
覆盖:字典/材料下拉/保存/列表/明细/提交/审核/修改实发(库存增减)/反审核拦截/
     驳回/作废/删除/导出材料需求单/临时附件转存/列表附件上传下载删除/权限越权拦截。
"""

import io
import time

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_ll"
SMOKE_VIEW_USER = "smoke_ll_view"
ORDER_IDS = []
MATERIAL_ID = None
STOCK_BEFORE = 0.0


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
            role = db.query(Role).filter(Role.code == "smoke_ll_view_role").first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == "lingliao:view").first()
                role = Role(name="smoke领料view角色", code="smoke_ll_view_role",
                            permissions=[perm])
                db.add(role)
                db.flush()
            user.roles.append(role)
        db.add(user)
        db.commit()
    finally:
        db.close()


def _login(username):
    from base64 import b64encode

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


def _stock_num():
    from app.db.session import SessionLocal
    from app.models.material import MaterialLibrary

    db = SessionLocal()
    try:
        material = db.get(MaterialLibrary, MATERIAL_ID)
        return round(float(material.num or 0), 1) if material else None
    finally:
        db.close()


def _cleanup():
    from pathlib import Path

    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.lingliao import LingLiao, LingLiaoDetail, LingLiaoFile
    from app.models.material import InStockRecord, MaterialLibrary
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        for order_id in ORDER_IDS:
            order = db.get(LingLiao, order_id)
            if order is None:
                continue
            for detail in db.query(LingLiaoDetail).filter(
                    LingLiaoDetail.lingliaoid == order_id).all():
                for record in db.query(InStockRecord).filter(
                        InStockRecord.lingliao_detail_id == detail.id).all():
                    material = db.get(MaterialLibrary, detail.material_id)
                    if material is not None:
                        material.num = round(
                            float(material.num or 0) - float(record.quantity or 0), 1)
                    db.delete(record)
                db.delete(detail)
            for file in db.query(LingLiaoFile).filter(
                    LingLiaoFile.lingliaoid == order_id).all():
                path = Path(settings.UPLOAD_DIR) / file.filepath
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                db.delete(file)
            db.delete(order)
        db.commit()
        for name in (SMOKE_USER, SMOKE_VIEW_USER):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        role = db.query(Role).filter(Role.code == "smoke_ll_view_role").first()
        if role is not None:
            db.delete(role)
            db.commit()
    finally:
        db.close()


def main():
    global MATERIAL_ID, STOCK_BEFORE
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False)
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}

        # 1. 字典 / 材料
        r = client.get("/api/lingliao/dicts", headers=h)
        check("GET dicts 200", r.status_code == 200)
        d = r.json()
        check("超管 audit=true", d["perms"]["audit"] is True)
        check("状态字典 7 项", len(d["statuses"]) == 7, str(len(d["statuses"])))
        rv = client.get("/api/lingliao/dicts", headers=hv)
        check("仅 view 用户 audit=false", rv.json()["perms"]["audit"] is False)
        r = client.get("/api/lingliao/materials", headers=h)
        check("GET materials 200 且非空", r.status_code == 200 and len(r.json()) > 0)
        MATERIAL_ID = r.json()[0]["MaterialId"]
        STOCK_BEFORE = _stock_num()

        # 2. 新增保存
        payload = {
            "id": 0, "sqriqi": "2026-11-09", "gongyingshang": "SMOKE供应商",
            "shuoming": "smoke测试", "Details": [{
                "id": 0, "MaterialId": MATERIAL_ID,
                "materialname": r.json()[0]["materialname"],
                "model": r.json()[0]["model"], "spec": r.json()[0]["spec"],
                "unit": r.json()[0]["unit"], "num": 3, "beizhu": "smoke",
            }], "files": [],
        }
        r = client.post("/api/lingliao/orders/save", headers=h, json=payload)
        check("POST save 新建 200", r.status_code == 200 and r.json().get("success"),
              r.text[:200])
        order_id = r.json()["id"]
        ORDER_IDS.append(order_id)

        # 3. 列表 / 明细 / 回显
        r = client.get("/api/lingliao/orders", headers=h,
                       params={"page": 1, "size": 10, "keyword": "SMOKE供应商"})
        check("列表按供应商搜索命中", r.status_code == 200 and r.json()["total"] >= 1)
        row = next(x for x in r.json()["rows"] if x["id"] == order_id)
        check("列表状态草稿/单号 LL 前缀", row["shzt"] == 0 and row["danno"].startswith("LL"))
        r = client.get(f"/api/lingliao/orders/{order_id}/details", headers=h)
        check("明细返回 1 条", r.status_code == 200 and len(r.json()) == 1)
        detail_id = r.json()[0]["id"]
        r = client.get(f"/api/lingliao/orders/{order_id}", headers=h)
        check("编辑回显含 Details/files", "Details" in r.json() and "files" in r.json())

        # 4. 越权:仅 view 用户不能改别人的单 / 审核
        payload2 = dict(payload)
        payload2["id"] = order_id
        r = client.post("/api/lingliao/orders/save", headers=hv, json=payload2)
        check("仅 view 用户改他人单 403", r.status_code == 403, str(r.status_code))
        r = client.post(f"/api/lingliao/orders/{order_id}/audit", headers=hv)
        check("仅 view 用户审核 403", r.status_code == 403, str(r.status_code))

        # 5. 提交 / 审核 / 实发库存
        r = client.post(f"/api/lingliao/orders/{order_id}/submit", headers=h)
        check("提交草稿 200", r.status_code == 200)
        r = client.post(f"/api/lingliao/orders/{order_id}/audit", headers=h)
        check("审核 200", r.status_code == 200)
        r = client.get(f"/api/lingliao/orders/{order_id}", headers=h)
        check("审核后状态=2", r.json()["shzt"] == 2)
        r = client.post(f"/api/lingliao/orders/{order_id}/details/{detail_id}/renum",
                        headers=h, json={"renum": 2})
        check("修改实发 200", r.status_code == 200, r.text[:200])
        check("库存增加 2", _stock_num() == round(STOCK_BEFORE + 2, 1),
              f"{STOCK_BEFORE} -> {_stock_num()}")
        r = client.post(f"/api/lingliao/orders/{order_id}/reverse-audit", headers=h)
        check("有实发后反审核被拦截", r.status_code == 400, str(r.status_code))
        r = client.post(f"/api/lingliao/orders/{order_id}/details/{detail_id}/renum",
                        headers=h, json={"renum": 99})
        check("实发超申请数量被拦截", r.status_code == 400)

        # 6. 导出
        r = client.get(f"/api/lingliao/orders/{order_id}/export", headers=h)
        check("导出 200", r.status_code == 200)
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.active
        check("导出 Sheet 标题/表头", ws["A1"].value == "材料需求单"
              and ws["A7"].value == "序号" and ws["B7"].value == "材料名称")

        # 7. 附件:列表直传 / 下载 / 删除
        r = client.post(f"/api/lingliao/orders/{order_id}/files", headers=h,
                        files={"file": ("smoke.txt", b"hello lingliao", "text/plain")})
        check("列表附件上传 200", r.status_code == 200 and r.json()["success"],
              r.text[:200])
        file_id = r.json()["file"]["id"]
        token_url = r.json()["file"]["downloadUrl"]
        r = client.get(token_url)
        check("列表附件短令牌下载 200", r.status_code == 200 and r.content == b"hello lingliao")
        r = client.delete(f"/api/lingliao/files/{file_id}", headers=h)
        check("列表附件删除 200", r.status_code == 200)

        # 8. 临时附件:上传 -> 保存转存
        temp = client.post("/api/lingliao/files/temp", headers=h,
                           files={"file": ("temp.txt", b"temp lingliao", "text/plain")})
        check("临时附件上传 200", temp.status_code == 200 and temp.json()["success"],
              temp.text[:200])
        temp_info = temp.json()
        r = client.get(temp_info["downloadUrl"])
        check("临时附件下载 200", r.status_code == 200 and r.content == b"temp lingliao")
        r = client.post("/api/lingliao/orders/save", headers=h, json={
            **payload, "gongyingshang": "SMOKE附件供应商"})
        temp_order_id = r.json()["id"]
        ORDER_IDS.append(temp_order_id)
        payload3 = dict(payload)
        payload3["id"] = temp_order_id
        payload3["Details"] = client.get(
            f"/api/lingliao/orders/{temp_order_id}/details", headers=h).json()
        payload3["files"] = [{
            "Id": 0, "filename": temp_info["filename"],
            "filepath": temp_info["filepath"], "filesize": temp_info["filesize"],
        }]
        r = client.post("/api/lingliao/orders/save", headers=h, json=payload3)
        check("编辑保存临时附件转存 200", r.status_code == 200, r.text[:200])
        files = client.get(f"/api/lingliao/orders/{temp_order_id}/files", headers=h).json()
        check("转存后附件 1 条", len(files) == 1, str(len(files)))
        client.post(f"/api/lingliao/orders/{temp_order_id}/cancel", headers=h)
        client.delete(f"/api/lingliao/orders/{temp_order_id}", headers=h)
        ORDER_IDS.remove(temp_order_id)

        # 9. 草稿作废/删除
        r = client.post("/api/lingliao/orders/save", headers=h, json={
            **payload, "gongyingshang": "SMOKE作废供应商"})
        draft_id = r.json()["id"]
        ORDER_IDS.append(draft_id)
        r = client.post(f"/api/lingliao/orders/{draft_id}/cancel", headers=h)
        check("草稿作废 200", r.status_code == 200)
        r = client.delete(f"/api/lingliao/orders/{draft_id}", headers=h)
        check("作废后删除 200", r.status_code == 200)
        ORDER_IDS.remove(draft_id)

        # 10. 驳回(另一个草稿提交后驳回)
        r = client.post("/api/lingliao/orders/save", headers=h, json={
            **payload, "gongyingshang": "SMOKE驳回供应商"})
        reject_id = r.json()["id"]
        ORDER_IDS.append(reject_id)
        client.post(f"/api/lingliao/orders/{reject_id}/submit", headers=h)
        r = client.post(f"/api/lingliao/orders/{reject_id}/reject", headers=h)
        check("驳回 200", r.status_code == 200)
        r = client.get(f"/api/lingliao/orders/{reject_id}", headers=h)
        check("驳回后状态=3", r.json()["shzt"] == 3)

        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
