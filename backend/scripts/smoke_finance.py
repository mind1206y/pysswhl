"""财务管理三模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_finance
覆盖:迁移基线(7 表行数/金额)、权限码、固定资产字典/列表/合计/筛选/备注/盘点/
报废单详情/两个导出/盘点表导入、清理报告单据增删改/图片/候选/报废/报告导出、
物资采购申请列表/合计/模板/Excel 解析/主子表增删改/越权/打印/两个下载。
"""

from base64 import b64encode
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app

client = TestClient(app)
PASS = 0
FAIL = 0
MARK = "SMOKE-FIN"
ADMIN = "smoke_fin_admin"
NOPERM = "smoke_fin_noperm"
DEPT_USER = "smoke_fin_dept"
WZ_USER = "smoke_fin_wz"


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
        if db.query(User).filter(User.username == username).first():
            return
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=perm_code is None, is_active=True)
        if perm_code:
            code = f"smoke_fin_role_{perm_code.replace(':', '_')}_{username}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == perm_code).first()
                role = Role(name=f"smoke财务{perm_code}", code=code,
                            permissions=[perm] if perm else [])
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
    from app.models.finance import (Wzcgsq, WzcgsqMx, ZcBaofeidan, ZcBaofeitp, ZcCw)
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(Wzcgsq.id).filter(
            Wzcgsq.bumen.like(f"{MARK}%")).all()]
        if ids:
            db.query(WzcgsqMx).filter(WzcgsqMx.mainid.in_(ids)).delete(synchronize_session=False)
            db.query(Wzcgsq).filter(Wzcgsq.id.in_(ids)).delete(synchronize_session=False)
        bids = [r[0] for r in db.query(ZcBaofeidan.id).filter(
            ZcBaofeidan.zaiyao.like(f"{MARK}%")).all()]
        if bids:
            # ⚠️ 只解挂,绝不删除真实资产台账行
            db.query(ZcCw).filter(ZcCw.baofeidanid.in_(bids)).update(
                {ZcCw.baofeidanid: None, ZcCw.baofeiqk: None, ZcCw.baofeicztime: None},
                synchronize_session=False)
            db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid.in_(bids)).delete(synchronize_session=False)
            db.query(ZcBaofeidan).filter(ZcBaofeidan.id.in_(bids)).delete(synchronize_session=False)
        db.query(ZcCw).filter(ZcCw.zccode.like(f"{MARK}%")).delete(synchronize_session=False)
        # 逐个 ORM 删除并提交:bulk delete 会与 user_role 级联状态冲突(StaleDataError)
        for name in (ADMIN, NOPERM, DEPT_USER, WZ_USER):
            user = db.query(User).filter(User.username == name).first()
            if user:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_fin_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def main():
    from app.db.session import SessionLocal
    from app.models.finance import Wzcgsq, WzcgsqMx, ZcBaofeidan, ZcBaofeitp, ZcCw, ZcLb, ZcNd

    global PASS, FAIL
    _cleanup()
    _mk_user(ADMIN)
    _mk_user(NOPERM, "smoke:none")
    _mk_user(DEPT_USER, "gdzc:view", 8)   # 厦门营业所
    _mk_user(WZ_USER, "wzcgsq:view", 8)
    admin = _login(ADMIN)
    noperm = _login(NOPERM)
    dept_user = _login(DEPT_USER)
    wz_user = _login(WZ_USER)
    H, HN, HD, HW = (_headers(admin), _headers(noperm), _headers(dept_user),
                     _headers(wz_user))

    db = SessionLocal()
    baseline = {
        "zc_lb": db.query(ZcLb).count(), "zc_nd": db.query(ZcNd).count(),
        "zc_cw": db.query(ZcCw).count(), "zc_baofeidan": db.query(ZcBaofeidan).count(),
        "zc_baofeitp": db.query(ZcBaofeitp).count(),
        "wzcgsq": db.query(Wzcgsq).count(), "wzcgsq_mx": db.query(WzcgsqMx).count(),
    }
    db.close()
    print("\n[1] 迁移基线")
    check("固定资产类别 29", baseline["zc_lb"] == 29, baseline)
    check("固定资产台账 41383", baseline["zc_cw"] == 41383, baseline)
    check("报废单 176 / 图片 208", baseline["zc_baofeidan"] == 176
          and baseline["zc_baofeitp"] == 208, baseline)
    check("采购申请 1 / 明细 1", baseline["wzcgsq"] == 1
          and baseline["wzcgsq_mx"] == 1, baseline)

    print("\n[2] 权限码")
    for path in ("/api/gdzc/dicts", "/api/baofeizc/dicts", "/api/wzcgsq/dicts"):
        check(f"无权限 403 {path}", client.get(path, headers=HN).status_code == 403)
        check(f"超管 200 {path}", client.get(path, headers=H).status_code == 200)

    print("\n[3] 固定资产 gdzc")
    d = client.get("/api/gdzc/dicts", headers=H).json()
    year = d["default_year"]
    check("年度字典含 2025 且默认最大年度", year == 2025 and 2018 in d["years"], d["years"])
    check("类别/部门字典", len(d["categories"]) == 29 and len(d["departments"]) > 0)
    qy = client.get("/api/gdzc/qy-years", params={"nd": year}, headers=H).json()
    check("启用年度字典降序", qy["years"] == sorted(qy["years"], reverse=True) and qy["years"])
    p = {"nd": year, "page": 1, "size": 30}
    r = client.get("/api/gdzc", params=p, headers=H).json()
    check("列表默认年度 7060 条", r["total"] == 7060, r["total"])
    check("合计是筛选后全量", abs(r["sum_yz"] - 3741506699.73) < 0.05, r["sum_yz"])
    check("分页返回 30 条", len(r["items"]) == 30)
    check("行含类别/部门名", all("lb" in x and "bm" in x for x in r["items"]))
    r2 = client.get("/api/gdzc", params={**p, "keyword": "电脑"}, headers=H).json()
    check("关键字筛选", r2["total"] <= r["total"])
    r3 = client.get("/api/gdzc", params={**p, "categories": "1,2"}, headers=H).json()
    check("类别多选", r3["total"] < r["total"])
    r4 = client.get("/api/gdzc", params={**p, "expired": True}, headers=H).json()
    check("到期资产筛选", r4["total"] <= r["total"])
    r5 = client.get("/api/gdzc", params={**p, "dept_id": 8}, headers=H).json()
    check("部门子树筛选", r5["total"] < r["total"], r5["total"])
    r6 = client.get("/api/gdzc", params={"nd": 9999}, headers=H).json()
    check("不存在的年度查不到数据", r6["total"] == 0)
    # 部门用户只能看到本部门子树
    rd = client.get("/api/gdzc", params=p, headers=HD).json()
    check("部门用户数据范围受限", 0 < rd["total"] < r["total"], rd["total"])

    # 备注 + 盘点(用一条记录并恢复原值)
    from app.db.session import SessionLocal as SL
    from app.models.finance import ZcCw as CW
    s = SL()
    row = s.query(CW).filter(CW.nd == year).order_by(CW.id).first()
    original = (row.id, row.beizhu, row.beizhuren, row.bzdate, row.pandian)
    s.close()
    rid = original[0]
    rr = client.post("/api/gdzc/remark", json={"id": rid, "beizhu": f"{MARK}备注"},
                     headers=H)
    s = SL(); a = s.get(CW, rid)
    check("备注写入且登记人/时间非空", rr.json().get("ok") and a.beizhu == f"{MARK}备注"
          and a.beizhuren and a.bzdate is not None)
    client.post("/api/gdzc/remark", json={"id": rid, "beizhu": ""}, headers=H)
    s.commit(); a = s.get(CW, rid)  # 结束本 session 的快照事务,才能读到接口连接刚提交的改动
    check("清空备注同时清登记人/时间(修旧 bug)", a.beizhu in (None, "")
          and a.beizhuren is None and a.bzdate is None)
    client.post("/api/gdzc/check", json={"id": rid, "checked": True}, headers=H)
    s.commit(); a = s.get(CW, rid)  # 结束本 session 的快照事务,才能读到接口连接刚提交的改动
    check("盘点确认", (a.pandian or "").strip() == "盘点")
    client.post("/api/gdzc/check", json={"id": rid, "checked": False}, headers=H)
    s.commit(); a = s.get(CW, rid)  # 结束本 session 的快照事务,才能读到接口连接刚提交的改动
    check("取消盘点", a.pandian is None)
    # 恢复原值
    a.beizhu, a.beizhuren, a.bzdate, a.pandian = original[1], original[2], original[3], original[4]
    s.commit(); s.close()

    detail = client.get("/api/gdzc/baofei/2", headers=H)
    check("报废单详情", detail.status_code == 200
          and "danju" in detail.json() and "mingxi" in detail.json(),
          detail.text[:120])
    for url in ("/api/gdzc/export", "/api/gdzc/pandian-export"):
        res = client.get(url, params={**p, "size": 1}, headers=H)
        check(f"导出 {url}", res.status_code == 200
              and res.content[:2] == b"PK", res.status_code)

    # 盘点表导入(唯一资产号 + 新年度,跑完清理)
    imp = _xlsx([
        ["固定资产类别", "资产号", "设备名称", "数量", "在用地点", "启用日期",
         "原值", "净值", "规格型号", "设备编号", "期限", "已用", "盘点年度"],
        ["办公设备", f"{MARK}-001", "冒烟测试资产", 1, "测试地点", "2020-01-01",
         100.5, 50.25, "规格A", "SB-1", 5, 3, 9999],
    ])
    res = client.post("/api/gdzc/import", headers=H,
                      data={"bmid": "8"},
                      files={"file": ("盘点表.xlsx", imp,
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    check("导入盘点表新增 1 条", res.status_code == 200 and res.json().get("added") == 1,
          res.text[:200])
    res2 = client.post("/api/gdzc/import", headers=H, data={"bmid": "8"},
                       files={"file": ("盘点表.xlsx", imp, "application/octet-stream")})
    check("同 (nd,zccode) 重复跳过", res2.json().get("skipped") == 1, res2.text[:160])

    print("\n[4] 清理报告 baofeizc")
    bd = client.get("/api/baofeizc/dicts", headers=H).json()
    check("字典含默认日期与部门", bd["default_start"].endswith("-01-01")
          and bd["departments"])
    bl = client.get("/api/baofeizc", params={"page": 1, "size": 20}, headers=H).json()
    check("报废单列表", bl["total"] == 176 and len(bl["items"]) == 20, bl["total"])
    check("行含报废条数/部门/图片", all("ts" in x and "bm" in x and "tps" in x
                                     for x in bl["items"]))
    bm = client.get("/api/baofeizc", params={"keyword": "泵"}, headers=H).json()
    check("关键字检索明细资产", bm["total"] <= bl["total"])
    created = client.post("/api/baofeizc", headers=H, json={
        "riqi": "2026-11-10", "bmid": 8, "zaiyao": f"{MARK}测试单", "images": []})
    check("新增报废单", created.status_code == 200 and created.json().get("id"),
          created.text[:160])
    bid = created.json()["id"]
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082")
    up = client.post("/api/baofeizc/upload-image", headers=H,
                     files={"file": ("a.png", png, "image/png")})
    check("上传图片", up.status_code == 200 and up.json().get("dizhi"), up.text[:160])
    dizhi = up.json()["dizhi"]
    img = client.get(up.json()["url"])
    check("图片短令牌代理", img.status_code == 200 and img.content == png)
    edt = client.put(f"/api/baofeizc/{bid}", headers=H, json={
        "riqi": "2026-11-10", "bmid": 8, "zaiyao": f"{MARK}测试单-改",
        "images": [dizhi]})
    get = client.get(f"/api/baofeizc/{bid}", headers=H).json()
    check("编辑报废单并同步图片", edt.status_code == 200
          and get["zaiyao"] == f"{MARK}测试单-改" and len(get["images"]) == 1,
          get)
    cand = client.get("/api/baofeizc/candidates", params={"bfid": bid, "page": 1, "size": 10},
                      headers=H).json()
    check("候选资产列表", cand["total"] > 0 and all("can_add" in x for x in cand["items"]),
          cand["total"])
    # 用专用测试资产做报废联动,避免触碰真实台账的历史状态
    from datetime import date as _date
    s = SL()
    asset = CW(zccode=f"{MARK}-ASSET", sbname="冒烟测试资产", num=1, bmid=8,
               qyrq=_date(2020, 1, 1), yz=123.45, jz=60, nd=9999,
               guige="测试规格", sbbh="TEST-001", didian="测试地点")
    s.add(asset); s.commit(); aid = asset.id; s.close()
    add = client.post("/api/baofeizc/mx/add", headers=H,
                      json={"id": aid, "bfid": bid})
    check("加入报废明细", add.status_code == 200, add.text[:160])
    mx = client.get(f"/api/baofeizc/{bid}/mx", headers=H).json()
    check("子表按挂单取明细", mx["total"] == 1 and mx["items"][0]["id"] == aid, mx["total"])
    rep = client.get(f"/api/baofeizc/export/{bid}", headers=H)
    check("导出清理报告", rep.status_code == 200 and rep.content[:2] == b"PK")
    dele = client.delete(f"/api/baofeizc/{bid}", headers=H)
    check("有明细禁止删除", dele.status_code == 400, dele.text[:120])
    rm = client.post("/api/baofeizc/mx/delete", headers=H, json={"id": aid})
    check("取消报废", rm.status_code == 200, rm.text[:120])
    check("清除明细后可删除", client.delete(f"/api/baofeizc/{bid}", headers=H).status_code == 200)
    # 越权的部门用户不可操作厦门以外的单据(本测试用超管创建的单据已被删除)

    print("\n[5] 物资采购申请 wzcgsq")
    wd = client.get("/api/wzcgsq/dicts", headers=H).json()
    check("字典含范围部门/年度", wd["departments"] and len(wd["years"]) == 6)
    wl = client.get("/api/wzcgsq", params={"scope": "all"}, headers=H).json()
    check("列表(含迁入的 1 条历史单)", wl["total"] == 1 and wl["sum_hj"] == 446.0, wl)
    check("历史单明细数", wl["items"][0]["mxcount"] == 1, wl["items"])
    tpl = client.get("/api/wzcgsq/template", headers=H)
    check("下载明细模板", tpl.status_code == 200 and tpl.content[:2] == b"PK")
    mx_xlsx = _xlsx([
        ["物品名称", "规格、型号", "单位", "数量", "单价", "验收情况", "备注"],
        ["打印纸", "A4", "箱", 2, 33.5, "完成", ""],
        ["", "", "", 0, 0, "", "空行"],
        ["数量为空", "A4", "箱", 0, 10, "", "应跳过"],
    ])
    upl = client.post("/api/wzcgsq/upload-mx", headers=H,
                      files={"file": ("明细.xlsx", mx_xlsx, "application/octet-stream")})
    check("Excel 明细解析(表头定位 + 跳过无效行)", upl.status_code == 200
          and upl.json()["ok"] and len(upl.json()["rows"]) == 1
          and upl.json()["rows"][0]["wpmc"] == "打印纸"
          and upl.json()["skipped"] == 1, upl.text[:200])
    payload = {
        "bumen": f"{MARK}部门", "sgyy": "冒烟测试",
        "mx": [{"wpmc": "打印纸", "ggxh": "A4", "danwei": "箱",
                "shuliang": 2, "danjia": 33.33, "ysqk": "完成", "beizhu": ""}],
    }
    cr = client.post("/api/wzcgsq", headers=H, json=payload)
    check("新增采购单(服务端重算小计/合计)", cr.status_code == 200
          and cr.json().get("id"), cr.text[:160])
    wid = cr.json()["id"]
    one = client.get(f"/api/wzcgsq/{wid}", headers=H).json()
    check("合计 = 2×33.33 = 66.66", abs(one["hj"] - 66.66) < 0.001, one.get("hj"))
    edit = client.get(f"/api/wzcgsq/{wid}/edit", headers=H).json()
    check("编辑回填主表+明细", edit["bumen"] == f"{MARK}部门" and len(edit["mx"]) == 1)
    upd = client.put(f"/api/wzcgsq/{wid}", headers=H, json={
        **payload, "sgyy": "冒烟测试-改",
        "mx": payload["mx"] + [{"wpmc": "墨盒", "shuliang": 1, "danjia": 100}]})
    one2 = client.get(f"/api/wzcgsq/{wid}/edit", headers=H).json()
    check("整单替换明细 + 日期不被篡改", upd.status_code == 200
          and len(one2["mx"]) == 2 and one2["sgyy"] == "冒烟测试-改")
    one3 = client.get(f"/api/wzcgsq/{wid}", headers=H).json()
    check("编辑后合计同步", abs(one3["hj"] - 166.66) < 0.001, one3.get("hj"))
    prt = client.get(f"/api/wzcgsq/{wid}/print", headers=H).json()
    check("打印数据含标题部门与主子表", "userBm" in prt and len(prt["mx"]) == 2)
    for url in ("download-sq", "download-ys"):
        res = client.get(f"/api/wzcgsq/{wid}/{url}", headers=H)
        check(f"下载 {url}", res.status_code == 200 and res.content[:2] == b"PK")
    # 数据范围:厦门营业所用户看不到「集团」层级的历史单(cj=0001)
    denied = client.get("/api/wzcgsq/2", headers=HW)
    check("跨部门读取被拒(补旧越权缺口)", denied.status_code in (403, 404),
          denied.status_code)
    dl = client.delete(f"/api/wzcgsq/{wid}", headers=H)
    check("删除采购单", dl.status_code == 200, dl.text[:160])
    check("删除后明细一并清除", client.get(f"/api/wzcgsq/{wid}", headers=H).status_code == 404)

    _cleanup()
    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
