"""路面修复管理模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_roadrepair
"""

import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_road"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def login():
    """临时超管账号登录(密码走 RSA-OAEP(SHA-256) 加密,与前端一致),跑完删除。"""
    from base64 import b64encode

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == SMOKE_USER).first()
        if u is None:
            u = User(
                username=SMOKE_USER,
                password_hash=hash_password("Smoke@12345"),
                password_version=1,
                real_name="路面修复smoke",
                is_superuser=True,
                is_active=True,
            )
            db.add(u)
            db.commit()
    finally:
        db.close()

    pub_pem = client.get("/api/auth/public-key").json()["publicKey"].encode()
    pubkey = serialization.load_pem_public_key(pub_pem)
    encrypted = pubkey.encrypt(
        "Smoke@12345".encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    res = client.post(
        "/api/auth/login",
        json={"username": SMOKE_USER, "password": b64encode(encrypted).decode()},
    )
    if res.status_code != 200 or "token" not in res.json():
        raise SystemExit(f"登录失败: {res.status_code} {res.text[:200]}")
    return res.json()["token"]


def cleanup_user():
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == SMOKE_USER).first()
        if u is not None:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def main():
    token = login()
    h = {"Authorization": f"Bearer {token}"}

    # 1. 字典
    r = client.get("/api/roadrepair/dicts", headers=h)
    check("GET dicts 200", r.status_code == 200)
    d = r.json()
    check("dicts companies 4", len(d.get("companies", [])) == 4)
    check("dicts banzu 14", len(d.get("banzu", [])) == 14, str(len(d.get("banzu", []))))

    # 2. 列表
    r = client.get("/api/roadrepair", headers=h, params={"page": 1, "size": 20})
    check("GET list 200", r.status_code == 200)
    data = r.json()
    check("list total 508", data.get("total") == 508, str(data.get("total")))
    check("list items 20", len(data.get("items", [])) == 20)
    check("item has attachment_count", "attachment_count" in data["items"][0])
    first = data["items"][0]
    check("默认倒序", data["items"][0]["id"] >= data["items"][-1]["id"])

    # 3. 筛选
    r = client.get("/api/roadrepair", headers=h,
                   params={"keyword": first["address"][:4] if first["address"] else "路"})
    check("keyword filter 200", r.status_code == 200)
    r = client.get("/api/roadrepair", headers=h, params={"progress": "已完账"})
    check("progress filter", r.json().get("total", 0) > 0)
    r = client.get("/api/roadrepair", headers=h, params={"company": "公路局"})
    check("company filter", r.json().get("total", 0) > 0)
    r = client.get("/api/roadrepair", headers=h,
                   params={"start": "2000-01-01", "end": "2099-01-01"})
    check("date range = all", r.json().get("total") == 508)
    r = client.get("/api/roadrepair", headers=h,
                   params={"sort": "total", "order": "desc"})
    items = r.json()["items"]
    totals = [i["total"] or 0 for i in items]
    check("sort total desc", totals == sorted(totals, reverse=True))

    # 4. 新增 -> 详情 -> 进度 -> 更新 -> 批量 -> 删除
    payload = {
        "address": "测试地址(可删除)",
        "company": "大市政",
        "banzu": d["banzu"][0] if d["banzu"] else "",
        "dig_date": "2026-11-09",
        "area": 10.5,
        "final_area": 11.2,
        "price": 100,
        "total": 1120,
        "reason": "smoke",
        "remark": "smoke-remark",
    }
    r = client.post("/api/roadrepair", headers=h, json=payload)
    check("create 200", r.status_code == 200)
    new_id = r.json().get("id")
    check("create returns id", bool(new_id))

    r = client.get(f"/api/roadrepair/{new_id}", headers=h)
    check("getById 200", r.status_code == 200)
    check("create default 新建", r.json()["current_progress"] == "新建")

    r = client.get(f"/api/roadrepair/{new_id}/progress", headers=h)
    check("progress history 1条(新建)", len(r.json()) == 1 and r.json()[0]["progress"] == "新建")

    # 编辑不改状态
    r = client.put(f"/api/roadrepair/{new_id}", headers=h,
                   json={**payload, "address": "测试地址(改)"})
    check("update 200", r.status_code == 200)
    r = client.get(f"/api/roadrepair/{new_id}", headers=h)
    check("update address", r.json()["address"] == "测试地址(改)")
    check("update 不改状态", r.json()["current_progress"] == "新建")

    # 进度更新
    r = client.post(f"/api/roadrepair/{new_id}/progress", headers=h,
                    json={"progress": "已报账"})
    check("updateProgress 200", r.status_code == 200)
    r = client.get(f"/api/roadrepair/{new_id}/progress", headers=h)
    plist = r.json()
    check("progress history 2条", len(plist) == 2)
    check("进度倒序(最新在前)", plist[0]["progress"] == "已报账")

    # 批量
    r = client.post("/api/roadrepair/progress-batch", headers=h,
                    json={"ids": [new_id], "progress": "已付款"})
    check("batch progress 200", r.status_code == 200 and r.json()["updated"] == 1)
    r = client.get(f"/api/roadrepair/{new_id}", headers=h)
    check("batch 后状态已付款", r.json()["current_progress"] == "已付款")

    # 5. 附件
    r = client.post(f"/api/roadrepair/{new_id}/attachments", headers=h,
                    files={"file": ("smoke测试.txt", io.BytesIO("hello".encode()), "text/plain")})
    check("upload attachment 200", r.status_code == 200)
    att_id = r.json().get("id")
    r = client.get(f"/api/roadrepair/{new_id}/attachments", headers=h)
    check("attachment list 1", len(r.json()) == 1)
    r = client.get("/api/roadrepair", headers=h,
                   params={"keyword": "测试地址(改)"})
    check("attachment_count 同步",
          any(i["id"] == new_id and i["attachment_count"] == 1 for i in r.json()["items"]))

    # 拦截脚本类
    r = client.post(f"/api/roadrepair/{new_id}/attachments", headers=h,
                    files={"file": ("evil.aspx", io.BytesIO(b"x"), "application/octet-stream")})
    check("blocked ext 400", r.status_code == 400)

    # 下载短令牌
    r = client.post(f"/api/roadrepair/attachments/{att_id}/token", headers=h)
    check("token 200", r.status_code == 200)
    url = r.json()["url"]
    r = client.get(url)
    check("download 200 content", r.status_code == 200 and r.content == b"hello")
    r = client.get(url + "x")
    check("bad token 401", r.status_code == 401)

    r = client.delete(f"/api/roadrepair/attachments/{att_id}", headers=h)
    check("delete attachment 200", r.status_code == 200)

    # 6. 价格管理
    r = client.get("/api/roadrepair/prices", headers=h)
    check("prices total 37", r.json().get("total") == 37, str(r.json().get("total")))
    r = client.get("/api/roadrepair/price-options", headers=h, params={"company": "公路局"})
    opts = r.json()
    check("公路局选项全专属", all(o["company"] == "公路局" for o in opts) and len(opts) > 0)
    r = client.get("/api/roadrepair/price-options", headers=h, params={"company": "大市政"})
    opts2 = r.json()
    check("大市政含通用价", any(o["company"] == "通用" for o in opts2))
    r = client.get("/api/roadrepair/match-price", headers=h,
                   params={"company": "大市政", "road_type": opts2[0]["road_type"]})
    check("match-price 200", r.status_code == 200)

    r = client.post("/api/roadrepair/prices", headers=h,
                    json={"road_type": "测试类型", "price": 88.5})
    check("save price 200", r.status_code == 200)
    pid = r.json()["id"]
    r = client.post("/api/roadrepair/prices", headers=h,
                    json={"id": pid, "road_type": "测试类型", "price": 99, "company": "大市政"})
    check("update price 200", r.status_code == 200)
    r = client.delete(f"/api/roadrepair/prices/{pid}", headers=h)
    check("delete price 200", r.status_code == 200)

    # 7. 导出
    r = client.get("/api/roadrepair/export", headers=h)
    check("export 200 xlsx", r.status_code == 200
          and r.headers["content-type"].startswith("application/vnd.openxmlformats"))
    check("export size > 10KB", len(r.content) > 10000, str(len(r.content)))

    # 8. 无权限拦截(无 token)
    r = client.get("/api/roadrepair")
    check("no token 401/403", r.status_code in (401, 403))

    # 9. 清理
    r = client.delete(f"/api/roadrepair/{new_id}", headers=h)
    check("delete repair 200", r.status_code == 200)
    r = client.get(f"/api/roadrepair/{new_id}", headers=h)
    check("deleted -> 404", r.status_code == 404)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_user()
