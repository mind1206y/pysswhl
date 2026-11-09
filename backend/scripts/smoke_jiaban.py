"""维抢修加班 Jiaban 模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_jiaban
覆盖:列表各筛选与合计/人员增删改查重/人员下拉与部门选项/工单号带出(查重)/
     新增多人员+时间冲突+跨天/编辑冲突排除自身/删除本人限制/
     4 个导出(按姓名/按地址/工资汇总/加班申请模板)/附件上传下载删除与扩展名白名单/
     无权限用户 403/迁移附件文件缺失下载兜底/共享表 gongdancailiao 未被改动。
"""

import io
from datetime import datetime

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_jb"
SMOKE_VIEW_USER = "smoke_jb_view"
SMOKE_NONE_USER = "smoke_jb_none"

HEADERS = {"Authorization": ""}
VIEW_HEADERS = {"Authorization": ""}
RIQI = "2020-01-01"  # 远离真实数据的测试日期


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def _mk_user(username, is_superuser, with_perm=False):
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
        if with_perm:
            perm = db.query(Permission).filter(Permission.code == "jiaban:view").first()
            role = db.query(Role).filter(Role.code == "smoke_jb_view_role").first()
            if role is None:
                role = Role(name="smoke维抢修加班view角色", code="smoke_jb_view_role",
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


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.jiaban import Jiaban, JiabanAttachment, JiabanRenyuan
    from app.models.user import Role, User

    db = SessionLocal()
    try:
        for u in (SMOKE_USER, SMOKE_VIEW_USER, SMOKE_NONE_USER):
            user = db.query(User).filter(User.username == u).first()
            if user:
                db.delete(user)
        role = db.query(Role).filter(Role.code == "smoke_jb_view_role").first()
        if role:
            db.delete(role)
        # 测试人员的记录与人员本体(riqi 固定在 2020-01-01,不影响真实数据)
        db.query(Jiaban).filter(Jiaban.riqi == datetime(2020, 1, 1)).delete()
        db.query(JiabanRenyuan).filter(JiabanRenyuan.name.like("smoke测试%")).delete()
        db.query(JiabanAttachment).filter(
            JiabanAttachment.file_name.like("smoke_%")).delete()
        db.commit()
    finally:
        db.close()


def main():
    global HEADERS, VIEW_HEADERS
    _cleanup()
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False, with_perm=True)
    _mk_user(SMOKE_NONE_USER, False)
    HEADERS = _login(SMOKE_USER)
    VIEW_HEADERS = _login(SMOKE_VIEW_USER)
    NONE_HEADERS = _login(SMOKE_NONE_USER)

    api = "/api/jiaban"

    # ==================== 权限 ====================
    res = client.get(f"{api}/records", headers=NONE_HEADERS)
    check("无权限用户访问列表 403", res.status_code == 403)
    res = client.get(f"{api}/records", headers=VIEW_HEADERS)
    check("view 用户访问列表 200", res.status_code == 200)

    # ==================== 人员管理 ====================
    res = client.post(f"{api}/renyuan/add", headers=HEADERS,
                      json={"name": "smoke测试甲", "bmlb": "smoke测试组", "danjia": 123.45,
                            "gonghao": "JB001"})
    check("新增人员", res.json().get("success") is True, res.text[:200])
    res = client.post(f"{api}/renyuan/add", headers=HEADERS,
                      json={"name": "SMOKE测试甲", "bmlb": "smoke测试组", "danjia": 1})
    check("人员重名(不区分大小写)拒绝", res.status_code == 400, res.text[:200])
    res = client.post(f"{api}/renyuan/add", headers=HEADERS,
                      json={"name": "smoke测试乙", "bmlb": "smoke测试组", "danjia": 88})
    check("新增第二人员", res.json().get("success") is True)
    res = client.post(f"{api}/renyuan/add", headers=HEADERS,
                      json={"name": "smoke测试甲", "bmlb": "", "danjia": 0})
    check("部门类别为空拒绝", res.status_code == 400)

    res = client.get(f"{api}/renyuan", headers=HEADERS,
                     params={"search": "smoke测试", "page": 1, "rows": 10})
    body = res.json()
    check("人员模糊搜索 2 条", body["total"] == 2, str(body))
    person_a = next(r for r in body["rows"] if r["name"] == "smoke测试甲")
    person_b = next(r for r in body["rows"] if r["name"] == "smoke测试乙")

    res = client.get(f"{api}/renyuan-list", headers=HEADERS)
    check("人员下拉含测试人员", any(r["id"] == person_a["id"] for r in res.json()))
    res = client.get(f"{api}/bmlb-options", headers=HEADERS)
    check("部门类别选项含 smoke测试组", any(r["id"] == "smoke测试组" for r in res.json()))

    res = client.post(f"{api}/renyuan/update", headers=HEADERS,
                      json={"id": person_a["id"], "name": "smoke测试甲",
                            "bmlb": "smoke测试组2", "danjia": 200, "gonghao": "JB001"})
    check("编辑人员", res.json().get("success") is True, res.text[:200])
    res = client.post(f"{api}/renyuan/update", headers=HEADERS,
                      json={"id": person_b["id"], "name": "smoke测试甲",
                            "bmlb": "x", "danjia": 1})
    check("编辑撞名拒绝", res.status_code == 400)

    # ==================== 新增加班记录 ====================
    payload = {"nameids": f"{person_a['id']},{person_b['id']}", "gongdanNo": "900001",
               "riqi": RIQI, "dizhi": "smoke地址1", "neirong": "smoke内容",
               "kssj": "15:00", "jssj": "17:00", "shijian": 2, "beishu": 1.5,
               "zongshu": 3, "lei": False}
    res = client.post(f"{api}/add", headers=HEADERS, json=payload)
    body = res.json()
    check("新增两条记录", body.get("successCount") == 2, res.text[:300])

    res = client.post(f"{api}/add", headers=HEADERS,
                      json={**payload, "gongdanNo": "900002"})
    body = res.json()
    check("同人同时段冲突跳过", body.get("successCount") == 0
          and body.get("failCount") == 2, res.text[:300])
    check("冲突文案含工单号", "900001" in (body.get("errors") or [""])[0], str(body))

    res = client.post(f"{api}/add", headers=HEADERS,
                      json={**payload, "gongdanNo": "900003", "kssj": "23:00",
                            "jssj": "01:00", "shijian": 2, "zongshu": 3})
    check("跨天时段成功(结束<=开始+1天)", res.json().get("successCount") == 2, res.text[:300])

    res = client.post(f"{api}/add", headers=HEADERS,
                      json={**payload, "gongdanNo": "900004", "riqi": "bad-date"})
    check("日期非法 400", res.status_code == 400, res.text[:200])
    res = client.post(f"{api}/add", headers=HEADERS, json={**payload, "nameids": ""})
    check("人员为空 400", res.status_code == 400)

    # ==================== 列表 / 合计 / 筛选 ====================
    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "rows": 50})
    body = res.json()
    ids_created = [r["ID"] for r in body["rows"] if r["gongdanNo"].startswith("9000")]
    check("按日期查到 4 条新记录", len(ids_created) == 4, str(body["total"]))
    check("totalShijian 合计正确", abs(body["totalShijian"] - 8) < 0.001,
          str(body["totalShijian"]))
    row_first = next(r for r in body["rows"] if r["gongdanNo"] == "900003")
    check("跨天记录 jstime 为次日", row_first["jstime"].startswith("2020-01-02"),
          row_first["jstime"])

    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "mohu": "smoke地址"})
    check("模糊搜索命中", res.json()["total"] == 4)
    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "mohu": "smoke测试甲"})
    check("模糊搜索命中姓名", res.json()["total"] == 2)
    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "bmlb": "smoke测试组2"})
    check("部门类别筛选(多选串)", res.json()["total"] == 2, str(res.json()["total"]))
    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "leiType": "address"})
    check("leiType=address 0 条", res.json()["total"] == 0)
    res = client.post(f"{api}/update", headers=HEADERS,
                      json={"id": row_first["ID"], "nameid": person_a["id"],
                            "gongdanNo": "900003", "riqi": RIQI, "dizhi": "smoke地址1",
                            "neirong": "smoke内容改", "kssj": "18:00", "jssj": "20:00",
                            "shijian": 2, "beishu": 2, "zongshu": 4, "lei": True})
    check("编辑记录", res.json().get("success") is True, res.text[:200])
    res = client.get(f"{api}/records", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI, "leiType": "address"})
    check("leiType=address 1 条", res.json()["total"] == 1)

    res = client.post(f"{api}/add", headers=VIEW_HEADERS,
                      json={"nameids": str(person_a["id"]), "gongdanNo": "900010",
                            "riqi": RIQI, "dizhi": "v", "neirong": "v",
                            "kssj": "08:00", "jssj": "09:00", "shijian": 1,
                            "beishu": 1.5, "zongshu": 1.5, "lei": False})
    check("view 用户可新增(旧逻辑无角色细分)", res.json().get("successCount") == 1)

    res = client.post(f"{api}/delete", headers=VIEW_HEADERS,
                      json={"id": row_first["ID"]})
    body = res.json()
    check("他人记录不可删", body.get("success") is False
          and "只能删除自己录入的记录" in body.get("msg", ""), str(body))
    res = client.post(f"{api}/delete", headers=HEADERS,
                      json={"id": row_first["ID"]})
    check("删除本人记录", res.json().get("success") is True)

    # ==================== 工单号带出 ====================
    res = client.get(f"{api}/gongdan-info", headers=HEADERS,
                     params={"gongdanNo": "900001", "nameid": person_a["id"]})
    body = res.json()
    check("工单不存在时 success=False(外网未接)", body.get("success") is False, str(body)[:150])
    res = client.get(f"{api}/by-no", headers=HEADERS, params={"gongdanNo": "1"})
    check("详情抽屉外网未接 success=False", res.json().get("success") is False)
    res = client.get(f"{api}/images", headers=HEADERS, params={"flow_id": "1"})
    check("图片接口外网未接 images=[]", res.json().get("images") == [])

    # ==================== 4 个导出 ====================
    params = {"startDate": RIQI, "endDate": RIQI, "remark": "smoke备注"}
    res = client.get(f"{api}/export", headers=HEADERS, params=params)
    wb = load_workbook(io.BytesIO(res.content))
    check("按姓名导出 2 个 Sheet", set(wb.sheetnames) == {"smoke测试甲", "smoke测试乙"},
          str(wb.sheetnames))
    ws = wb["smoke测试甲"]
    check("按姓名导出标题", ws.cell(1, 1).value == "smoke测试组2加班审批表",
          str(ws.cell(1, 1).value))
    texts = [c.value for r in ws.iter_rows() for c in r if c.value is not None]
    check("按姓名导出含备注/审批行", "smoke备注" in texts and "审批:" in texts)

    res = client.get(f"{api}/export-by-address", headers=VIEW_HEADERS, params=params)
    wb = load_workbook(io.BytesIO(res.content))
    check("按地址导出按工单分 Sheet", "900010" in wb.sheetnames, str(wb.sheetnames))
    ws = wb["900010"]
    check("按地址导出标题", ws.cell(1, 1).value == "厦门营业所加班审批表")

    res = client.get(f"{api}/export-summary", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI})
    wb = load_workbook(io.BytesIO(res.content))
    ws = wb.active
    check("工资汇总标题", ws.cell(1, 1).value == "厦门市政水务集团有限公司 加班工资报销表")
    texts = [c.value for r in ws.iter_rows() for c in r if c.value is not None]
    check("工资汇总含人民币大写", any(str(t).endswith("元整") or "元" in str(t)
                                     for t in texts if isinstance(t, str)), str(texts[:8]))
    check("工资汇总制表人", "smoke_jb" in texts)

    res = client.get(f"{api}/export-for-overtime", headers=HEADERS,
                     params={"startDate": RIQI, "endDate": RIQI})
    wb = load_workbook(io.BytesIO(res.content))
    ws = wb.active
    check("加班申请模板表头 14 列", [ws.cell(2, c).value for c in (1, 2, 14)]
          == ["姓名", "工号", "结算类型"], str([ws.cell(2, c).value for c in range(1, 15)]))
    check("加班申请模板类别固定", ws.cell(3, 4).value == "维抢修加班")
    start_cells = {str(ws.cell(r, 6).value) for r in range(3, ws.max_row + 1)}
    check("加班申请模板开始时间 HHmm", {"0800", "1500", "2300"} <= start_cells,
          str(sorted(start_cells)))

    res = client.get(f"{api}/export", headers=HEADERS,
                     params={"startDate": "1999-01-01", "endDate": "1999-01-02"})
    check("无数据导出提示", res.json().get("msg") == "没有符合条件的数据可导出", res.text[:150])

    # ==================== 附件 ====================
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63fccf00c30f0003050100f9e2fe6e0000000049454e44ae426082")
    res = client.post(f"{api}/attachments/upload", headers=HEADERS,
                      params={"year": 2020, "month": 1},
                      files={"file": ("smoke_测试.png", io.BytesIO(png), "image/png")})
    check("上传附件", res.json().get("success") is True, res.text[:200])
    res = client.post(f"{api}/attachments/upload", headers=HEADERS,
                      params={"year": 2020, "month": 1},
                      files={"file": ("smoke_测试.txt", io.BytesIO(b"x"), "text/plain")})
    check("非白名单扩展名拒绝", res.status_code == 400, res.text[:150])

    res = client.get(f"{api}/attachments", headers=HEADERS, params={"rows": 600})
    body = res.json()
    att = next((r for r in body["rows"] if r["file_name"].startswith("smoke_")), None)
    check("附件列表可查", att is not None)
    check("附件 canDelete=本人", att and att["canDelete"] is True)
    check("迁移旧附件也在列表(508+1)", body["total"] >= 509, str(body["total"]))

    res = client.get(att["downloadUrl"])
    check("短令牌下载新附件 200", res.status_code == 200
          and res.headers["content-type"] == "application/octet-stream",
          str(res.status_code))
    res = client.get(f"{att['downloadUrl']}&inline=1")
    check("inline 下载返回 image/png(图片浏览窗)", res.status_code == 200
          and res.headers["content-type"] == "image/png"
          and "inline" in res.headers.get("content-disposition", ""),
          str(res.headers.get("content-type")))
    legacy = next((r for r in body["rows"] if not r["file_name"].startswith("smoke_")), None)
    if legacy:
        res = client.get(legacy["downloadUrl"])
        body2 = res.json()
        check("旧附件文件缺失兜底提示", body2.get("success") is False
              and "文件已被删除" in body2.get("msg", ""), str(body2)[:150])

    res = client.post(f"{api}/attachments/delete", headers=VIEW_HEADERS,
                      json={"id": att["id"]})
    body2 = res.json()
    check("他人附件不可删", body2.get("success") is False
          and "只能删除自己上传的附件" in body2.get("msg", ""), str(body2))
    res = client.post(f"{api}/attachments/delete", headers=HEADERS,
                      json={"id": att["id"]})
    check("删除本人附件", res.json().get("success") is True)

    # ==================== 人员删除 ====================
    res = client.post(f"{api}/renyuan/delete", headers=HEADERS,
                      json={"id": person_b["id"]})
    check("删除人员", res.json().get("success") is True)

    # ==================== 清理 ====================
    _cleanup()
    from app.db.session import SessionLocal
    from app.models.jiaban import Jiaban as _JB
    from app.models.workorder import GongdanCailiao
    db = SessionLocal()
    try:
        check("清理后测试记录为 0",
              db.query(_JB).filter(_JB.riqi == datetime(2020, 1, 1)).count() == 0)
        check("gongdancailiao 未被改动", db.query(GongdanCailiao).count() == 19689)
    finally:
        db.close()

    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
