"""车辆各类费用(CLfeiyong)模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_clfeiyong
覆盖:迁移基线(34 条 / 1285.0000)、列表/合计/年度/类别/关键字/分页筛选、
字典与联想、部门子树数据权限、权限码、增删改与旧 Editgz 漏存金额修复、Excel 导出。
"""

from base64 import b64encode
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_fy"
SMOKE_VIEW_USER = "smoke_fy_view"
SMOKE_DEPT_USER = "smoke_fy_dept"
SMOKE_NO_PERM = "smoke_fy_noperm"
MARK = "SMOKE-FY"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _mk_user(username, perm_code=None, dept_id=None):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import Department, Permission, Role, User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is not None:
            return
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=perm_code is None, is_active=True)
        if perm_code is not None:
            code = f"smoke_fy_role_{perm_code.replace(':', '_')}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == perm_code).first()
                role = Role(name=f"smoke车辆费用{perm_code}", code=code, permissions=[perm])
                db.add(role)
                db.flush()
            user.roles.append(role)
        if dept_id is not None:
            dept = db.get(Department, dept_id)
            if dept is not None:
                user.departments.append(dept)
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
    from app.models.vehicle import ClFeiyong

    db = SessionLocal()
    try:
        db.query(ClFeiyong).filter(
            (ClFeiyong.bz.like(f"{MARK}%")) | (ClFeiyong.dw.like(f"{MARK}%"))
        ).delete(synchronize_session=False)
        db.commit()
        for name in (SMOKE_USER, SMOKE_VIEW_USER, SMOKE_DEPT_USER, SMOKE_NO_PERM):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_fy_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def main():
    from sqlalchemy import func

    from app.db.session import SessionLocal
    from app.models.vehicle import ClChe, ClFeiyong

    _cleanup()  # 上次异常中断时先清理残留
    db = SessionLocal()
    try:
        # 有费用的部门(取一个,用于构造部门受限用户);以及另一个不同部门的记录(测 403)
        pairs = (
            db.query(ClFeiyong, ClChe).join(ClChe, ClFeiyong.cheid == ClChe.id).all()
        )
        dept_ids = sorted({car.bmid for _f, car in pairs if car.bmid})
        dept_fees = {}
        for fee, car in pairs:
            dept_fees[car.bmid] = dept_fees.get(car.bmid, 0) + float(fee.jine or 0)
        target_dept = max(dept_fees, key=lambda k: dept_fees[k]) if dept_fees else None
        other_fee_id = next((fee.id for fee, car in pairs
                             if car.bmid and car.bmid != target_dept), None)
        car = (db.query(ClChe)
               .filter(ClChe.yongtu != "油卡", ClChe.delf != 0)
               .order_by(ClChe.id).first())
        car_id, car_no = car.id, car.chehao
        oil_card_cars = db.query(ClChe.id).filter(ClChe.yongtu == "油卡").all()
        oil_card_ids = {x[0] for x in oil_card_cars}
        deleted_car_ids = {x[0] for x in db.query(ClChe.id).filter(ClChe.delf == 0).all()}

        expected_total = len(pairs)   # 内连接口径:孤立的 cheid 不进列表
        expected_sum = float(db.query(func.sum(ClFeiyong.jine)).scalar() or 0)
        n_xi = db.query(ClFeiyong).filter(ClFeiyong.lx == "洗车").count()
        year_counts = dict(
            db.query(func.year(ClFeiyong.feiyongdate), func.count(ClFeiyong.id))
            .filter(ClFeiyong.feiyongdate.isnot(None))
            .group_by(func.year(ClFeiyong.feiyongdate)).all()
        )
        top_year = max(year_counts) if year_counts else None
        sample_unit = next((fee.dw for fee, _c in pairs if fee.dw), "")
        sample_fee = pairs[0][0]
        sample_no = pairs[0][1].chehao
    finally:
        db.close()

    _mk_user(SMOKE_USER, None)
    _mk_user(SMOKE_VIEW_USER, "vehicle:view")
    _mk_user(SMOKE_DEPT_USER, "vehicle:view", target_dept)
    _mk_user(SMOKE_NO_PERM, "gongdan:view")
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}
        hd = {"Authorization": f"Bearer {_login(SMOKE_DEPT_USER)}"}
        hn = {"Authorization": f"Bearer {_login(SMOKE_NO_PERM)}"}

        # ---- 迁移基线 ----
        check("迁移 34 行", expected_total == 34, str(expected_total))
        check("SUM(jine)=1285.0000", abs(expected_sum - 1285.0) < 1e-6, str(expected_sum))

        # ---- 列表 ----
        r = client.get("/api/clfeiyong", headers=h, params={"page": 1, "size": 30})
        check("GET 列表 200", r.status_code == 200, r.text[:200])
        data = r.json()
        check("总数与 DB 联查口径一致", data["total"] == expected_total,
              f"{data['total']} != {expected_total}")
        check("合计金额与 DB 口径一致", abs(data["sum"] - expected_sum) < 0.01,
              f"{data['sum']} != {expected_sum}")
        check("首页返回 ≤30 条", len(data["items"]) == min(30, expected_total))
        first = data["items"][0]
        check("字段结构完整", all(k in first for k in (
            "id", "cheid", "lx", "jine", "bz", "username", "djdate", "zuihoudate",
            "feiyongdate", "dw", "fangshi", "jingshou", "chehao", "bumen")),
            str(sorted(first.keys())))
        check("按费用日期倒序", all(
            (data["items"][i]["feiyongdate"] or "") >= (data["items"][i + 1]["feiyongdate"] or "")
            for i in range(len(data["items"]) - 1)))

        # ---- 筛选 ----
        r = client.get("/api/clfeiyong", headers=h, params={"lx": "洗车", "size": 500})
        check("类别筛选(洗车)", r.status_code == 200 and r.json()["total"] == n_xi,
              f"{r.json().get('total')} != {n_xi}")
        check("类别筛选合计同步", abs(r.json()["sum"] - sum(
            float(f.jine or 0) for f in [p[0] for p in pairs] if f.lx == "洗车")) < 0.01)
        r = client.get("/api/clfeiyong", headers=h,
                       params={"year": top_year, "size": 500})
        check(f"年度筛选({top_year})", r.status_code == 200
              and r.json()["total"] == year_counts[top_year],
              f"{r.json().get('total')} != {year_counts.get(top_year)}")
        r = client.get("/api/clfeiyong", headers=h,
                       params={"keyword": sample_no, "size": 500})
        check("关键字按车号命中", r.status_code == 200 and r.json()["total"] >= 1,
              str(r.json().get("total")))
        if sample_unit:
            r = client.get("/api/clfeiyong", headers=h,
                           params={"keyword": sample_unit, "size": 500})
            check("关键字按收费单位命中", r.status_code == 200 and r.json()["total"] >= 1,
                  str(r.json().get("total")))
        r = client.get("/api/clfeiyong", headers=h,
                       params={"keyword": "SMOKE-FY-NO-SUCH-RECORD", "size": 500})
        check("关键字无命中返回 0 / 合计 0",
              r.json()["total"] == 0 and r.json()["sum"] == 0 and r.json()["items"] == [])
        r = client.get("/api/clfeiyong", headers=h, params={"size": 5})
        check("分页 size=5 生效", len(r.json()["items"]) == 5)
        r = client.get("/api/clfeiyong", headers=h, params={"page": 2, "size": 5})
        check("分页 page=2 生效", r.status_code == 200 and r.json()["items"][0]["id"]
              != first["id"])
        r = client.get("/api/clfeiyong", headers=h,
                       params={"year": top_year, "lx": "洗车", "size": 500})
        check("组合筛选不超过单条件", 0 <= r.json()["total"] <= year_counts[top_year])

        # ---- 字典 / 联想 ----
        r = client.get("/api/clfeiyong/dicts", headers=h)
        check("GET dicts 200", r.status_code == 200)
        check("类别固定三项", r.json()["categories"] == ["洗车", "高速", "停车"],
              str(r.json().get("categories")))
        check("年度倒序且含数据年度", top_year in r.json()["years"]
              and r.json()["years"] == sorted(r.json()["years"], reverse=True))
        r = client.get("/api/clfeiyong/vehicles", headers=h)
        vids = [x["id"] for x in r.json()]
        check("车辆下拉 200 且含有效车", r.status_code == 200 and car_id in vids)
        check("车辆下拉排除油卡/已删除", not (oil_card_ids | deleted_car_ids) & set(vids))
        r = client.get("/api/clfeiyong/vehicles", headers=h, params={"q": car_no})
        check("车辆下拉按车号过滤", r.status_code == 200
              and all(car_no in x["chehao"] for x in r.json()))
        r = client.get("/api/clfeiyong/units", headers=h)
        check("收费单位联想空 query 返回空", r.status_code == 200 and r.json() == [])
        if sample_unit:
            r = client.get("/api/clfeiyong/units", headers=h, params={"q": sample_unit[:2]})
            check("收费单位联想去重", r.status_code == 200
                  and len({x["value"] for x in r.json()}) == len(r.json()))
            r = client.get("/api/clfeiyong/units", headers=h,
                           params={"q": "SMOKE-FY-NO-SUCH-UNIT"})
            check("收费单位联想无命中", r.json() == [])

        # ---- 权限 ----
        r = client.get("/api/clfeiyong", headers=hv)
        check("仅 vehicle:view 用户可访问", r.status_code == 200, str(r.status_code))
        r = client.get("/api/clfeiyong", headers=hn)
        check("无 vehicle:view 用户 403", r.status_code == 403, str(r.status_code))
        r = client.get("/api/clfeiyong")
        check("未登录 401", r.status_code == 401, str(r.status_code))
        if target_dept is not None:
            r = client.get("/api/clfeiyong", headers=hd, params={"size": 500})
            dept_data = r.json()
            check("部门子树用户可见范围收窄", r.status_code == 200
                  and 0 < dept_data["total"] < expected_total,
                  f"{dept_data.get('total')} / {expected_total}")
            check("部门子树合计与可见记录一致", abs(dept_data["sum"] - sum(
                float(x["jine"] or 0) for x in dept_data["items"])) < 0.01)
            if other_fee_id:
                r = client.get(f"/api/clfeiyong/{other_fee_id}", headers=hd)
                check("跨部门记录详情 403", r.status_code == 403, str(r.status_code))
                r = client.delete(f"/api/clfeiyong/{other_fee_id}", headers=hd)
                check("跨部门记录删除 403", r.status_code == 403, str(r.status_code))

        # ---- 添加 ----
        payload = {
            "cheid": car_id, "lx": "洗车", "jine": 66.66,
            "bz": f"{MARK}-CREATE", "feiyongdate": "2026-11-09",
            "dw": f"{MARK}-收费单位", "fangshi": "转账", "jingshou": "测试员",
        }
        r = client.post("/api/clfeiyong", headers=h, json=payload)
        check("添加费用 200", r.status_code == 200, r.text[:200])
        created = r.json()
        new_id = created.get("id")
        check("登记人=当前登录人", created.get("username") == SMOKE_USER,
              str(created.get("username")))
        check("登记日期/最后操作日期已写入",
              bool(created.get("djdate")) and bool(created.get("zuihoudate")))
        check("新增回读车号与金额", created.get("chehao") == car_no
              and abs(float(created.get("jine") or 0) - 66.66) < 1e-6)
        check("总金额随新增同步", abs(client.get(
            "/api/clfeiyong", headers=h, params={"keyword": MARK}).json()["sum"] - 66.66) < 0.01)

        bad = dict(payload)
        bad.pop("cheid")
        check("缺车号 400", client.post("/api/clfeiyong", headers=h, json=bad).status_code == 400)
        bad = dict(payload, lx="过路费")
        check("非法类别 400", client.post("/api/clfeiyong", headers=h, json=bad).status_code == 400)
        bad = dict(payload, jingshou="")
        check("缺经手人 400", client.post("/api/clfeiyong", headers=h, json=bad).status_code == 400)
        bad = dict(payload, cheid=99999999)
        r = client.post("/api/clfeiyong", headers=h, json=bad)
        check("不存在车辆 404", r.status_code == 404, str(r.status_code))

        # ---- 单条 / 编辑 ----
        r = client.get(f"/api/clfeiyong/{new_id}", headers=h)
        check("单条详情 200 且回读", r.status_code == 200
              and r.json()["dw"] == f"{MARK}-收费单位", r.text[:200])
        check("不存在记录 404", client.get(
            "/api/clfeiyong/99999999", headers=h).status_code == 404)

        edit = dict(payload, jine=88.88, lx="高速", dw=f"{MARK}-单位2",
                    bz=f"{MARK}-EDIT", fangshi="现金")
        r = client.put(f"/api/clfeiyong/{new_id}", headers=h, json=edit)
        check("编辑 200", r.status_code == 200, r.text[:200])
        edited = r.json()
        check("旧 Editgz 漏存金额已修复", abs(float(edited["jine"]) - 88.88) < 1e-6,
              str(edited.get("jine")))
        check("类别/收费方式/单位同步更新", edited["lx"] == "高速"
              and edited["fangshi"] == "现金" and edited["dw"] == f"{MARK}-单位2")
        check("登记人/登记日期编辑后不变", edited["username"] == SMOKE_USER
              and edited["djdate"] == created["djdate"])
        r = client.get("/api/clfeiyong", headers=h, params={"keyword": MARK})
        check("列表合计随编辑同步", abs(r.json()["sum"] - 88.88) < 0.01,
              str(r.json().get("sum")))

        # ---- 导出 ----
        r = client.get("/api/clfeiyong/export", headers=h)
        check("导出 200 且为 xlsx", r.status_code == 200 and r.content[:2] == b"PK",
              str(r.status_code))
        check("导出文件名 UTF-8 编码", "filename*=UTF-8''" in r.headers.get(
            "content-disposition", ""))
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(r.content))
        ws = wb.active
        check("导出 9 列表头", [ws.cell(row=2, column=c).value for c in range(1, 10)] == [
            "序号", "车牌号", "交费日期", "费用名称", "费用金额", "收费单位",
            "交费方式", "经手人", "备注"], str([ws.cell(row=2, column=c).value for c in range(1, 10)]))
        check("导出行数=筛选全量(含新增)", ws.max_row == expected_total + 1 + 2,
              str(ws.max_row))
        r = client.get("/api/clfeiyong/export", headers=h, params={"keyword": MARK})
        ws = load_workbook(BytesIO(r.content)).active
        check("导出跟随当前筛选", ws.max_row == 3, str(ws.max_row))
        check("导出含新增记录金额", ws.cell(row=3, column=5).value == 88.88,
              str(ws.cell(row=3, column=5).value))
        r = client.get("/api/clfeiyong/export", headers=hn)
        check("无权限导出 403", r.status_code == 403, str(r.status_code))

        # ---- 删除 ----
        r = client.delete(f"/api/clfeiyong/{new_id}", headers=h)
        check("删除 200", r.status_code == 200, r.text[:200])
        check("删除后详情 404", client.get(
            f"/api/clfeiyong/{new_id}", headers=h).status_code == 404)
        check("删除后合计恢复", abs(client.get(
            "/api/clfeiyong", headers=h).json()["sum"] - expected_sum) < 0.01)
        r = client.put(f"/api/clfeiyong/{new_id}", headers=h, json=edit)
        check("编辑已删除记录 404", r.status_code == 404, str(r.status_code))

        # ---- 旧数据未被污染 ----
        r = client.get("/api/clfeiyong", headers=h, params={"size": 500})
        check("跑完仍为 34 行 / 1285.0000", r.json()["total"] == 34
              and abs(r.json()["sum"] - 1285.0) < 1e-6,
              f"{r.json()['total']} / {r.json()['sum']}")
        check("历史记录字段未被改写", any(
            x["id"] == sample_fee.id and x["jine"] == float(sample_fee.jine or 0)
            for x in r.json()["items"]))

        print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
