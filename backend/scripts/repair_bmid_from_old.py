"""回填历史表里被置空的 bmid(部门表补齐后的收尾)。

背景:部门表没补齐前,旧 bmid 指向「特水/原水/各水厂」等 15 个在新库无同名的部门,
import_vehicles.py 等脚本按约定把这些记录的 bmid 置了 NULL。现在 departments 已有
全部 38 个旧部门,可以把它们补回来。

做法(刻意不 TRUNCATE 重导):
- 导入时保留了旧主键 id,因此按 id 一一对照旧库同表,取出原始 bmid;
- 只更新**当前 bmid IS NULL** 且旧库有值的行,已经正确的行一个都不碰,
  新系统里导入后新增/编辑过的数据也不会被覆盖;
- CASE id WHEN ... 一次性批量赋值,不做逐条 bmid 映射 UPDATE,避免旧/新 id 空间
  重叠导致链式污染(与 fix_waterfee_bmid.py 同样的防呆);
- 映射优先读 scripts/migration_reports/department_map.json(import_departments.py 产出),
  读不到则退回按部门名现算;旧 bmid 在部门表里已不存在的(旧 id=10)保持 NULL 并告警。

自动扫描新库所有带 bmid 列的表,旧库同表按名称(大小写不敏感)匹配,可 --tables 指定。
可重复执行(幂等:只补 NULL),支持 --dry-run。

用法(backend 目录下):
    python -m scripts.repair_bmid_from_old --dry-run
    python -m scripts.repair_bmid_from_old
    python -m scripts.repair_bmid_from_old --tables cl_che plusoil
"""

import argparse
import json
import os
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"
BATCH = 500


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )


def load_bmid_map(ncur):
    """旧 bb_bumen.id → 新 departments.id。优先用迁移时固化的映射,避免部门改名后错配。"""
    if MAP_FILE.exists():
        data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        m = {int(k): int(v) for k, v in data.get("bmid_map", {}).items()}
        print(f"映射来源: {MAP_FILE.name}({len(m)} 项)")
        return m
    print(f"⚠ 未找到 {MAP_FILE.name},退回按部门名现算(建议先跑 import_departments.py)")
    oc = old_conn()
    try:
        c = oc.cursor()
        c.execute("SELECT id, bm FROM bb_bumen")
        old = dict(c.fetchall())
    finally:
        oc.close()
    ncur.execute("SELECT id, name FROM departments")
    by_name = {name: i for i, name in ncur.fetchall()}
    return {oid: by_name[name] for oid, name in old.items() if name in by_name}


def old_table_names(ocur):
    """旧库表名(小写 → 原名),以及每张表是否有 id / bmid 列。"""
    ocur.execute(
        "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE COLUMN_NAME IN ('id', 'bmid')"
    )
    cols = {}
    for t, col in ocur.fetchall():
        cols.setdefault(t.lower(), {"name": t, "cols": set()})["cols"].add(col.lower())
    return cols


def new_bmid_tables(ncur, only=None):
    ncur.execute(
        "SELECT TABLE_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'bmid' ORDER BY TABLE_NAME"
    )
    tabs = [r[0] for r in ncur.fetchall()]
    return [t for t in tabs if not only or t.lower() in {x.lower() for x in only}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--tables", nargs="*", default=None, help="只处理指定表(默认全部)")
    args = parser.parse_args()

    oc = old_conn()
    nc = new_conn()
    try:
        ocur, ncur = oc.cursor(), nc.cursor()
        bmid_map = load_bmid_map(ncur)
        old_tables = old_table_names(ocur)
        tables = new_bmid_tables(ncur, args.tables)
        print(f"待检查 {len(tables)} 张带 bmid 的表: {tables}\n")

        grand_total = 0
        for table in tables:
            info = old_tables.get(table.lower())
            if not info or not {"id", "bmid"} <= info["cols"]:
                print(f"⏭ {table}: 旧库无同名表或缺 id/bmid 列,跳过")
                continue
            old_name = info["name"]
            ocur.execute(f"SELECT [id], [bmid] FROM [{old_name}] WHERE [bmid] IS NOT NULL")
            old_bmid = {int(r[0]): int(r[1]) for r in ocur.fetchall()}
            ncur.execute(f"SELECT id FROM `{table}` WHERE bmid IS NULL")
            null_ids = {int(r[0]) for r in ncur.fetchall()}
            if not null_ids or not old_bmid:
                why = "当前无 NULL 行" if not null_ids else "旧库该表 bmid 本就全为空"
                print(f"✓ {table}: 无需回填({why}; 当前 NULL {len(null_ids)} 行)")
                continue

            fix, unmapped = {}, set()
            for rid in null_ids & set(old_bmid):
                old_v = old_bmid[rid]
                new_v = bmid_map.get(old_v)
                if new_v is None:
                    unmapped.add(old_v)
                else:
                    fix[rid] = new_v
            print(f"  {table}: 当前 NULL {len(null_ids)} 行 → 可回填 {len(fix)} 行(旧表 {len(old_bmid)} 行有 bmid)")
            if unmapped:
                print(f"    ⚠ 旧 bmid {sorted(unmapped)} 在部门表中已不存在,按约定保持 NULL")
            if not fix:
                continue

            dist = {}
            for v in fix.values():
                dist[v] = dist.get(v, 0) + 1
            ncur.execute("SELECT id, name FROM departments")
            names = dict(ncur.fetchall())
            print("    回填分布: " + ", ".join(
                f"{v}({names.get(v, '?')}) {n}行" for v, n in sorted(dist.items())
            ))

            if args.dry_run:
                grand_total += len(fix)
                continue
            items = sorted(fix.items())
            for i in range(0, len(items), BATCH):
                chunk = items[i:i + BATCH]
                cases = " ".join("WHEN %s THEN %s" for _ in chunk)
                params = [x for rid, v in chunk for x in (rid, v)]
                params += [rid for rid, _ in chunk]
                ncur.execute(
                    f"UPDATE `{table}` SET bmid = CASE id {cases} END "
                    f"WHERE id IN ({', '.join(['%s'] * len(chunk))}) AND bmid IS NULL",
                    params,
                )
            grand_total += len(fix)
        if args.dry_run:
            print(f"\ndry-run:共可回填 {grand_total} 行,未写入")
        else:
            nc.commit()
            print(f"\n完成:共回填 {grand_total} 行(仅原 bmid IS NULL 的行)")
    finally:
        oc.close()
        nc.close()


if __name__ == "__main__":
    main()
