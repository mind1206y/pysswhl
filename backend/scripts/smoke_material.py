"""工单材料库模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_material
"""

import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_mat"
SMOKE_VIEW_USER = "smoke_mat_view"
SMOKE_MAT_NAME = "smoke测试材料(可删除)"


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
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        if u is not None:
            return
        u = User(
            username=username,
            password_hash=hash_password("Smoke@12345"),
            password_version=1,
            real_name=username,
            is_superuser=is_superuser,
            is_active=True,
        )
        if not is_superuser:
            # 挂一个只含 material:view 的角色,验证「非管理权限可入库、不可删材料」
            role = db.query(Role).filter(Role.name == "smoke材料view角色").first()
            if role is None:
                from app.models.user import Permission

                perm = db.query(Permission).filter(Permission.code == "material:view").first()
                role = Role(name="smoke材料view角色", code="smoke_mat_view",
                            permissions=[perm])
                db.add(role)
                db.flush()
            u.roles.append(role)
        db.add(u)
        db.commit()
    finally:
        db.close()


def _cleanup_users():
    from app.db.session import SessionLocal
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        for name in (SMOKE_USER, SMOKE_VIEW_USER):
            u = db.query(User).filter(User.username == name).first()
            if u is not None:
                db.delete(u)
                db.commit()
        role = db.query(Role).filter(Role.name == "smoke材料view角色").first()
        if role is not None:
            db.delete(role)
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
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": b64encode(encrypted).decode()},
    )
    if res.status_code != 200 or "token" not in res.json():
        raise SystemExit(f"登录失败: {res.status_code} {res.text[:200]}")
    return res.json()["token"]


def _jpeg_bytes(color=(200, 30, 30)):
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (200, 200), color).save(buf, "JPEG")
    buf.seek(0)
    return buf


def _cleanup_leftover_materials():
    """兜底清理残留 smoke 材料(含流水)。"""
    from app.db.session import SessionLocal
    from app.models.material import InStockRecord, MaterialImage, MaterialLibrary

    db = SessionLocal()
    try:
        mats = db.query(MaterialLibrary).filter(
            MaterialLibrary.material_name == SMOKE_MAT_NAME).all()
        for m in mats:
            db.query(InStockRecord).filter(InStockRecord.material_id == m.id).delete()
            db.query(MaterialImage).filter(MaterialImage.material_id == m.id).delete()
            db.delete(m)
        db.commit()
    finally:
        db.close()


