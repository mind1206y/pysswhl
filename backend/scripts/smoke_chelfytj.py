"""车辆费用明细统计(chelfytj)模块 smoke 测试(TestClient,跑完自动清理)。

用法(backend 目录下): python -m scripts.smoke_chelfytj
覆盖:权限码、列表口径(车辆数/序号连续/分页)、四表金额与直查 DB 对齐、
日期区间、状态/非油卡/类型/用途/关键字/部门子树筛选、footer 合计、字典、Excel 导出。
"""

from base64 import b64encode

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_cftj"
SMOKE_DEPT_USER = "smoke_cftj_dept"
SMOKE_NO_PERM = "smoke_cftj_noperm"


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
        if db.query(User).filter(User.username == username).first() is not None:
            return
        user = User(username=username, password_hash=hash_password("Smoke@12345"),
                    password_version=1, real_name=username,
                    is_superuser=perm_code is None, is_active=True)
        if perm_code is not None:
            code = f"smoke_cftj_role_{perm_code.replace(':', '_')}"
            role = db.query(Role).filter(Role.code == code).first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == perm_code).first()
                role = Role(name=f"smoke费用统计{perm_code}", code=code, permissions=[perm])
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

    db = SessionLocal()
    try:
        for name in (SMOKE_USER, SMOKE_DEPT_USER, SMOKE_NO_PERM):
            user = db.query(User).filter(User.username == name).first()
            if user is not None:
                db.delete(user)
                db.commit()
        for role in db.query(Role).filter(Role.code.like("smoke_cftj_role_%")).all():
            db.delete(role)
        db.commit()
    finally:
        db.close()


def _subtree(db, root):
    from app.models.user import Department

    ids = {root}
    while True:
        children = (db.query(Department.id)
                    .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids)).all())
        if not children:
            break
        ids |= {c[0] for c in children}
    return ids


def _expected_footer(db, car_ids, ksd, jsd):
    """直查 DB 计算期望 footer(与 summarize 同口径)。"""
    from sqlalchemy import func

    from app.models.vehicle import ClBaoxian, ClFeiyong, ClWxdan, PlusOil

    if not car_ids:
        return {k: 0 for k in ("noil", "weixiu", "baoxian", "gaosu", "tingche", "xiche", "ye")}
    noil = db.query(func.sum(PlusOil.jine)).filter(
        PlusOil.cheid.in_(car_ids), PlusOil.ptime >= ksd, PlusOil.ptime <= jsd).scalar() or 0
    wx = db.query(func.sum(ClWxdan.jine)).filter(
        ClWxdan.cheid.in_(car_ids), ClWxdan.jcriqi >= ksd.date(), ClWxdan.jcriqi <= jsd.date()).scalar() or 0
    bx = db.query(func.sum(ClBaoxian.jine)).filter(
        ClBaoxian.cheid.in_(car_ids), ClBaoxian.tbdate >= ksd.date(), ClBaoxian.tbdate <= jsd.date()).scalar() or 0
    from datetime import datetime, timedelta

    cf = (db.query(ClFeiyong.lx, func.sum(ClFeiyong.jine))
          .filter(ClFeiyong.cheid.in_(car_ids),
                  ClFeiyong.feiyongdate >= ksd.date(), ClFeiyong.feiyongdate <= jsd.date())
          .group_by(ClFeiyong.lx).all())
    fees = {lx: (v or 0) for lx, v in cf}
    g, t, x = fees.get("高速", 0), fees.get("停车", 0), fees.get("洗车", 0)
    noil, wx, bx = float(noil), float(wx), float(bx)
    return {"noil": round(noil, 2), "weixiu": round(wx, 2), "baoxian": round(bx, 2),
            "gaosu": round(float(g), 2), "tingche": round(float(t), 2), "xiche": round(float(x), 2),
            "ye": round(noil + wx + bx + float(g) + float(t) + float(x), 2)}


