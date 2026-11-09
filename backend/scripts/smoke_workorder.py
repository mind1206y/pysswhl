"""工单领料管理模块全链路 smoke 测试(TestClient,跑完自动清理)。

用法:backend 目录下  python -m scripts.smoke_workorder
覆盖:字典/库存/列表(含各筛选)/工单号回显/明细/导出3Sheet/外部详情降级/
     提交-编辑-库存增减/附件上传下载删除/删除回滚/仅 view 权限越权拦截。
"""

import io
import time

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app

client = TestClient(app)

PASS = 0
FAIL = 0
SMOKE_USER = "smoke_wo"
SMOKE_VIEW_USER = "smoke_wo_view"
SMOKE_NO = ""


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
        if db.query(User).filter(User.username == username).first() is not None:
            return
        u = User(username=username, password_hash=hash_password("Smoke@12345"),
                 password_version=1, real_name=username,
                 is_superuser=is_superuser, is_active=True)
        if not is_superuser:
            from app.models.user import Permission

            role = db.query(Role).filter(Role.code == "smoke_wo_view_role").first()
            if role is None:
                perm = db.query(Permission).filter(Permission.code == "workorder:view").first()
                role = Role(name="smoke工单view角色", code="smoke_wo_view_role",
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
    return res.json()["token"]


def _stock_num(mid):
    from app.db.session import SessionLocal
    from app.models.material import MaterialLibrary

    db = SessionLocal()
    try:
        m = db.get(MaterialLibrary, mid)
        return float(m.num or 0) if m else None
    finally:
        db.close()


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.material import MaterialLibrary, MaterialRecord
    from app.models.user import Role, User
    from app.models.workorder import WorkOrderAttachment
    from app.models.material import WorkOrder

    db = SessionLocal()
    try:
        if SMOKE_NO:
            orders = db.query(WorkOrder).filter(WorkOrder.work_order_no == SMOKE_NO).all()
            for o in orders:
                for rec in db.query(MaterialRecord).filter(
                    MaterialRecord.work_order_id == o.id).all():
                    mat = db.get(MaterialLibrary, rec.material_id)
                    if mat is not None:
                        mat.num = round(float(mat.num or 0) + float(rec.quantity or 0), 1)
                    db.delete(rec)
                for att in db.query(WorkOrderAttachment).filter(
                    WorkOrderAttachment.workorderid == o.id).all():
                    db.delete(att)
                db.delete(o)
            db.commit()
        for name in (SMOKE_USER, SMOKE_VIEW_USER):
            u = db.query(User).filter(User.username == name).first()
            if u is not None:
                db.delete(u)
                db.commit()
        role = db.query(Role).filter(Role.code == "smoke_wo_view_role").first()
        if role is not None:
            db.delete(role)
            db.commit()
        # 兜底:历史 smoke 残留附件物理文件清理由接口删除时完成,这里只清孤儿记录
    finally:
        db.close()


def main():
    global SMOKE_NO
    _mk_user(SMOKE_USER, True)
    _mk_user(SMOKE_VIEW_USER, False)
    try:
        h = {"Authorization": f"Bearer {_login(SMOKE_USER)}"}
        hv = {"Authorization": f"Bearer {_login(SMOKE_VIEW_USER)}"}
        SMOKE_NO = f"SMOKE{int(time.time())}"

        # 1. 字典
        r = client.get("/api/workorder/dicts", headers=h)
        check("GET dicts 200", r.status_code == 200)
        d = r.json()
        check("dicts 领料类别 11 项", len(d["lingliaotypes"]) == 11)
        check("dicts 班组 14 项", len(d["banzu"]) == 14, str(len(d["banzu"])))
        check("dicts 超管 manage=true", d["perms"]["manage"] is True)
        rv = client.get("/api/workorder/dicts", headers=hv)
        check("仅 view 用户 manage=false", rv.json()["perms"]["manage"] is False)

        # 2. 选料库存
        r = client.get("/api/workorder/stocks", headers=h, params={"page": 1, "size": 5})
        check("GET stocks 200", r.status_code == 200)
        check("stocks total 695", r.json()["total"] == 695, str(r.json().get("total")))
        stocks = r.json()["rows"]
        check("stocks 按领用次数排序有 num 字段", bool(stocks) and "num" in stocks[0])
        r = client.get("/api/workorder/stocks", headers=h,
                       params={"page": 1, "size": 5, "mohu": "黄铜闸阀"})
        check("stocks 模糊搜索命中", r.json()["total"] >= 1)

        # 3. 工单列表 + 筛选
        r = client.get("/api/workorder/orders", headers=h, params={"page": 1, "size": 5})
        check("GET orders 200", r.status_code == 200)
        check("orders total 10976", r.json()["total"] == 10976, str(r.json().get("total")))
        first = r.json()["rows"][0]
        check("列表含 IsUsed/AttachmentCount/CreatedTime",
              all(k in first for k in ("IsUsed", "AttachmentCount", "CreatedTime")))
        r = client.get("/api/workorder/orders", headers=h,
                       params={"page": 1, "size": 5, "unusedOnly": True})
        check("只看未领用 total 1872", r.json()["total"] == 1872, str(r.json().get("total")))
        check("只看未领用行均 IsUsed=false",
              all(not x["IsUsed"] for x in r.json()["rows"]))
        r = client.get("/api/workorder/orders", headers=h,
                       params={"page": 1, "size": 5, "lingliaotype": "__EMPTY__"})
        check("未分类筛选 total 10976", r.json()["total"] == 10976)
        r = client.get("/api/workorder/orders", headers=h,
                       params={"page": 1, "size": 5, "startDate": "2026-10-16",
                               "endDate": "2026-10-16"})
        check("日期筛选(含结束当天)", 0 < r.json()["total"] < 10976, str(r.json().get("total")))
        r = client.get("/api/workorder/orders", headers=h,
                       params={"page": 1, "size": 5, "searchText": "438408"})
        check("关键字按工单号搜索", r.json()["total"] >= 1)

        # 4. 明细 / 工单号回显
        r = client.get(f"/api/workorder/orders/{first['Id']}/details", headers=h)
        check("GET 明细 200 且为数组", r.status_code == 200 and isinstance(r.json(), list))
        r = client.get("/api/workorder/orders/by-no2", headers=h,
                       params={"workOrderNo": first["WorkOrderNo"]})
        check("by-no2 回显明细", r.status_code == 200 and len(r.json()["details"]) >= 1)
        check("by-no2 带主表字段", "banzu" in r.json()["details"][0])
        r = client.get("/api/workorder/external/by-no", headers=h,
                       params={"gongdanNo": "abc"})
        check("外部详情非数字工单号安全降级", r.json()["success"] is False)
        # 工单号点击抽屉:与 jcxt/gongdan-info 同结构,另含现场图片短令牌
        r = client.get("/api/workorder/external/info", headers=h,
                       params={"gongdanNo": "abc"})
        check("external/info 非数字工单号安全降级",
              r.status_code == 200 and r.json()["success"] is False
              and "message" in r.json())
        r = client.get("/api/workorder/external/info", headers=h, params={"gongdanNo": ""})
        check("external/info 空工单号返回 message", r.json()["message"] == "工单号不能为空")
        r = client.get("/api/workorder/external/images", headers=h,
                       params={"flow_id": "123456", "gongdanNo": "123456"})
        check("external/images 不可达时返回空图片",
              r.status_code == 200 and r.json()["images"] == [])
        r = client.get("/api/workorder/external/image", params={"token": "bad"})
        check("external/image 非法令牌 401", r.status_code == 401)
        r = client.get("/api/jcxt/gongdan-info", headers=h,
                       params={"gongdanhao": "abc"})
        check("jcxt/gongdan-info 重构后仍正常", r.status_code == 200 and r.json()["success"] is False)

        # 5. 导出 3 Sheet
        r = client.get("/api/workorder/export", headers=h,
                       params={"startDate": "2026-10-01", "endDate": "2026-10-31"})
        check("GET export 200", r.status_code == 200)
        wb = load_workbook(io.BytesIO(r.content))
        check("导出 3 个 Sheet", wb.sheetnames == ["材料出库统计", "班组领料统计", "未领用工单"],
              str(wb.sheetnames))
        check("Sheet1 有标题+表头+数据", wb.worksheets[0].max_row > 2)

        # 6. 提交 / 编辑 / 库存事务
        mat = stocks[0]
        before = _stock_num(mat["Id"])
        body = {
            "workOrderNo": SMOKE_NO, "banzu": "郭建德",
            "lingliaotype": "管网维抢修", "beizhu": "smoke",
            "items": [{"Id": mat["Id"], "MaterialName": mat["MaterialName"],
                       "Spec": mat["Spec"], "Qty": 2.0, "Unit": mat["Unit"]}],
        }
        r = client.post("/api/workorder/orders/submit", headers=hv, json=body)
        check("仅 view 用户可提交领料", r.status_code == 200 and r.json().get("success"), r.text[:200])
        oid = r.json().get("id")
        check("提交后库存 -2", abs(_stock_num(mat["Id"]) - (before - 2)) < 0.01,
              f"{before} -> {_stock_num(mat['Id'])}")
        r = client.get("/api/workorder/orders/by-no2", headers=h,
                       params={"workOrderNo": SMOKE_NO})
        check("提交后按工单号查到 1 条明细", len(r.json()["details"]) == 1)

        body2 = {**body, "orderId": oid, "items": [
            {"Id": mat["Id"], "MaterialName": mat["MaterialName"],
             "Spec": mat["Spec"], "Qty": 3.0, "Unit": mat["Unit"]}]}
        r = client.post("/api/workorder/orders/submit", headers=h, json=body2)
        check("编辑领料单 200", r.status_code == 200 and r.json().get("success"))
        check("编辑后库存回滚再扣 -3", abs(_stock_num(mat["Id"]) - (before - 3)) < 0.01,
              f"{before} -> {_stock_num(mat['Id'])}")
        r = client.get(f"/api/workorder/orders/{oid}/details", headers=h)
        check("编辑后明细仍 1 条数量 3",
              len(r.json()) == 1 and r.json()[0]["Quantity"] == 3.0, str(r.json())[:200])

        # 7. 附件
        r = client.post("/api/workorder/attachments", headers=h,
                        params={"workorderid": oid},
                        files={"file": ("smoke.png", b"\x89PNG\r\n\x1a\nhello", "image/png")})
        check("上传附件 200", r.status_code == 200 and r.json().get("success"), r.text[:200])
        r = client.get("/api/workorder/attachments", headers=h,
                       params={"workorderid": oid})
        check("附件列表 1 条", r.status_code == 200 and r.json()["total"] == 1)
        att = r.json()["rows"][0]
        check("附件可删 + 有短令牌下载链接",
              att["canDelete"] and att["downloadUrl"].startswith("/api/workorder/attachments/download?token="))
        r = client.get(att["downloadUrl"])
        check("短令牌下载 200", r.status_code == 200 and r.content.startswith(b"\x89PNG"))
        r = client.delete(f"/api/workorder/attachments/{att['id']}", headers=h)
        check("删除附件 200", r.status_code == 200)

        # 8. 删除权限与库存回滚
        r = client.delete(f"/api/workorder/orders/{oid}", headers=hv)
        check("仅 view 用户删除领料单 403", r.status_code == 403)
        r = client.delete(f"/api/workorder/orders/{oid}", headers=h)
        check("超管删除领料单 200", r.status_code == 200, r.text[:200])
        check("删除后库存恢复", abs(_stock_num(mat["Id"]) - before) < 0.01,
              f"{before} -> {_stock_num(mat['Id'])}")
        r = client.get("/api/workorder/orders/by-no2", headers=h,
                       params={"workOrderNo": SMOKE_NO})
        check("删除后明细清空", len(r.json()["details"]) == 0)
    finally:
        _cleanup()
    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    if FAIL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
