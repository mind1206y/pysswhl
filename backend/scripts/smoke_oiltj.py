"""车辆油量统计(oiltj)模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_oiltj
"""

from base64 import b64encode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_oiltj"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def login():
    """临时超管账号登录(密码 RSA-OAEP 加密,与前端一致),跑完删除。"""
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
                real_name="油量统计smoke",
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
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
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
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def main():
    token = login()
    h = {"Authorization": f"Bearer {token}"}

    # ===== 下拉 =====
    r = client.get("/api/oiltj/dicts", headers=h)
    check("dicts 200", r.status_code == 200, r.text[:200])
    d = r.json()
    check("dicts 年度含 2026", 2026 in d.get("years", []), str(d.get("years")))
    check("dicts 车辆下拉非空", len(d.get("vehicles", [])) > 0)
    check("dicts 部门下拉非空", len(d.get("departments", [])) > 0)

    r = client.get("/api/oiltj/months", params={"year": 2026}, headers=h)
    check("months 200 且含月份", r.status_code == 200 and len(r.json()["months"]) > 0, r.text[:200])

    r = client.get("/api/oiltj/cars", headers=h)
    check("cars 200 非空", r.status_code == 200 and len(r.json()) > 0, r.text[:200])

    # ===== 主列表(默认:今年上月,只看正常车) =====
    r = client.get("/api/oiltj", headers=h)
    check("列表 200", r.status_code == 200, r.text[:300])
    data = r.json()
    check("列表 total>0", data["total"] > 0)
    row = data["rows"][0]
    need_keys = ["cheid", "chehao", "bumen", "yoil", "noil", "ngls", "lpkm",
                 "monthLpkm", "bydgls", "sydgls", "yssgls", "times", "ye", "bz"]
    check("列表行字段齐全", all(k in row for k in need_keys), str(row.keys()))
    check("车辆状态字段", row["delf"] in (1, 2), str(row["delf"]))

    # 分页
    r = client.get("/api/oiltj", params={"page": 2, "size": 5}, headers=h)
    check("分页第 2 页", r.status_code == 200 and len(r.json()["rows"]) <= 5)

    # 过滤开关
    r = client.get("/api/oiltj", params={"oillie": "true"}, headers=h)
    ok = all(x["oil"] == "0#" for x in r.json()["rows"]) if r.json()["rows"] else True
    check("柴油开关过滤 oil=0#", ok)
    r = client.get("/api/oiltj", params={"nooilcard": "true"}, headers=h)
    ok = all(x["cheyt"] != "油卡" for x in r.json()["rows"]) if r.json()["rows"] else True
    check("非油卡开关过滤", ok)
    r = client.get("/api/oiltj", params={"px": "true"}, headers=h)
    check("所有状态开关 200", r.status_code == 200)
    if data["total"]:
        r = client.get("/api/oiltj", params={"sousou": row["chehao"][:2]}, headers=h)
        check("车号模糊搜索", r.status_code == 200)

    # 排序(照旧按年油量)
    r = client.get("/api/oiltj", params={"sort": "noil", "order": "desc"}, headers=h)
    rows_sorted = r.json()["rows"]
    vals = [x["noil"] for x in rows_sorted if x["noil"] is not None]
    check("noil 降序排序", vals == sorted(vals, reverse=True), str(vals[:5]))

    # ===== 与旧口径抽查:挑一辆有 2026 数据的车,核月油量与子表 =====
    from sqlalchemy import text as stext
    from app.db.session import engine
    with engine.connect() as c:
        one = c.execute(stext(
            "SELECT cheid, nian, SUM(oilnum) s FROM tboil WHERE nian=2026 "
            "GROUP BY cheid, nian ORDER BY s DESC LIMIT 1")).fetchone()
    check("存在 2026 年 tboil 数据", one is not None)
    if one:
        cheid, year = int(one[0]), int(one[1])
        r = client.get(f"/api/oiltj/{cheid}/youliang", params={"year": year}, headers=h)
        check("youliang 子表 200", r.status_code == 200, r.text[:200])
        sub = r.json()["rows"][0]
        total12 = sum(sub[f"yue{m}"] for m in range(1, 13))
        check("子表 12 月合计=tboil 年合计", abs(total12 - float(one[2])) < 0.05,
              f"{total12} vs {one[2]}")

        r = client.get(f"/api/oiltj/{cheid}/chart", params={"year": year}, headers=h)
        check("chart 200 含车号", r.status_code == 200 and "chehao" in r.json())

        r = client.get(f"/api/oiltj/{cheid}/glchart", params={"year": year}, headers=h)
        check("glchart 200", r.status_code == 200)

        r = client.get("/api/oiltj/month-stat", params={"cheid": cheid, "year": year}, headers=h)
        check("month-stat 12 个月", r.status_code == 200 and len(r.json()["months"]) == 12,
              r.text[:200])
        ms = r.json()["months"]
        check("month-stat 合计>0", sum(m["oil"] for m in ms) > 0)

    # ===== 部门年度图表 =====
    r = client.get("/api/oiltj/zchart", params={"year": 2026}, headers=h)
    check("zchart 200", r.status_code == 200, r.text[:200])
    z = r.json()
    check("zchart 三油类字段", all(k in z for k in ("zong0", "zong92", "zong95", "zong_je")))
    check("zchart 年总量>0", z["zong"] > 0, str(z["zong"]))

    # ===== 导出 =====
    r = client.get("/api/oiltj/export-month", headers=h)
    check("月度导出 200 xlsx", r.status_code == 200 and len(r.content) > 1000,
          f"{r.status_code} {len(r.content)}B")
    r = client.get("/api/oiltj/export-year", headers=h)
    check("年度导出 200 xlsx", r.status_code == 200 and len(r.content) > 1000)
    r = client.get("/api/oiltj/export-finance", headers=h)
    check("财务导出 200 xlsx", r.status_code == 200 and len(r.content) > 1000)

    # ===== 无令牌应被拒 =====
    r = client.get("/api/oiltj")
    check("未登录 401/403", r.status_code in (401, 403), str(r.status_code))

    cleanup_user()
    print(f"\n结果: PASS={PASS} FAIL={FAIL}")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