def main():
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.db.session import SessionLocal
    from app.models.vehicle import ClChe, PlusOil

    _cleanup()
    db = SessionLocal()
    try:
        n_all = db.query(ClChe).count()                     # zt=0 含已删除
        n_1 = db.query(ClChe).filter(ClChe.delf == 1).count()
        n_2 = db.query(ClChe).filter(ClChe.delf == 2).count()
        n_0 = db.query(ClChe).filter(ClChe.delf == 0).count()
        n_nocd = db.query(ClChe).filter(ClChe.yongtu != "油卡").count()
        sample = (db.query(ClChe).filter(ClChe.chehao != "", ClChe.delf == 1)
                  .order_by(ClChe.chehao).first())
        kw = sample.chehao[:2] if sample else "X"
        # 关键字与后端同口径:12 个文本字段 OR 模糊
        from sqlalchemy import or_

        from app.services.chelfytj import MOHU_FIELDS

        n_kw = db.query(ClChe).filter(or_(*[f.like(f"%{kw}%") for f in MOHU_FIELDS])).count()
        lx_used = [r[0] for r in db.query(ClChe.lx).filter(ClChe.lx != "").distinct().all()]
        lx_top = max(lx_used, key=lambda v: db.query(ClChe).filter(ClChe.lx == v).count()) if lx_used else None
        n_lx = db.query(ClChe).filter(ClChe.lx == lx_top).count() if lx_top else 0
        yt_used = [r[0] for r in db.query(ClChe.yongtu).filter(ClChe.yongtu != "").distinct().all()]
        yt_top = max(yt_used, key=lambda v: db.query(ClChe).filter(ClChe.yongtu == v).count()) if yt_used else None
        n_yt = db.query(ClChe).filter(ClChe.yongtu == yt_top).count() if yt_top else 0

        # 部门子树:选一个车辆最多的部门
        cars_dept = (db.query(ClChe.bmid, func.count(ClChe.id))
                     .filter(ClChe.bmid.isnot(None)).group_by(ClChe.bmid).all())
        dept_top = max(cars_dept, key=lambda x: x[1])[0] if cars_dept else None
        dept_ids = sorted(_subtree(db, dept_top)) if dept_top else []
        n_dept = db.query(ClChe).filter(ClChe.bmid.in_(dept_ids)).count() if dept_top else 0

        # 有加油记录的车:做日期区间校验
        po = (db.query(PlusOil).filter(PlusOil.cheid.isnot(None), PlusOil.ptime.isnot(None))
              .order_by(PlusOil.ptime.desc()).first())
        range_rq = range_rqend = None
        exp_noil = 0.0
        if po:
            y, m = po.ptime.year, po.ptime.month
            range_rq = f"{y}-{m:02d}-01"
            nxt = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
            range_rqend = (nxt - timedelta(days=1)).strftime("%Y-%m-%d")
            exp_noil = float(db.query(func.sum(PlusOil.jine)).filter(
                PlusOil.cheid == po.cheid, PlusOil.ptime >= datetime(y, m, 1),
                PlusOil.ptime < nxt).scalar() or 0)
            range_car_id = po.cheid

        year = datetime.now().year
        ksd = datetime(year, 1, 1)
        jsd = datetime(year, 12, 31, 23, 59, 59)
        all_ids = [c.id for c in db.query(ClChe.id).all()]
        exp_footer = _expected_footer(db, all_ids, ksd, jsd)
        n_sample = sample.id if sample else None
    finally:
        db.close()

    _mk_user(SMOKE_USER)                                     # 超管
    # SMOKE_NO_PERM 不走 _mk_user(perm_code=None 会建成超管),下面手动建普通无权限账号
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import User
    sdb = SessionLocal()
    try:
        if sdb.query(User).filter(User.username == SMOKE_NO_PERM).first() is None:
            sdb.add(User(username=SMOKE_NO_PERM, password_hash=hash_password("Smoke@12345"),
                         password_version=1, real_name=SMOKE_NO_PERM,
                         is_superuser=False, is_active=True))
            sdb.commit()
    finally:
        sdb.close()
    if dept_top:
        _mk_user(SMOKE_DEPT_USER, perm_code="chelfytj:view", dept_id=dept_top)

    token = _login(SMOKE_USER)
    H = {"Authorization": f"Bearer {token}"}

    # ===== 权限 =====
    r = client.get("/api/chelfytj", headers=H)
    check("超管列表 200", r.status_code == 200, r.text[:120])
    noperm = _login(SMOKE_NO_PERM)
    HN = {"Authorization": f"Bearer {noperm}"}
    r = client.get("/api/chelfytj", headers=HN)
    check("无权限列表 403", r.status_code == 403, str(r.status_code))
    r = client.get("/api/chelfytj/dicts", headers=HN)
    check("无权限字典 403", r.status_code == 403, str(r.status_code))
    r = client.get("/api/chelfytj/export", headers=HN)
    check("无权限导出 403", r.status_code == 403, str(r.status_code))

    # ===== 列表口径 =====
    d = r.json() if False else client.get("/api/chelfytj", headers=H).json()
    check(f"total=全部车辆数({n_all})", d["total"] == n_all, f'got {d["total"]}')
    check("默认页 20 行", len(d["rows"]) == min(20, n_all))
    check("序号从 1 连续", d["rows"][0]["ID"] == 1)
    check("footer oil=合计", d["footer"]["oil"] == "合计")
    for k in ("noil", "weixiu", "baoxian", "gaosu", "tingche", "xiche", "ye"):
        check(f"footer.{k} 对齐直查 DB", abs(d["footer"][k] - exp_footer[k]) < 0.01,
              f'api={d["footer"][k]} db={exp_footer[k]}')
    check("行 ye=各分项之和",
          all(abs(r_["ye"] - (r_["noil"] + r_["weixiu"] + r_["baoxian"] +
                              r_["gaosu"] + r_["tingche"] + r_["xiche"])) < 0.01
              for r_ in d["rows"]))

    # 分页:第二页序号接续
    d2 = client.get("/api/chelfytj", headers=H, params={"page": 2, "size": 2}).json()
    check("size=2 取 2 行", len(d2["rows"]) == min(2, n_all))
    if n_all > 2:
        check("第二页序号=3 起接续", d2["rows"][0]["ID"] == 3, str(d2["rows"][0]["ID"]))
    check("分页 total 不变", d2["total"] == n_all)

    # 状态
    check("zt=1 正常车数", client.get("/api/chelfytj", headers=H, params={"zt": 1}).json()["total"] == n_1)
    check("zt=2 报废车数", client.get("/api/chelfytj", headers=H, params={"zt": 2}).json()["total"] == n_2)
    check("zt=3 已删除车数", client.get("/api/chelfytj", headers=H, params={"zt": 3}).json()["total"] == n_0)

    # 非油卡 / 类型 / 用途 / 关键字
    check("非油卡过滤", client.get("/api/chelfytj", headers=H, params={"nocd": True}).json()["total"] == n_nocd)
    if lx_top:
        check("类型过滤", client.get("/api/chelfytj", headers=H,
              params={"chellx": lx_top}).json()["total"] == n_lx)
    if yt_top:
        check("用途过滤", client.get("/api/chelfytj", headers=H,
              params={"chelyt": yt_top}).json()["total"] == n_yt)
    if n_sample:
        check("关键字模糊", client.get("/api/chelfytj", headers=H,
              params={"sousou": kw}).json()["total"] == n_kw)

    # 部门子树
    if dept_top:
        check("部门子树过滤", client.get("/api/chelfytj", headers=H,
              params={"bmid": dept_top}).json()["total"] == n_dept)
        dt = _login(SMOKE_DEPT_USER)
        HD = {"Authorization": f"Bearer {dt}"}
        dd = client.get("/api/chelfytj", headers=HD).json()
        check(f"部门用户只见子树({n_dept})", dd["total"] == n_dept, f'got {dd["total"]}')
        ddict = client.get("/api/chelfytj/dicts", headers=HD).json()
        check("部门下拉限子树", all(x["id"] in set(dept_ids) for x in ddict["departments"]))

    # 日期区间:该车当月油费与直查一致
    if range_rq:
        dr = client.get("/api/chelfytj", headers=H,
                        params={"rq": range_rq, "rqend": range_rqend, "size": 500}).json()
        row = next((r_ for r_ in dr["rows"] if r_["cheid"] == range_car_id), None)
        check("区间内车存在", row is not None)
        if row:
            check("区间油费对齐 DB", abs(row["noil"] - exp_noil) < 0.01,
                  f'api={row["noil"]} db={exp_noil}')

    # 字典
    dict_all = client.get("/api/chelfytj/dicts", headers=H).json()
    check("字典类型非空", len(dict_all["chellx"]) > 0)
    check("字典类型=DB 去重", sorted(dict_all["chellx"]) == sorted(lx_used))
    check("字典用途=DB 去重", sorted(dict_all["chelyt"]) == sorted(yt_used))

    # ===== 导出 =====
    r = client.get("/api/chelfytj/export", headers=H)
    check("导出 200", r.status_code == 200, str(r.status_code))
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(r.content))
    ws = wb.active
    check("sheet 名=费用统计", ws.title == "费用统计")
    hdr = [c.value for c in ws[2]]
    check("导出表头照旧 10 列",
          hdr == ["序号", "车牌号", "油费", "维保费", "保险费", "高速费", "停车费", "洗车费", "小计", "备注"], str(hdr))
    check(f"数据行=车辆数({n_all})", ws.max_row == n_all + 3, f"rows={ws.max_row}")
    title = ws.cell(row=1, column=1).value
    check("标题含年份+统计表", str(title).endswith("车辆各类费用统计表") and str(year) in str(title), str(title))
    total_row = ws.max_row
    ye_col = 9  # 小计列
    excel_sum = sum(ws.cell(row=r_, column=ye_col).value or 0 for r_ in range(3, total_row))
    check("导出小计列和=footer.ye", abs(excel_sum - d["footer"]["ye"]) < 0.05,
          f'excel={excel_sum} footer={d["footer"]["ye"]}')
    check("合计行首格=合计", ws.cell(row=total_row, column=1).value == "合计")

    print(f"\n===== chelfytj smoke: {PASS} ok / {FAIL} fail =====")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
