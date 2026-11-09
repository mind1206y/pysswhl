"""旧库 db_plan.dbo.overtime_* -> 新库 sswhl_new 迁移脚本(可重复执行,支持 --dry-run)。

用法(在 backend 目录下):
    python -m scripts.import_overtime            # 正式迁移
    python -m scripts.import_overtime --dry-run  # 只统计、不写库

三套 id 空间必须分清(见 docs/数据迁移约定.md 与本模块模型 docstring):

1. 旧 bb_bumen.id -> 新 departments.id
   用 migration_reports/department_map.json 的 bmid_map 一次性重映射。
   涉及列: overtime_dept.sys_bumen_id、overtime_approval_level.mapped_bumen_id、
           overtime_approver.scope_bumen_id。
   ⚠ 禁止逐条 UPDATE 循环:旧/新 id 数字会撞车,链式覆盖会污染数据。
      本脚本在**内存里**按映射替换后一次性 INSERT,从根源避免该问题。

2. overtime_dept.id(加班部门自建镜像树)
   overtime_personnel.bb_bumen_id / overtime_apply.apply_dept_id /
   overtime_dept.parent_id / overtime_personnel.parent_id 存的是这套 id,
   整棵树连同 id 原样导入即可自洽,**不要**套 bmid_map。

3. 旧 bb_user.id -> 新 users.id
   按 username 精确匹配生成 user_map.json 后重映射。
   涉及列见 USER_COLUMNS。匹配不到的置 NULL 并告警。

另:加班部门是否"基层营业所"(旧 bb_bumen._parentId==1)决定审批路由 field/hq,
旧库没有持久化该标记,本脚本按旧 bb_bumen 计算后写入 overtime_dept.is_field。

迁移前会把新库 12 张 overtime_* 表现有数据备份到
migration_reports/overtime_backup_<时间戳>.json。
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pymysql
import pyodbc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"
USER_MAP_FILE = REPORT_DIR / "user_map.json"

# 导入顺序:父表在前(模型不建物理外键,但保持顺序便于排查)
TABLE_ORDER = [
    "overtime_dept",
    "overtime_personnel",
    "overtime_approval_level",
    "overtime_approver",
    "overtime_month_config",
    "overtime_apply",
    "overtime_apply_detail",
    "overtime_time_entry",
    "overtime_apply_approval",
    "overtime_comp_leave",
    "overtime_record",
    "overtime_user",
]

TABLE_FIELDS = {
    "overtime_dept": ["id", "name", "parent_id", "sys_bumen_id", "full_path", "level",
                      "sort_order", "is_active", "create_time"],
    "overtime_personnel": ["id", "name", "employee_no", "bb_user_id", "bb_bumen_id",
                           "parent_id", "daily_wage", "is_active", "create_time"],
    "overtime_approval_level": ["id", "level_name", "level_order", "parent_id", "dept_offset",
                                "mapped_bumen_id", "approval_mode", "route_type", "is_active",
                                "create_time"],
    "overtime_approver": ["id", "bb_user_id", "approval_level_id", "scope_bumen_id",
                          "work_type", "is_active", "create_time"],
    "overtime_month_config": ["id", "config_type", "start_day", "end_day", "description", "is_active"],
    "overtime_apply": ["id", "apply_no", "record_type", "apply_month", "work_type",
                       "apply_user_id", "apply_dept_id", "apply_date", "total_hours",
                       "status", "remark", "create_time", "update_time", "verify_time",
                       "verify_user_id", "settle_type"],
    "overtime_apply_detail": ["id", "apply_id", "personnel_id", "accounting_month",
                              "total_hours", "sort_order", "work_type", "apply_month",
                              "apply_user_id", "create_time", "status", "settle_type"],
    "overtime_time_entry": ["id", "detail_id", "work_type", "work_date", "start_time",
                            "end_time", "raw_hours", "multiplier", "total_hours", "reason",
                            "daily_wage", "overtime_amount", "work_order_no", "address",
                            "accounting_month", "sort_order", "is_full_day", "shift_type"],
    "overtime_apply_approval": ["id", "apply_id", "step_order", "approval_level_id",
                                "approver_id", "status", "comment", "approve_time", "create_time"],
    "overtime_comp_leave": ["id", "personnel_id", "leave_date", "start_time", "end_time",
                            "hours", "leave_type", "reason", "create_user_id", "create_time"],
    "overtime_record": ["id", "userid", "username", "work_date", "work_type", "remark",
                        "create_time", "update_time", "creater"],
    "overtime_user": ["id", "username"],
}

# 旧 bb_bumen.id -> 新 departments.id 的列(走 department_map.json)
DEPT_COLUMNS = {
    "overtime_dept": ["sys_bumen_id"],
    "overtime_approval_level": ["mapped_bumen_id"],
    "overtime_approver": ["scope_bumen_id"],
}
# 旧 bb_user.id -> 新 users.id 的列(走 user_map.json)
USER_COLUMNS = {
    "overtime_personnel": ["bb_user_id"],
    "overtime_apply": ["apply_user_id", "verify_user_id"],
    "overtime_apply_detail": ["apply_user_id"],
    "overtime_approver": ["bb_user_id"],
    "overtime_apply_approval": ["approver_id"],
    "overtime_comp_leave": ["create_user_id"],
    "overtime_record": ["userid"],
}
# 目标列为 NOT NULL 的列:匹配不到时必须给安全值,不能写 NULL 触发 1048 错误。
# overtime_record 是旧系统遗留表,userid 无对应账号时置 0(真实姓名仍在 username 文本列)。
NON_NULL_FALLBACK = {("overtime_record", "userid"): 0}


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};"
        f"PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )


def load_bmid_map():
    if not MAP_FILE.exists():
        print(f"⚠ 未找到 {MAP_FILE.name},部门列将按名称现算(建议先跑 import_departments.py)")
        return {}
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    m = {int(k): (int(v) if v is not None else None)
         for k, v in data.get("bmid_map", {}).items()}
    print(f"部门映射: {MAP_FILE.name}({len(m)} 项)")
    return m


def _key(v):
    return str(v or "").strip().lower()


def build_user_map(ocur, ncur):
    """旧 bb_user.id -> 新 users.id。

    按 docs/数据迁移约定.md「用户与密码」,新库 users 不从旧库导入、管理员重建账号,
    所以这里只做**多通道尽力匹配**(不做任何账号创建):
      ① 旧 username  == 新 username   (英文名/手机号登录名)
      ② 旧 tel       == 新 username   (旧库实名+手机号登录,新库用手机号做账号)
      ③ 旧 username/unames == 新 real_name
    匹配不到的详细名单写进 user_map.json,供管理员建号后回填。
    """
    try:
        ocur.execute("SELECT [id], [username], [unames], [tel] FROM [bb_user]")
        old = [(int(r[0]), _key(r[1]), _key(r[2]), _key(r[3])) for r in ocur.fetchall()]
    except pyodbc.Error as e:
        print(f"⚠ 读取 bb_user 失败({e}),用户列将置空")
        return {}
    ncur.execute("SELECT id, username, real_name FROM users")
    by_username, by_realname = {}, {}
    for uid, uname, real in ncur.fetchall():
        if _key(uname):
            by_username[_key(uname)] = int(uid)
        if _key(real):
            by_realname.setdefault(_key(real), int(uid))
    out, missing = {}, []
    for oid, uname, names, tel in old:
        nid = (by_username.get(uname) or by_username.get(tel)
               or by_realname.get(names) or by_realname.get(uname))
        if nid:
            out[oid] = nid
        else:
            missing.append({"id": oid, "username": uname, "unames": names, "tel": tel})
    if missing:
        labels = [m["username"] or m["unames"] or str(m["id"]) for m in missing]
        print(f"  ⚠ 旧系统 {len(missing)} 个用户在新库无对应账号: "
              f"{', '.join(labels[:10])}{' ...' if len(labels) > 10 else ''}")
    USER_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_MAP_FILE.write_text(
        json.dumps({"source": "db_plan.dbo.bb_user", "target": f"{settings.DB_NAME}.users",
                    "match_rules": ["username==username", "tel==username",
                                    "unames/username==real_name"],
                    "user_map": {str(k): v for k, v in out.items()},
                    "missing": missing}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"用户映射: 成功 {len(out)} 项 → {USER_MAP_FILE.name}")
    return out


def source_columns(ocur, table):
    ocur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", table)
    return {r[0].lower() for r in ocur.fetchall()}


def field_parents(ocur):
    """旧 bb_bumen 中 _parentId==1 的是基层营业所(审批路由 field)。"""
    try:
        ocur.execute("SELECT [id], [_parentId] FROM [bb_bumen]")
        return {int(r[0]): (r[1] == 1) for r in ocur.fetchall()}
    except pyodbc.Error:
        print("  ⚠ 读取 bb_bumen._parentId 失败,is_field 全部置 0")
        return {}


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v.strftime("%Y-%m-%d")
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def backup_new(ncur, stamp):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for table in TABLE_ORDER:
        try:
            ncur.execute(f"SELECT * FROM `{table}`")
            cols = [d[0] for d in ncur.description]
            out[table] = [dict(zip(cols, [jsonable(v) for v in row])) for row in ncur.fetchall()]
        except pymysql.err.ProgrammingError:
            out[table] = []  # 表尚未建
    path = REPORT_DIR / f"overtime_backup_{stamp}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已备份新库现有加班数据 → {path.name}")


def fetch_table(ocur, table, cols):
    names = ", ".join(f"[{c}]" for c in cols)
    ocur.execute(f"SELECT {names} FROM [{table}] ORDER BY [id]")
    return [tuple(r) for r in ocur.fetchall()]


def remap(rows, cols, table, bmid_map, user_map, field_flags):
    """一次性内存重映射(不做逐条 UPDATE,避免旧/新 id 重叠污染)。"""
    dept_idx = {c: cols.index(c) for c in DEPT_COLUMNS.get(table, []) if c in cols}
    user_idx = {c: cols.index(c) for c in USER_COLUMNS.get(table, []) if c in cols}
    is_field_idx = cols.index("is_field") if "is_field" in cols else None
    sys_idx = cols.index("sys_bumen_id") if "sys_bumen_id" in cols else None
    out, warnings = [], {"dept": set(), "user": set()}
    for r in rows:
        lst = list(r)
        old_sys = lst[sys_idx] if sys_idx is not None and table == "overtime_dept" else None
        for c, i in dept_idx.items():
            v = lst[i]
            if v is not None:
                nv = bmid_map.get(int(v))
                if nv is None:
                    warnings["dept"].add(int(v))
                    nv = NON_NULL_FALLBACK.get((table, c))
                lst[i] = nv
        for c, i in user_idx.items():
            v = lst[i]
            if v is not None:
                nv = user_map.get(int(v))
                if nv is None:
                    warnings["user"].add(int(v))
                    nv = NON_NULL_FALLBACK.get((table, c))
                lst[i] = nv
        if is_field_idx is not None:
            lst[is_field_idx] = 1 if (old_sys is not None and field_flags.get(int(old_sys))) else 0
        out.append(tuple(lst))
    if warnings["dept"]:
        print(f"  ⚠ {table}: 旧部门 id {sorted(warnings['dept'])} 无映射,已置 NULL")
    if warnings["user"]:
        print(f"  ⚠ {table}: 旧用户 id {sorted(warnings['user'])} 无映射,已置 NULL")
    return out, warnings


def write_table(ncur, table, cols, rows):
    if not rows:
        print(f"  {table}: 0 条(跳过)")
        return
    placeholders = ", ".join(["%s"] * len(cols))
    sql = (f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in cols)
           + f") VALUES ({placeholders})")
    batch = []
    for r in rows:
        # pymysql 原生支持 datetime/date/Decimal/None,不要转字符串以免精度/格式损失
        batch.append(tuple(r))
        if len(batch) >= 1000:
            ncur.executemany(sql, batch)
            batch = []
    if batch:
        ncur.executemany(sql, batch)
    max_id = max((r[0] for r in rows if isinstance(r[0], int)), default=0)
    if max_id:
        ncur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")


def main():
    parser = argparse.ArgumentParser(description="迁移旧库加班申请审批模块数据")
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bmid_map = load_bmid_map()

    o = old_conn()
    n = new_conn()
    try:
        ocur, ncur = o.cursor(), n.cursor()
        user_map = build_user_map(ocur, ncur)
        field_flags = field_parents(ocur)
        report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "source": f"{os.environ.get('OLD_DB_NAME', 'db_plan')}.dbo.overtime_*",
                  "target": f"{settings.DB_NAME}.overtime_*",
                  "dry_run": args.dry_run, "tables": {}, "warnings": {}}
        if not args.dry_run:
            backup_new(ncur, stamp)

        for table in TABLE_ORDER:
            actual = source_columns(ocur, table)
            if not actual:
                print(f"  ⚠ {table}: 旧库不存在该表,跳过")
                report["tables"][table] = {"exists": False, "rows": 0}
                continue
            cols = [c for c in TABLE_FIELDS[table] if c in actual]
            if table == "overtime_dept":
                cols.append("is_field")  # 新系统新增列,按旧 bb_bumen 计算
            rows = fetch_table(ocur, table, TABLE_FIELDS[table] and [c for c in TABLE_FIELDS[table] if c in actual])
            # 若目标需要 is_field,在 remap 时追加
            if table == "overtime_dept":
                rows = [r + (0,) for r in rows]
            rows, warn = remap(rows, cols, table, bmid_map, user_map, field_flags)
            missing = sorted(set(TABLE_FIELDS[table]) - actual)
            report["tables"][table] = {"exists": True, "rows": len(rows),
                                       "columns": cols, "missing_source_columns": missing}
            report["warnings"][table] = {k: sorted(v) for k, v in warn.items()}
            print(f"  {table}: 旧库 {len(rows)} 条"
                  + (f",源表缺列 {missing}(取新库默认值)" if missing else ""))
            if args.dry_run:
                continue
            ncur.execute(f"TRUNCATE TABLE `{table}`")
            write_table(ncur, table, cols, rows)

        if args.dry_run:
            print("\n[dry-run] 未写入任何数据")
        else:
            n.commit()
            print("\n✓ 迁移完成,已提交")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"overtime_import_report_{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告 → {path.name}")
    except Exception:
        n.rollback()
        raise
    finally:
        o.close()
        n.close()


if __name__ == "__main__":
    main()
