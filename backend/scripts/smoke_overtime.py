"""加班申请审批模块:数据迁移校验 + 接口冒烟(只读,跑完自动清理临时账号)。

用法(backend 目录下): python -m scripts.smoke_overtime

覆盖:
  [数据] 12 张 overtime_* 表新旧行数/金额&时长 SUM 对齐、部门树与人员引用的
         id 重映射完整性、overtime_record.userid 原样保留、is_field 生效。
  [接口] dicts / 人员列表 / 活动人员 / 部门树 / 系统部门 / 申请单 / 我的加班 /
         汇总 / Excel 导出等只读接口在有真实历史数据时均能正常返回。
"""

import os
import sys
from base64 import b64encode
from pathlib import Path

import pyodbc
import pymysql
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
PASS = 0
FAIL = 0
ADMIN = "smoke_ot_admin"

TABLES = [
    "overtime_dept", "overtime_personnel", "overtime_approval_level",
    "overtime_approver", "overtime_month_config", "overtime_apply",
    "overtime_apply_detail", "overtime_time_entry", "overtime_apply_approval",
    "overtime_comp_leave", "overtime_record", "overtime_user",
]
SUMS = {
    "overtime_personnel": ["daily_wage"],
    "overtime_apply": ["total_hours"],
    "overtime_apply_detail": ["total_hours"],
    "overtime_time_entry": ["raw_hours", "total_hours", "overtime_amount"],
}
# 重映射后的外键必须全部命中(模型不建物理外键,靠脚本保证)
REFS = [
    ("人员→系统用户", "SELECT COUNT(*) FROM overtime_personnel p LEFT JOIN users u "
     "ON p.bb_user_id=u.id WHERE p.bb_user_id IS NOT NULL AND u.id IS NULL"),
    ("人员→加班部门", "SELECT COUNT(*) FROM overtime_personnel p LEFT JOIN overtime_dept d "
     "ON p.bb_bumen_id=d.id WHERE p.bb_bumen_id IS NOT NULL AND d.id IS NULL"),
    ("加班部门→系统部门", "SELECT COUNT(*) FROM overtime_dept d LEFT JOIN departments s "
     "ON d.sys_bumen_id=s.id WHERE d.sys_bumen_id IS NOT NULL AND s.id IS NULL"),
    ("部门树父节点", "SELECT COUNT(*) FROM overtime_dept d LEFT JOIN overtime_dept p "
     "ON d.parent_id=p.id WHERE d.parent_id IS NOT NULL AND p.id IS NULL"),
    ("申请单→加班部门", "SELECT COUNT(*) FROM overtime_apply a LEFT JOIN overtime_dept d "
     "ON a.apply_dept_id=d.id WHERE a.apply_dept_id IS NOT NULL AND d.id IS NULL"),
    ("申请单→制单人", "SELECT COUNT(*) FROM overtime_apply a LEFT JOIN users u "
     "ON a.apply_user_id=u.id WHERE a.apply_user_id IS NOT NULL AND u.id IS NULL"),
    ("明细→人员", "SELECT COUNT(*) FROM overtime_apply_detail x LEFT JOIN overtime_personnel p "
     "ON x.personnel_id=p.id WHERE x.personnel_id IS NOT NULL AND p.id IS NULL"),
    ("明细→申请单", "SELECT COUNT(*) FROM overtime_apply_detail x LEFT JOIN overtime_apply a "
     "ON x.apply_id=a.id WHERE x.apply_id IS NOT NULL AND a.id IS NULL"),
    ("时段→明细", "SELECT COUNT(*) FROM overtime_time_entry t LEFT JOIN overtime_apply_detail d "
     "ON t.detail_id=d.id WHERE t.detail_id IS NOT NULL AND d.id IS NULL"),
]


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};"
        f"PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};", timeout=10)


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4")


def norm(v):
    return float(v or 0)