def main():
    _cleanup_leftover_materials()
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False)
    token = _login(SMOKE_USER)
    h = {"Authorization": f"Bearer {token}"}

    # 1. 字典
    r = client.get("/api/materials/dicts", headers=h)
    check("GET dicts 200", r.status_code == 200)
    d = r.json()
    check("dicts departments>0", len(d.get("departments", [])) > 0)
    check("dicts categories>0", len(d.get("categories", [])) > 0)
    check("dicts specs 含其他", any(s["value"] == "其他" for s in d.get("specs", [])))
    check("dicts materials>0", len(d.get("materials", [])) > 0)
    check("dicts DisplayText 拼别名",
          any("[" in m["DisplayText"] for m in d["materials"]),
          )
    check("perms.manage=True(超管)", d["perms"]["manage"] is True)

    # 2. 库存列表
    r = client.get("/api/materials", headers=h, params={"page": 1, "size": 30})
    check("GET list 200", r.status_code == 200)
    data = r.json()
    check("list total 695", data.get("total") == 695, str(data.get("total")))
    check("rows 30", len(data.get("rows", [])) == 30)
    check("row 含 Images 字段", "Images" in data["rows"][0])
    names = [x["MaterialName"] for x in data["rows"]]
    check("按材料名称排序", names == sorted(names))
    nums = [x["num"] for x in data["rows"]]
    check("num 均为 1 位小数", all(round(float(v), 1) == float(v) for v in nums))

    # 3. 关键字分词搜索(空格多词 AND)
    kw = data["rows"][0]["MaterialName"][:2]
    r = client.get("/api/materials", headers=h, params={"mohu": kw})
    check("keyword search>0", r.json().get("total", 0) > 0)
    r = client.get("/api/materials", headers=h,
                   params={"mohu": f"{kw} 不存在的词xyz"})
    check("多词 AND 命中 0", r.json().get("total") == 0)

    # 4. 大口径 / 部门筛选
    r = client.get("/api/materials", headers=h, params={"dakoujing": "on", "size": 300})
    check("大口径 total 253", r.json().get("total") == 253, str(r.json().get("total")))
    bmid0 = d["departments"][0]["id"]
    r = client.get("/api/materials", headers=h, params={"bmid": bmid0, "size": 1})
    check("bmid filter 200", r.status_code == 200)

    # 5. 库存预警(旧库口径 30 项)
    r = client.get("/api/materials/warning", headers=h)
    check("warning 200", r.status_code == 200)
    check("warning 30 项", len(r.json()) == 30, str(len(r.json())))

    # 6. 进出库记录
    r = client.get("/api/materials/in-out", headers=h, params={"page": 1, "size": 30})
    check("in-out 200", r.status_code == 200)
    io_total = r.json()["total"]
    check("in-out total>0", io_total > 0, str(io_total))
    check("in-out 出库数量为负",
          any(x["Quantity"] < 0 for x in r.json()["rows"]))
    r = client.get("/api/materials/in-out", headers=h,
                   params={"page": 1, "size": 30, "direction": "入库"})
    check("direction=入库 只入库",
          all(x["Direction"] != "出库" for x in r.json()["rows"]))
    r = client.get("/api/materials/in-out", headers=h,
                   params={"page": 1, "size": 30, "direction": "出库"})
    check("direction=出库 只出库",
          all(x["Direction"] == "出库" for x in r.json()["rows"]))
    check("出库 RefNo=工单号",
          all(x["RefNo"] for x in r.json()["rows"]))
    r = client.get("/api/materials/in-out", headers=h,
                   params={"StartDate": "2000-01-01", "EndDate": "2099-12-31"})
    check("date range=全量", r.json()["total"] == io_total)

    # 7. 材料增删改 + 查重
    r = client.post("/api/materials", headers=h, json={
        "MaterialName": SMOKE_MAT_NAME, "Model": "smoke型号", "Spec": "smoke规格",
        "Unit": "个", "biaoji": "sm", "Alias1": "别名甲", "yujing": 5, "Remark": "smoke",
    })
    check("create material 200", r.status_code == 200)
    mid = r.json()["id"]
    r = client.post("/api/materials", headers=h, json={
        "MaterialName": SMOKE_MAT_NAME, "Model": "smoke型号", "Spec": "smoke规格",
        "Unit": "个",
    })
    check("duplicate 400", r.status_code == 400)
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("get material 200", r.status_code == 200)
    check("new num=0 bmid=None", r.json()["num"] == 0)
    r = client.post("/api/materials", headers=h, json={
        "id": mid, "MaterialName": SMOKE_MAT_NAME, "Model": "smoke型号", "Spec": "smoke规格",
        "Unit": "只", "dakoujing": "on", "yujing": 6,
    })
    check("update material 200", r.status_code == 200)
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("update 生效", r.json()["Unit"] == "只" and r.json()["dakoujing"] == "on")

    # 8. 入库 / 编辑 / 删除(库存联动)
    r = client.post("/api/materials/in-stock", headers=h,
                    json={"id": 0, "MaterialId": mid, "Quantity": 3.5, "Remark": "smoke入库1"})
    check("in-stock 1 200", r.status_code == 200)
    r1 = r.json()
    r = client.post("/api/materials/in-stock", headers=h,
                    json={"id": 0, "MaterialId": mid, "Quantity": 2.55, "Remark": "smoke入库2"})
    check("in-stock 2 200", r.status_code == 200)
    r2 = r.json()
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("库存 6.0(1位小数)", abs(r.json()["num"] - 6.0) < 1e-9, str(r.json()["num"]))
    r = client.post("/api/materials/in-stock", headers=h,
                    json={"id": r1["id"], "MaterialId": mid,
                          "Quantity": 4.0, "Remark": "smoke入库1改"})
    check("编辑入库 200", r.status_code == 200, r.text[:120])
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("编辑入库后 num=6.5", abs(r.json()["num"] - 6.5) < 1e-9, str(r.json()["num"]))

    # 9. 库存调整
    r = client.post("/api/materials/adjust", headers=h,
                    json={"materialId": mid, "adjustQuantity": 5, "reason": "smoke调整"})
    check("adjust 200", r.status_code == 200)
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("调整后 num=11.5", abs(r.json()["num"] - 11.5) < 1e-9, str(r.json()["num"]))

    # 10. 盘点提交
    r = client.post("/api/materials/stock-check", headers=h,
                    json={"list": [{"MaterialId": mid, "CheckNum": 10.0}]})
    check("stock-check 200", r.status_code == 200)
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("盘点后 num=10.0", abs(r.json()["num"] - 10.0) < 1e-9, str(r.json()["num"]))

    # 11. 图片上传 / 令牌取图 / 删除
    r = client.post("/api/materials/images", headers=h,
                    params={"materialId": mid},
                    files=[("files", ("a.jpg", _jpeg_bytes((200, 30, 30)), "image/jpeg")),
                           ("files", ("b.png", _jpeg_bytes((30, 200, 30)), "image/png"))])
    check("upload images 200", r.status_code == 200 and r.json().get("count") == 2,
          r.text[:200])
    r = client.get("/api/materials/images", headers=h, params={"id": mid})
    imgs = r.json()
    check("images list 2", len(imgs) == 2)
    r = client.get(imgs[0]["ThumbPath"])
    check("thumb token 200", r.status_code == 200 and len(r.content) > 100)
    r = client.get(imgs[0]["FilePath"])
    check("full token 200", r.status_code == 200 and len(r.content) > 100)
    r = client.get(imgs[0]["FilePath"] + "x")
    check("bad token 401", r.status_code == 401)
    r = client.delete(f"/api/materials/images/{imgs[0]['Id']}", headers=h)
    check("delete image 200", r.status_code == 200)
    r = client.get("/api/materials/images", headers=h, params={"id": mid})
    check("images 剩 1", len(r.json()) == 1)

    # 12. 导出
    r = client.get("/api/materials/export-stock-check", headers=h)
    check("export 盘点表 xlsx", r.status_code == 200
          and r.headers["content-type"].startswith("application/vnd.openxmlformats"))
    r = client.get("/api/materials/export-stock-check", headers=h, params={"dakoujing": "on"})
    check("export 大口径盘点表", r.status_code == 200)
    r = client.get("/api/materials/export-in-out", headers=h, params={"direction": "出库"})
    check("export 进出库 xlsx", r.status_code == 200
          and r.headers["content-type"].startswith("application/vnd.openxmlformats"))

    # 13. 删除入库记录(联动回减)
    # 当前 num=10.0;流水:入库4.0(改)、入库2.55、调整+5、盘点-1.5
    r = client.get("/api/materials/in-out", headers=h,
                   params={"page": 1, "size": 50, "mohu": "smoke测试材料"})
    recs = [x for x in r.json()["rows"] if x["MaterialName"] == SMOKE_MAT_NAME]
    instock_recs = [x for x in recs if x["Direction"] != "出库"]
    for rec in sorted(instock_recs, key=lambda x: x["Id"]):
        rr = client.delete(f"/api/materials/in-stock/{rec['Id']}", headers=h)
        check(f"delete in-stock #{rec['Id']}", rr.status_code == 200, rr.text[:120])
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("删完流水 num=0", abs(r.json()["num"]) < 1e-9, str(r.json()["num"]))

    # 14. view-only 用户权限拦截
    vtoken = _login(SMOKE_VIEW_USER)
    vh = {"Authorization": f"Bearer {vtoken}"}
    r = client.get("/api/materials", headers=vh, params={"size": 1})
    check("view-only 列表 200", r.status_code == 200)
    d["perms"] = {}
    r = client.delete(f"/api/materials/{mid}", headers=vh)
    check("view-only 删除材料 403", r.status_code == 403)
    r = client.post("/api/materials/in-stock", headers=vh,
                    json={"id": 0, "MaterialId": mid, "Quantity": 1})
    check("view-only 入库 200(人人可入库)", r.status_code == 200)
    # 清掉刚才的入库流水
    r = client.get("/api/materials/in-out", headers=vh,
                   params={"page": 1, "size": 5, "mohu": "smoke测试材料"})
    for rec in [x for x in r.json()["rows"]
                if x["MaterialName"] == SMOKE_MAT_NAME and x["Direction"] != "出库"]:
        client.delete(f"/api/materials/in-stock/{rec['Id']}", headers=h)

    # 15. 无 token
    r = client.get("/api/materials")
    check("no token 401/403", r.status_code in (401, 403))

    # 16. 删除材料(无流水时可删)
    r = client.delete(f"/api/materials/{mid}", headers=h)
    check("delete material 200", r.status_code == 200, r.text[:120])
    r = client.get(f"/api/materials/{mid}", headers=h)
    check("deleted -> 404", r.status_code == 404)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup_leftover_materials()
        _cleanup_users()
