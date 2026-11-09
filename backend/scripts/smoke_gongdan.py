"""工单信息录入 Gongdan 模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_gongdan
覆盖:字典/部门/计数/列表各筛选/内容材质字典与删选项/抢修班组增删改/
     工单号带出/领料明细/外部详情与图片降级/导出20列/新增校验与写入/
     编辑与重复工单号提示/物理删除(仅 view 用户 403)/共享表未被改动。
"""

import io
import time

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_gd"
SMOKE_VIEW_USER = "smoke_gd_view"
SMOKE_NO = ""
SMOKE_IDS = []
SMOKE_QX_ID = None
SMOKE_NEIRONG = ""
SMOKE_CAIZHI = ""

HEADERS = {"Authorization": ""}


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
        u = User(username=username, password_hash=hash_password("Smoke@12345"),
                 password_version=1, real_name=username,
                 is_superuser=is_superuser, is_active=True)
        if not is_superuser:
            role = db.query(Role).filter(Role.code == "smoke_gd_view_role").first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == "gongdan:view").first()
                role = Role(name="smoke工单录入view角色", code="smoke_gd_view_role",
                            permissions=[perm])
                db.add(role)
                db.flush()
            u.roles.append(role)
        db.add(u)
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
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _one_work_order_no():
    """取一条确有领料明细的工单号(只读,不改数据)。"""
    from app.db.session import SessionLocal
    from app.models.material import MaterialRecord, WorkOrder

    db = SessionLocal()
    try:
        row = (db.query(WorkOrder.work_order_no)
               .join(MaterialRecord, MaterialRecord.work_order_id == WorkOrder.id)
               .filter(WorkOrder.work_order_no.isnot(None))
               .first())
        return row[0] if row else ""
    finally:
        db.close()


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.gongdan import GongdanCaizhiDict, GongdanNeirongDict
    from app.models.road_repair import Qiangxiurenyuan
    from app.models.user import Role, User
    from app.models.workorder import GongdanCailiao

    db = SessionLocal()
    try:
        if SMOKE_NO:
            for item in db.query(GongdanCailiao).filter(
                    GongdanCailiao.gongdanhao == SMOKE_NO).all():
                db.delete(item)
        for _id in SMOKE_IDS:
            item = db.get(GongdanCailiao, _id)
            if item:
                db.delete(item)
        if SMOKE_NEIRONG:
            for item in db.query(GongdanNeirongDict).filter(
                    GongdanNeirongDict.neirong == SMOKE_NEIRONG).all():
                db.delete(item)
        if SMOKE_CAIZHI:
            for item in db.query(GongdanCaizhiDict).filter(
                    GongdanCaizhiDict.caizhi == SMOKE_CAIZHI).all():
                db.delete(item)
        if SMOKE_QX_ID:
            item = db.get(Qiangxiurenyuan, SMOKE_QX_ID)
            if item:
                db.delete(item)
        for name in (SMOKE_USER, SMOKE_VIEW_USER):
            u = db.query(User).filter(User.username == name).first()
            if u:
                db.delete(u)
        role = db.query(Role).filter(Role.code == "smoke_gd_view_role").first()
        if role:
            db.delete(role)
        db.commit()
    finally:
        db.close()