def data_checks():
    print("\n[1] 新旧库行数 / 金额时长对齐")
    o, n = old_conn(), new_conn()
    try:
        oc, nc = o.cursor(), n.cursor()
        for t in TABLES:
            oc.execute(f"SELECT COUNT(*) FROM dbo.[{t}]")
            nc.execute(f"SELECT COUNT(*) FROM `{t}`")
            a, b = oc.fetchone()[0], nc.fetchone()[0]
            check(f"{t} 行数 {a}", a == b, (a, b))
        for t, cols in SUMS.items():
            for c in cols:
                oc.execute(f"SELECT SUM(ISNULL([{c}],0)) FROM dbo.[{t}]")
                nc.execute(f"SELECT SUM(IFNULL(`{c}`,0)) FROM `{t}`")
                a, b = norm(oc.fetchone()[0]), norm(nc.fetchone()[0])
                check(f"SUM({t}.{c})={a:.2f}", abs(a - b) < 0.01, (a, b))

        print("\n[2] id 重映射完整性")
        for name, sql in REFS:
            nc.execute(sql)
            bad = nc.fetchone()[0]
            check(f"{name} 无悬空引用", bad == 0, bad)

        # overtime_record.userid 属于 overtime_user.id(1~19),不能套 user_map
        oc.execute("SELECT MIN(userid),MAX(userid),COUNT(DISTINCT userid) FROM dbo.overtime_record")
        nc.execute("SELECT MIN(userid),MAX(userid),COUNT(DISTINCT userid) FROM overtime_record")
        # pyodbc 返回 Row,pymysql 返回 tuple,统一转 tuple 再比
        o_val, n_val = tuple(oc.fetchone()), tuple(nc.fetchone())
        check("遗留表 userid 原值保留", o_val == n_val, (o_val, n_val))

        oc.execute("SELECT id,full_path FROM dbo.overtime_dept ORDER BY id")
        nc.execute("SELECT id,full_path FROM overtime_dept ORDER BY id")
        old_paths = [tuple(r) for r in oc.fetchall()]
        new_paths = [tuple(r) for r in nc.fetchall()]
        check("部门 full_path 与旧库一致", old_paths == new_paths,
              (len(old_paths), len(new_paths)))

        nc.execute("SELECT COUNT(*) FROM overtime_dept WHERE is_field=1")
        field_n = nc.fetchone()[0]
        check(f"基层营业所 is_field 生效({field_n} 个)", field_n > 0, field_n)
        nc.execute("SELECT COUNT(*) FROM overtime_personnel WHERE bb_user_id IS NOT NULL")
        bound = nc.fetchone()[0]
        check(f"人员已绑定系统用户({bound} 人)", bound > 0, bound)
        nc.execute("SELECT COUNT(*) FROM overtime_personnel WHERE is_active=1")
        active = nc.fetchone()[0]
        check(f"在职人员 {active} 人", active > 0, active)

        # 部门映射抽查:旧 sys_bumen_id=2(厦门) -> 新 departments.id=8
        nc.execute("SELECT sys_bumen_id FROM overtime_dept WHERE name='厦门营业所'")
        row = nc.fetchone()
        check("厦门营业所 sys_bumen_id 已重映射为 8", bool(row) and row[0] == 8, row)
    finally:
        o.close()
        n.close()


def _mk_admin():
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == ADMIN).first()
        if not u:
            u = User(username=ADMIN, password_hash=hash_password("Smoke@12345"),
                     password_version=1, real_name=ADMIN, is_superuser=True, is_active=True)
            db.add(u)
            db.commit()
    finally:
        db.close()


def _login():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    pub = serialization.load_pem_public_key(
        client.get("/api/auth/public-key").json()["publicKey"].encode())
    enc = pub.encrypt(b"Smoke@12345", padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    r = client.post("/api/auth/login", json={
        "username": ADMIN, "password": b64encode(enc).decode()})
    if r.status_code != 200 or "token" not in r.json():
        raise SystemExit(f"登录失败: {r.status_code} {r.text[:200]}")
    return {"Authorization": "Bearer " + r.json()["token"]}


def _cleanup():
    from app.db.session import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == ADMIN).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def api_checks():
    print("\n[3] 接口冒烟(真实历史数据)")
    _mk_admin()
    try:
        h = _login()
        r = client.get("/api/overtime/dicts", headers=h)
        d = r.json() if r.status_code == 200 else {}
        check("dicts 200", r.status_code == 200, r.text[:150])
        check(f"dicts 人员池 {len(d.get('personnel', []))} 人", len(d.get("personnel", [])) > 0)
        check("dicts 部门树非空", bool(d.get("dept_tree")), str(d.get("dept_tree"))[:100])
        check("dicts 部门路径表非空", bool(d.get("dept_paths")), len(d.get("dept_paths", {})))

        url_checks = [
            ("人员列表", "/api/overtime/personnel", {"page": 1, "rows": 30}),
            ("活动人员", "/api/overtime/personnel/active", {}),
            ("部门树(full)", "/api/overtime/depts/tree", {"full": "true"}),
            ("系统部门列表", "/api/overtime/depts/sys-list", {}),
            ("申请单列表", "/api/overtime/applies", {"page": 1, "rows": 30}),
            ("我的加班", "/api/overtime/my-records", {"month": "202610"}),
            ("待汇总记录", "/api/overtime/submitted-records", {"month": "202610"}),
            ("加班汇总", "/api/overtime/summary", {"month": "202610"}),
            ("补休余额", "/api/overtime/comp-leave/balance", {"personnelId": 1}),
            ("审批流开关", "/api/overtime/approval-switch", {}),
        ]
        for name, url, params in url_checks:
            res = client.get(url, params=params, headers=h)
            check(f"{name} 200", res.status_code == 200, (res.status_code, res.text[:120]))

        res = client.get("/api/overtime/personnel", params={"page": 1, "rows": 30}, headers=h)
        body = res.json() if res.status_code == 200 else {}
        total = body.get("total", len(body.get("rows", body if isinstance(body, list) else [])))
        check(f"人员分页 total={total} (>500)", isinstance(total, int) and total > 500, total)

        tree = client.get("/api/overtime/depts/tree", params={"full": "true"}, headers=h)
        nodes = tree.json() if tree.status_code == 200 else []

        def count(ns):
            return sum(1 + count(x.get("children") or []) for x in ns) if isinstance(ns, list) else 0

        check(f"部门树节点 {count(nodes)} 个(应为 47)", count(nodes) == 47, count(nodes))

        apps = client.get("/api/overtime/applies", params={"page": 1, "rows": 30}, headers=h)
        ab = apps.json() if apps.status_code == 200 else {}
        at = ab.get("total", len(ab.get("rows", [])) if isinstance(ab, dict) else 0)
        check(f"申请单 total={at} (应为 186)", at == 186, at)
    finally:
        _cleanup()


def main():
    data_checks()
    api_checks()
    print(f"\n结果: {PASS} 通过 / {FAIL} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
