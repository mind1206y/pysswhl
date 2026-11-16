"""传导完好率分组 4 模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_cd
覆盖:4 表迁移基线(行数/SUM/bmid/25日)、权限码与部门子树、公共字典、
完好率列表/footer/备注/生成报表/锁定/导出(公司版+营业所版)、
故障/大修/变动三页增删改查/本人校验/往期校验/锁定校验、
大修导出、变动模板下载与 Excel 上传。
"""

import json
from base64 import b64encode
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import app

client = TestClient(app)
PASS = 0
FAIL = 0
MARK = "SMOKE-CD"
ADMIN = "smoke_cd_admin"
NOPERM = "smoke_cd_noperm"
DEPT_USER = "smoke_cd_dept"     # 厦门营业所(8),只有 cdgz:view
WHL_USER = "smoke_cd_whl"       # 厦门营业所(8),有 cdwhl:view(测营业所版导出)
ALL_USER = "smoke_cd_all"       # 厦门营业所(8),4 页权限(测明细 CRUD 归属)
REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _mk_user(username, perm_codes=None, dept_id=None):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import Department, Permission, Role, User

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            return
        superuser = perm_codes is None
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=superuser, is_active=True)
        if perm_codes:
            code = f"smoke_cd_role_{username}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perms = [p for c in perm_codes
                         for p in [db.query(Permission).filter(
                             Permission.code == c).first()] if p]
                role = Role(name=f"smoke传导{username}", code=code, permissions=perms)
                db.add(role)
                db.flush()
            user.roles.append(role)
        if dept_id:
            dept = db.get(Department, dept_id)
            if dept:
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


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.cd import CDDaxiu, CDGz, CDWhl, CDXz
    from app.models.plan import ConsolTb
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        db.query(CDGz).filter(CDGz.sbname.like(f"{MARK}%")).delete(synchronize_session=False)
        db.query(CDDaxiu).filter(CDDaxiu.nr.like(f"{MARK}%")).delete(synchronize_session=False)
        db.query(CDXz).filter(CDXz.sbname.like(f"{MARK}%")).delete(synchronize_session=False)
        # 本月生成的测试报表(_OPERATOR 用户名 = 测试账号)
        for name in (ADMIN, NOPERM, DEPT_USER, WHL_USER, ALL_USER):
            db.query(CDWhl).filter(CDWhl.username == name).delete(synchronize_session=False)
        lock = db.query(ConsolTb).filter(ConsolTb.conName == "锁定传导报表").first()
        if lock:
            lock.val = False
        db.commit()
        # 逐个 ORM 删除并提交:bulk delete 会撞 user_role 级联 StaleDataError
        for name in (ADMIN, NOPERM, DEPT_USER, WHL_USER, ALL_USER):
            user = db.query(User).filter(User.username == name).first()
            if user:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_cd_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def main():
    from app.db.session import SessionLocal
    from app.models.cd import CDDaxiu, CDGz, CDWhl, CDXz
    from app.models.plan import ConsolTb
    from app.services.cd_common import period_days, report_date

    global PASS, FAIL
    _cleanup()
    _mk_user(ADMIN)
    _mk_user(NOPERM, ["smoke:none"])
    _mk_user(DEPT_USER, ["cdgz:view"], 8)
    _mk_user(WHL_USER, ["cdwhl:view"], 8)
    _mk_user(ALL_USER, ["cdwhl:view", "cdgz:view", "cddaxiu:view", "cdbd:view"], 8)
    H = _headers(_login(ADMIN))
    HN = _headers(_login(NOPERM))
    HD = _headers(_login(DEPT_USER))
    HW = _headers(_login(WHL_USER))
    HA = _headers(_login(ALL_USER))

    db = SessionLocal()
    baseline = {
        "CD_whl": db.query(CDWhl).count(), "CD_gz": db.query(CDGz).count(),
        "CD_daxiu": db.query(CDDaxiu).count(), "CD_xz": db.query(CDXz).count(),
    }
    from sqlalchemy import func as sqlfunc

    sums = {
        "decgztss": float(db.query(sqlfunc.sum(CDWhl.decgztss)).scalar() or 0),
        "dects": float(db.query(sqlfunc.sum(CDGz.dects)).scalar() or 0),
    }
    bmid_set = {r[0] for r in db.query(CDWhl.bmid).distinct().all()}
    non25 = db.query(CDWhl).filter(CDWhl.bbdate.isnot(None)).all()
    lock_row = db.query(ConsolTb).filter(ConsolTb.conName == "锁定传导报表").first()
    db.close()

    print("\n[1] 迁移基线")
    report = json.loads((REPORT_DIR / "cd_import_report.json").read_text(encoding="utf-8"))
    check("4 表行数 184/3132/410/1355",
          baseline == report["rows"] and baseline["CD_whl"] == 184
          and baseline["CD_gz"] == 3132 and baseline["CD_daxiu"] == 410
          and baseline["CD_xz"] == 1355, baseline)
    check("SUM(decgztss)=27199 / SUM(dects)=27458",
          abs(sums["decgztss"] - 27199) < 0.01 and abs(sums["dects"] - 27458) < 0.01,
          sums)
    check("bmid 已重映射到新 departments.id", bmid_set == {8, 9, 10, 12, 13}, bmid_set)
    # 旧库有 10 行 2024-11-01 / 2024-12-01 的历史快照(bbdate 非25日),
    # 旧页面按 25 日过滤本来就查不到,迁移照原值保留
    off25 = [r for r in non25 if r.bbdate.day != 25]
    check("报表日期除 10 行历史快照外均为25日",
          len(off25) == 10
          and {(r.bbdate.year, r.bbdate.month) for r in off25} == {(2024, 11), (2024, 12)},
          [(r.bbdate.isoformat(), r.id) for r in off25[:12]])
    check("锁定传导报表开关已迁入", lock_row is not None and not bool(lock_row.val))
    check("报表周期天数 = 上月26日~本月25日",
          period_days(date(2026, 3, 25)) == 28 and period_days(date(2026, 11, 25)) == 31,
          (period_days(date(2026, 3, 25)), period_days(date(2026, 11, 25))))

    print("\n[2] 权限与部门子树")
    for path in ("/api/cdwhl", "/api/cdgz", "/api/cddaxiu", "/api/cdbd", "/api/cd/dicts"):
        check(f"无权限访问 {path} → 403",
              client.get(path, headers=HN).status_code == 403)
    for path in ("/api/cdwhl", "/api/cdgz", "/api/cddaxiu", "/api/cdbd"):
        check(f"超管访问 {path} → 200", client.get(path, headers=H).status_code == 200)
    r = client.get("/api/cdgz", params={"rq": "2026-10"}, headers=HD)
    dept_items = r.json().get("items", [])
    check("营业所用户 fault 列表只含本部门", r.status_code == 200
          and all(i["bmid"] == 8 for i in dept_items), r.text[:120])
    check("部门用户无完好率权限 → 403",
          client.get("/api/cdwhl", headers=HD).status_code == 403)

    print("\n[3] 公共字典")
    d = client.get("/api/cd/dicts", headers=H).json()
    check("管材11/管径16/变动类别4/大修类别1",
          len(d["guancai"]) == 11 and len(d["guanjing"]) == 16
          and len(d["bdlb"]) == 4 and d["daxiu_lb"] == ["报废更换"])
    check("部门下拉非空且含厦门营业所",
          any(x["name"] == "厦门营业所" for x in d["departments"]))
    check("报表日期=当月25日 / bt=年月",
          d["report_date"] == report_date().isoformat()
          and d["bt"] == f"{date.today().year}年{date.today().month}月", d["bt"])
    check("超管可锁定 / 初始未锁定", d["can_lock"] is True and d["is_locked"] is False)
    check("普通用户不可锁定",
          client.get("/api/cd/dicts", headers=HD).json()["can_lock"] is False)

    print("\n[4] 完好率列表 / footer / 备注")
    r = client.get("/api/cdwhl", params={"rq": "2026-10", "size": 30}, headers=H)
    body = r.json()
    # 2026-10 旧库只有 4 个营业所生成了报表(翔安未生成),照旧显示 4 行
    check("2026-10 列表 4 行 / bt=2026年10月",
          r.status_code == 200 and body["total"] == 4
          and len(body["items"]) == 4 and body["bt"] == "2026年10月",
          (r.status_code, body.get("total"), body.get("bt")))
    f = body["footer"]
    check("footer 当前页合计", f["bz"] == "合计"
          and abs(f["decgztss"] - sum(float(i["decgztss"] or 0) for i in body["items"])) < 0.01
          and f["whl"] is not None, f)
    check("部门下拉过滤 bmid=8 只 1 行",
          client.get("/api/cdwhl", params={"rq": "2026-10", "bmid": 8},
                     headers=H).json()["total"] == 1)
    wid = body["items"][0]["id"]
    old_bz = client.get("/api/cdwhl/remark", params={"id": wid}, headers=H).json()["bz"]
    check("读取备注", isinstance(old_bz, str))
    rr = client.post("/api/cdwhl/remark", json={"id": wid, "bz": f"{MARK}备注"},
                     headers=H)
    check("保存备注", rr.status_code == 200 and rr.json()["message"] == "ok")
    check("备注已落库", client.get("/api/cdwhl/remark", params={"id": wid},
                                 headers=H).json()["bz"] == f"{MARK}备注")
    client.post("/api/cdwhl/remark", json={"id": wid, "bz": old_bz}, headers=H)
    check("原备注已恢复", client.get("/api/cdwhl/remark", params={"id": wid},
                                   headers=H).json()["bz"] == old_bz)

    print("\n[5] 生成报表(旧 tjbb)")
    this_month = report_date().strftime("%Y-%m")
    gen = client.post("/api/cdwhl/generate", json={"rq": this_month}, headers=H)
    # 旧 tjbb:上月(2026-10-25)只有 4 个部门有报表,因此只生成 4 个部门
    check("生成报表成功(上月有报表的 4 个部门)",
          gen.status_code == 200 and gen.json()["created"] == 4, gen.text[:150])
    rows = client.get("/api/cdwhl", params={"rq": this_month}, headers=H).json()["items"]
    check("本月生成 4 个部门", len(rows) == 4, len(rows))
    check("台数=上月台数 / 完好率=100(本月无故障无变动)",
          all(i["whl"] == 100 and i["sytss"] == i["ts"] * period_days(report_date()) * 24
              for i in rows),
          [(i["bumen"], i["ts"], i["sytss"], i["whl"]) for i in rows])
    gen2 = client.post("/api/cdwhl/generate", json={"rq": this_month}, headers=H)
    check("重复生成替换而非追加",
          gen2.json()["created"] == 4
          and client.get("/api/cdwhl", params={"rq": this_month},
                         headers=H).json()["total"] == 4)

    print("\n[6] 锁定开关")
    check("锁定", client.post("/api/cdwhl/lock", json={"is_locked": True},
                             headers=H).json()["is_locked"] is True)
    check("dicts 反映锁定", client.get("/api/cd/dicts", headers=H).json()["is_locked"] is True)
    check("锁定时故障新增被拒",
          client.post("/api/cdgz", json={"sbname": f"{MARK}故障", "didian": "x",
                                        "ksdate": "2026-11-01", "jsdate": "2026-11-02"},
                      headers=H).status_code == 400)
    check("锁定时大修新增被拒",
          client.post("/api/cddaxiu", json={"nr": f"{MARK}大修", "gdh": "1",
                                            "daxiudate": "2026-11-01"},
                      headers=H).status_code == 400)
    check("锁定时变动新增被拒",
          client.post("/api/cdbd", json={"sbname": f"{MARK}变动", "bdlb": "新增设备"},
                      headers=H).status_code == 400)
    check("锁定时上传模板被拒",
          client.post("/api/cdbd/upload", files={"file": (
              "传导设备变动表.xlsx", _xlsx([["设备名称", "变动类型"], ["A", "新增设备"]]),
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
              headers=H).status_code == 400)
    check("锁定不影响完好率备注",
          client.post("/api/cdwhl/remark", json={"id": wid, "bz": old_bz},
                      headers=H).status_code == 200)
    check("解锁", client.post("/api/cdwhl/lock", json={"is_locked": False},
                              headers=H).json()["is_locked"] is False)

    print("\n[7] 传导故障 CRUD")
    gz_payload = {"bbdate": report_date().isoformat(), "sbname": f"{MARK}故障A",
                  "guancai": "PVC", "guanjing": "DN100", "didian": "测试地点",
                  "ksdate": "2026-11-01", "jsdate": "2026-11-02", "yy": "爆管",
                  "dects": 3.5, "bz": "否"}
    r = client.post("/api/cdgz", json=gz_payload, headers=HA)
    check("新增故障", r.status_code == 200 and r.json()["sbname"] == f"{MARK}故障A",
          r.text[:150])
    gid = r.json()["id"]
    check("详情回显", client.get(f"/api/cdgz/{gid}", headers=H).json()["dects"] == 3.5)
    gz_payload.update({"dects": 6.25, "sbname": f"{MARK}故障B"})
    check("编辑故障", client.put(f"/api/cdgz/{gid}", json=gz_payload,
                                headers=HA).json()["dects"] == 6.25)
    check("关键字搜索命中",
          client.get("/api/cdgz", params={"rq": this_month, "keyword": f"{MARK}故障B"},
                     headers=H).json()["total"] == 1)
    check("缺设备名称被拒",
          client.post("/api/cdgz", json={**gz_payload, "sbname": ""},
                      headers=H).status_code == 400)
    check("结束日期早于开始被拒",
          client.post("/api/cdgz", json={**gz_payload, "jsdate": "2026-10-01"},
                      headers=H).status_code == 400)
    check("非本人不能修改",
          client.put(f"/api/cdgz/{gid}", json=gz_payload, headers=H).status_code == 403)
    check("非本人不能删除",
          client.delete(f"/api/cdgz/{gid}", headers=H).status_code == 403)
    check("本人删除故障", client.delete(f"/api/cdgz/{gid}", headers=HA).status_code == 200)

    # 往期数据:直接插入上月记录,删除应被拒
    db = SessionLocal()
    past = CDGz(bmid=8, sbname=f"{MARK}往期故障", bbdate=date(2026, 10, 25),
                ksdate=date(2026, 10, 1), jsdate=date(2026, 10, 2),
                username=ADMIN, adddate=datetime.now(), finadate=datetime.now())
    db.add(past)
    db.commit()
    past_id = past.id
    db.close()
    rp = client.delete(f"/api/cdgz/{past_id}", headers=H)
    check("往期数据不能删除", rp.status_code == 400
          and "往期" in rp.json()["detail"], rp.text[:120])
    db = SessionLocal()
    db.query(CDGz).filter(CDGz.id == past_id).delete()
    db.commit()
    db.close()

    print("\n[8] 传导大修 CRUD / 导出")
    dx_payload = {"bbdate": report_date().isoformat(), "daxiudate": "2026-11-03",
                  "lb": "报废更换", "nr": f"{MARK}大修A", "gdh": "GD-001",
                  "gdkj": "DN100", "xbqkj": "DN200", "fmkj": "DN300",
                  "xfskj": "DN400", "num": 2, "bz": "外力", "cfd": "仓库",
                  "sgy": "张三", "sgtel": "13800000000"}
    r = client.post("/api/cddaxiu", json=dx_payload, headers=HA)
    check("新增大修", r.status_code == 200 and r.json()["nr"] == f"{MARK}大修A", r.text[:150])
    did = r.json()["id"]
    check("大修详情", client.get(f"/api/cddaxiu/{did}", headers=H).json()["gdh"] == "GD-001")
    check("编辑大修", client.put(f"/api/cddaxiu/{did}",
                                json={**dx_payload, "num": 5},
                                headers=HA).json()["num"] == 5)
    ex = client.get("/api/cddaxiu/export", params={"rq": this_month,
                                                   "keyword": f"{MARK}大修"}, headers=H)
    check("大修导出 200 + xlsx", ex.status_code == 200
          and ex.content[:2] == b"PK", ex.text[:120])
    wb = load_workbook(BytesIO(ex.content))
    ws = wb.worksheets[0]
    check("大修导出标题含年月", "年" in str(ws["A1"].value) and "大修" in str(ws["A1"].value),
          ws["A1"].value)
    check("大修导出两级表头", str(ws["C2"].value) == "设备大修/更新记录"
          and str(ws["G2"].value) == "口径", (ws["C2"].value, ws["G2"].value))
    check("大修导出命中 1 行", ws.max_row == 4 and ws.cell(row=4, column=5).value == f"{MARK}大修A",
          ws.max_row)
    check("缺工单号被拒",
          client.post("/api/cddaxiu", json={**dx_payload, "gdh": ""},
                      headers=H).status_code == 400)
    check("非本人不能删除大修",
          client.delete(f"/api/cddaxiu/{did}", headers=H).status_code == 403)
    check("本人删除大修", client.delete(f"/api/cddaxiu/{did}", headers=HA).status_code == 200)

    print("\n[9] 传导变动表 CRUD / 模板 / 上传")
    bd_payload = {"bbdate": report_date().isoformat(), "bdlb": "新增设备",
                  "sbname": f"{MARK}新增设备A"}
    r = client.post("/api/cdbd", json=bd_payload, headers=HA)
    check("新增变动", r.status_code == 200 and r.json()["bdlb"] == "新增设备", r.text[:150])
    bid = r.json()["id"]
    check("变动详情", client.get(f"/api/cdbd/{bid}", headers=H).json()["sbname"] == f"{MARK}新增设备A")
    check("编辑变动", client.put(f"/api/cdbd/{bid}",
                                json={**bd_payload, "bdlb": "报废设备"},
                                headers=HA).json()["bdlb"] == "报废设备")
    check("变动类别筛选", client.get("/api/cdbd", params={
        "rq": this_month, "bdlb": "报废设备", "keyword": MARK},
        headers=H).json()["total"] == 1)
    check("非法变动类别被拒",
          client.post("/api/cdbd", json={**bd_payload, "bdlb": "未知类别"},
                      headers=H).status_code == 400)
    tpl = client.get("/api/cdbd/template", headers=H)
    check("模板下载 200 + xlsx", tpl.status_code == 200 and tpl.content[:2] == b"PK")
    tws = load_workbook(BytesIO(tpl.content)).worksheets[0]
    check("模板 2 列表头", tws["A1"].value == "设备名称"
          and "变动类型" in str(tws["B1"].value))
    up_bytes = _xlsx([["设备名称", "变动类型"],
                      [f"{MARK}导入设备1", "新增设备"],
                      [f"{MARK}导入设备2", "停用设备"]])
    up = client.post("/api/cdbd/upload", files={"file": (
        "传导设备变动表.xlsx", up_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, headers=HA)
    check("上传导入 2 条", up.status_code == 200 and up.json()["count"] == 2, up.text[:150])
    check("导入数据按标记可查", client.get("/api/cdbd", params={
        "rq": this_month, "keyword": f"{MARK}导入设备"},
        headers=H).json()["total"] == 2)
    bad = client.post("/api/cdbd/upload", files={"file": (
        "随便.xlsx", up_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, headers=H)
    check("非模板文件名被拒", bad.status_code == 400
          and "传导设备变动表" in bad.json()["detail"], bad.text[:120])
    check("本人删除变动", client.delete(f"/api/cdbd/{bid}", headers=HA).status_code == 200)

    print("\n[10] 完好率导出(公司版 / 营业所版)")
    ew = client.get("/api/cdwhl/export", params={"rq": "2026-10"}, headers=H)
    check("公司版导出 200 + xlsx", ew.status_code == 200 and ew.content[:2] == b"PK")
    wbk = load_workbook(BytesIO(ew.content))
    check("3 个 sheet 统计/变动/故障",
          wbk.sheetnames == ["统计", "变动", "故障"], wbk.sheetnames)
    st = wbk["统计"]
    check("统计标题带年月 + 编制单位", "2026年10月" in str(st["A1"].value)
          and "售水事业部" in str(st["A2"].value), (st["A1"].value, st["A2"].value))
    check("统计 4 部门 + 合计行", st.max_row >= 8
          and any(str(st.cell(row=r, column=1).value or "").startswith("合")
                  for r in range(4, 11)))
    check("故障 sheet 含部门分块", wbk["故障"]["A3"].value is not None,
          wbk["故障"]["A3"].value)
    ey = client.get("/api/cdwhl/export", params={"rq": "2026-10"}, headers=HW)
    check("营业所版导出 200", ey.status_code == 200 and ey.content[:2] == b"PK")
    wsy = load_workbook(BytesIO(ey.content))["统计"]
    check("营业所版编制单位=厦门营业所",
          "厦门营业所" in str(wsy["A2"].value), wsy["A2"].value)
    check("营业所版只 1 个部门行",
          str(wsy["A4"].value) == "厦门营业所"
          and str(wsy["A5"].value or "").startswith("合"),
          (wsy["A4"].value, wsy["A5"].value))

    # 清理:本月生成的报表 + 导入的 2 条 + 测试用户/角色/锁定
    _cleanup()
    db = SessionLocal()
    left = {
        "CD_whl": db.query(CDWhl).count(), "CD_gz": db.query(CDGz).count(),
        "CD_daxiu": db.query(CDDaxiu).count(), "CD_xz": db.query(CDXz).count(),
    }
    from sqlalchemy import text as sqltext

    from app.models.user import Permission, Role
    cd_codes = {p.code for p in db.query(Permission).filter(
        Permission.code.like("cd%")).all()}
    cd_roles = db.query(Role).filter(Role.code.like("legacy_cd%")).all()
    role_ok = all(any(p.code.startswith("cd") for p in r.permissions) for r in cd_roles)
    grant_users = db.execute(sqltext(
        "SELECT COUNT(DISTINCT ur.user_id) FROM user_role ur "
        "JOIN role_permission rp ON rp.role_id=ur.role_id "
        "JOIN permissions p ON p.id=rp.permission_id WHERE p.code='cdwhl:view'"
    )).scalar()
    db.close()
    print("\n[11] 权限迁移 / 清理校验")
    check("数据回到迁移基线", left == report["rows"], (left, report["rows"]))
    check("5 个传导权限码齐备", cd_codes == {
        "cdwhl:view", "cdwhl:manage", "cdgz:view", "cddaxiu:view", "cdbd:view"}, cd_codes)
    check("legacy_cd* 角色均挂有权限码", len(cd_roles) >= 5 and role_ok, len(cd_roles))
    check("旧菜单用户已获传导权限(>=10 人)", grant_users >= 10, grant_users)

    print(f"\n==== smoke_cd: {PASS} passed, {FAIL} failed ====")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