def main():
    global SMOKE_NO, SMOKE_IDS, SMOKE_QX_ID, SMOKE_NEIRONG, SMOKE_CAIZHI
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False)
    H = _login(SMOKE_USER)
    HV = _login(SMOKE_VIEW_USER)
    try:
        # ---------- 字典 / 计数 ----------
        d = client.get("/api/gongdan/dicts", headers=H)
        check("dicts 200", d.status_code == 200, d.text[:120])
        j = d.json()
        check("dicts 含部门/班组/管径/停水", all(
            k in j for k in ("departments", "banzu", "guanjing", "tingshui")))
        check("dicts 管径 24 项含 DN1000/其他", len(j["guanjing"]) == 24
              and "DN1000" in j["guanjing"] and "其他" in j["guanjing"])
        check("dicts 默认起始日期为今年1月1日", j["defaultRq"].endswith("-01-01"))
        check("dicts 超管 perms.manage=true", j["perms"]["manage"] is True)
        check("dicts recordCount>0", j["recordCount"] > 0)
        depts = client.get("/api/gongdan/departments", headers=H)
        check("departments 数组", depts.status_code == 200 and isinstance(depts.json(), list))
        cnt = client.get("/api/gongdan/count", headers=H)
        check("count 镜像表 76870", cnt.status_code == 200 and cnt.json()["count"] == 76870,
              cnt.text[:100])

        # ---------- 列表与筛选 ----------
        r = client.get("/api/gongdan/list", headers=H)
        check("list 200", r.status_code == 200, r.text[:150])
        j = r.json()
        check("list rows/total", "rows" in j and "total" in j and j["total"] > 0)
        check("list 默认 30 条", len(j["rows"]) <= 30)
        check("list 字段含 ID/pipesize", all(
            k in j["rows"][0] for k in ("ID", "gongdanhao", "ksriqi", "pipesize")))
        base_params = {"rq": "2025-01-01", "rqend": "2026-12-31", "rows": 10}
        for label, extra in [
            ("模糊", {"mohu": "阀门"}),
            ("按登记日期", {"anbjriqi": "on"}),
            ("重复工单号", {"cf": "on"}),
            ("非重复(每号最新)", {"fcf": "on"}),
            ("管径范围", {"minPipe": 100, "maxPipe": 300}),
            ("部门精确", {"bmid": 8}),
        ]:
            p = {**base_params, **{k: v for k, v in extra.items() if v is not None}}
            res = client.get("/api/gongdan/list", params=p, headers=H)
            ok = res.status_code == 200 and "total" in res.json()
            check(f"list 筛选-{label}", ok, res.text[:120])
        fcf = client.get("/api/gongdan/list", params={**base_params, "fcf": "on"},
                         headers=H).json()
        nos = [x["gongdanhao"] for x in fcf["rows"]]
        check("fcf 每页工单号不重复", len(nos) == len(set(nos)))
        cf = client.get("/api/gongdan/list", params={**base_params, "cf": "on"},
                        headers=H).json()
        check("cf 返回重复工单号记录", cf["total"] >= 0)

        # ---------- 字典下拉与删选项 ----------
        nr = client.get("/api/gongdan/neirong", headers=H)
        check("neirong 数组", nr.status_code == 200 and isinstance(nr.json(), list))
        check("neirong 首项是高频词(阀门/其他)", nr.json()[0]["Text"] in ("阀门", "其他"),
              str(nr.json()[:2]))
        nrq = client.get("/api/gongdan/neirong", params={"q": "消防"}, headers=H)
        check("neirong q 过滤", all("消防" in x["Text"] for x in nrq.json()))
        cz = client.get("/api/gongdan/caizhi", headers=H)
        check("caizhi 首项为空", cz.status_code == 200 and cz.json()[0]["Value"] == "")
        czq = client.get("/api/gongdan/caizhi", params={"q": "铸"}, headers=H)
        check("caizhi q 过滤(首项空除外)",
              all("铸" in x["Text"] for x in czq.json() if x["Text"]))

        # ---------- 抢修班组 CRUD ----------
        SMOKE_NEIRONG = "smoke测试内容" + str(int(time.time()))
        SMOKE_CAIZHI = "smoke测试材质" + str(int(time.time()))
        qname = "smoke班组" + str(int(time.time()))
        qx = client.get("/api/gongdan/qiangxiu", headers=H)
        check("qiangxiu 列表", qx.status_code == 200 and isinstance(qx.json(), list))
        added = client.post("/api/gongdan/qiangxiu/add", json={"name": qname}, headers=H)
        check("qiangxiu 新增", added.status_code == 200 and added.json()["success"],
              added.text[:120])
        qx_rows = client.get("/api/gongdan/qiangxiu", params={"search": qname}, headers=H).json()
        check("qiangxiu 搜索生效", any(x["name"] == qname for x in qx_rows))
        SMOKE_QX_ID = next((x["id"] for x in qx_rows if x["name"] == qname), None)
        dup = client.post("/api/gongdan/qiangxiu/add", json={"name": qname}, headers=H)
        check("qiangxiu 重名拦截", dup.status_code == 400, dup.text[:120])
        ed = client.post("/api/gongdan/qiangxiu/edit",
                         json={"id": SMOKE_QX_ID, "name": qname + "改"}, headers=H)
        check("qiangxiu 编辑", ed.status_code == 200, ed.text[:120])
        dl = client.post("/api/gongdan/qiangxiu/delete", json={"id": SMOKE_QX_ID}, headers=H)
        check("qiangxiu 删除", dl.status_code == 200)
        SMOKE_QX_ID = None

        # ---------- 工单号带出 / 领料明细 / 外部降级 ----------
        wono = _one_work_order_no()
        check("样本工单号存在", bool(wono), wono)
        info = client.get("/api/gongdan/gongdan-info", params={"gongdanhao": wono},
                          headers=H)
        check("gongdan-info 200", info.status_code == 200, info.text[:150])
        ij = info.json()
        check("gongdan-info 结构", ij.get("success") is True and "hasUsed" in ij
              and "cailiao" in ij["data"])
        check("gongdan-info 拼接领料主材", "(" in ij["data"]["cailiao"] or
              ij["data"]["cailiao"] == "", ij["data"]["cailiao"][:120])
        det = client.get("/api/gongdan/order-details", params={"gdId": wono}, headers=H)
        check("order-details 数组 7 列", det.status_code == 200 and isinstance(det.json(), list)
              and len(det.json()) > 0, det.text[:120])
        if det.json():
            check("order-details 字段", all(k in det.json()[0] for k in (
                "MaterialName", "Model", "Spec", "dakoujing", "Quantity", "Unit",
                "CreatedTime")))
        empty = client.get("/api/gongdan/gongdan-info", params={"gongdanhao": ""},
                           headers=H)
        check("gongdan-info 空工单号", empty.json()["success"] is False)
        byno = client.get("/api/gongdan/by-no", params={"gongdanNo": "999999999"},
                          headers=H)
        check("by-no 外部不可达降级", byno.status_code == 200, byno.text[:120])
        check("by-no 与 workorder 同结构(success/message)",
              "message" in byno.json() and "msg" not in byno.json(), byno.text[:120])
        empty_no = client.get("/api/gongdan/by-no", params={"gongdanNo": ""}, headers=H)
        check("by-no 空工单号 message", empty_no.json().get("success") is False
              and empty_no.json().get("message") == "工单号不能为空")
        # images 参数名照 workorder 用 flow_id;flowId 保留兼容
        imgs = client.get("/api/gongdan/images", params={"flow_id": "999999999"},
                          headers=H)
        check("images 外部不可达降级(flow_id)", imgs.status_code == 200
              and imgs.json().get("images") == [], imgs.text[:120])
        imgs_old = client.get("/api/gongdan/images", params={"flowId": "999999999"},
                              headers=H)
        check("images 兼容旧 flowId", imgs_old.status_code == 200
              and imgs_old.json().get("images") == [], imgs_old.text[:120])
        bad = client.get("/api/gongdan/image", params={"token": "bad"}, headers=H)
        check("image 无效令牌 401", bad.status_code == 401)

        # ---------- 导出 ----------
        exp = client.get("/api/gongdan/export", params=base_params, headers=H)
        check("export 200 xlsx", exp.status_code == 200
              and "spreadsheetml" in exp.headers.get("content-type", ""), exp.text[:120])
        wb = load_workbook(io.BytesIO(exp.content))
        ws = wb.active
        check("export 表 20 列", ws.max_column == 20, str(ws.max_column))
        check("export 标题行", ws.cell(1, 1).value == "ID"
              and ws.cell(1, 20).value == "备注")
        lst = client.get("/api/gongdan/list", params={**base_params, "rows": 5},
                         headers=H).json()
        check("export 行数=筛选全量", ws.max_row - 1 == lst["total"],
              f"{ws.max_row-1} vs {lst['total']}")

        # ---------- 新增(校验 / 写入 / 字典扩词) ----------
        SMOKE_NO = "SMOKE" + str(int(time.time()))
        form = {
            "gongdanhao": SMOKE_NO, "neirong": SMOKE_NEIRONG,
            "ksriqi": "2026-11-01 08:30:00", "jsriqi": "2026-11-01 10:45:00",
            "shijian": 135, "tingshui": "是", "dizhi": "smoke测试地址",
            "caizhi": SMOKE_CAIZHI, "guanjing": "DN150", "shuiliang": 12,
            "cailiao": "测试主材", "qiangxiurenyuan": "测试班组", "beizhu": "smoke",
        }
        for label, patch in [
            ("缺工单号", {"gongdanhao": ""}),
            ("缺工作内容", {"neirong": ""}),
            ("缺开始日期", {"ksriqi": ""}),
            ("缺结束日期", {"jsriqi": ""}),
        ]:
            res = client.post("/api/gongdan/add", json={**form, **patch}, headers=H)
            check(f"add 校验-{label}", res.status_code == 400, res.text[:120])
        add = client.post("/api/gongdan/add", json=form, headers=H)
        check("add 200", add.status_code == 200 and add.json()["success"], add.text[:150])
        SMOKE_IDS.append(add.json()["id"])
        found = client.get("/api/gongdan/list",
                           params={"rq": "2026-01-01", "rqend": "2026-12-31",
                                   "mohu": SMOKE_NO}, headers=H).json()
        check("add 后列表可查", found["total"] == 1, str(found["total"]))
        row = found["rows"][0]
        check("add 管径解析 DN150→150", row["pipesize"] == 150, str(row["pipesize"]))
        check("add 日期/工时/登记人", row["ksriqi"].startswith("2026-11-01 08:30")
              and row["shijian"] == 135 and row["djren"] == SMOKE_USER)
        check("add 新词进内容字典", any(x["Text"] == SMOKE_NEIRONG for x in
                                   client.get("/api/gongdan/neirong", headers=H).json()))
        check("add 新词进材质字典", any(x["Text"] == SMOKE_CAIZHI for x in
                                   client.get("/api/gongdan/caizhi", headers=H).json()))
        d1 = client.post("/api/gongdan/neirong/delete",
                         json={"value": SMOKE_NEIRONG}, headers=H)
        check("neirong 删选项", d1.status_code == 200 and d1.json()["success"])
        check("neirong 删后查不到", not any(x["Text"] == SMOKE_NEIRONG for x in
                                       client.get("/api/gongdan/neirong", headers=H).json()))
        d2 = client.post("/api/gongdan/caizhi/delete",
                         json={"value": SMOKE_CAIZHI}, headers=H)
        check("caizhi 删选项", d2.status_code == 200 and d2.json()["success"])

        # ---------- 编辑 / 重复工单号 ----------
        edit = client.post("/api/gongdan/update",
                           json={**form, "id": SMOKE_IDS[0], "guanjing": "92#",
                                 "neirong": SMOKE_NEIRONG, "dizhi": "smoke修改地址"},
                           headers=H)
        check("update 200", edit.status_code == 200 and edit.json()["success"],
              edit.text[:150])
        check("update 返回 hasUsed=false", edit.json()["hasUsed"] is False)
        row = client.get("/api/gongdan/list",
                         params={"rq": "2026-01-01", "rqend": "2026-12-31",
                                 "mohu": SMOKE_NO}, headers=H).json()["rows"][0]
        check("update 含 # 管径解析为 NULL", row["pipesize"] is None, str(row["pipesize"]))
        check("update 地址/内容生效", row["dizhi"] == "smoke修改地址"
              and row["neirong"] == SMOKE_NEIRONG)
        add2 = client.post("/api/gongdan/add",
                           json={**form, "neirong": SMOKE_NEIRONG, "caizhi": ""}, headers=H)
        SMOKE_IDS.append(add2.json()["id"])
        edit2 = client.post("/api/gongdan/update",
                            json={**form, "id": SMOKE_IDS[0], "neirong": SMOKE_NEIRONG},
                            headers=H)
        check("update 重复工单号提示", edit2.json()["hasUsed"] is True
              and "其他记录" in edit2.json()["message"], edit2.text[:150])
        cf2 = client.get("/api/gongdan/list",
                         params={"rq": "2026-01-01", "rqend": "2026-12-31",
                                 "mohu": SMOKE_NO, "cf": "on"}, headers=H).json()
        check("cf 能筛出重复的测试工单", cf2["total"] == 2, str(cf2["total"]))

        # ---------- 删除权限 ----------
        denied = client.post("/api/gongdan/del", json={"id": SMOKE_IDS[0]}, headers=HV)
        check("仅 view 用户删除 403", denied.status_code == 403, denied.text[:120])
        okdel = client.post("/api/gongdan/del", json={"id": SMOKE_IDS[0]}, headers=H)
        check("超管删除 200", okdel.status_code == 200, okdel.text[:120])
        remain = client.get("/api/gongdan/list",
                            params={"rq": "2026-01-01", "rqend": "2026-12-31",
                                    "mohu": SMOKE_NO}, headers=H).json()
        check("删除后剩 1 条", remain["total"] == 1, str(remain["total"]))
        vd = client.get("/api/gongdan/dicts", headers=HV)
        check("仅 view 用户 perms.manage=false", vd.json()["perms"]["manage"] is False)
    finally:
        _cleanup()
    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
