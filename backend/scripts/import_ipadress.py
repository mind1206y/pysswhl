"""IP 地址管理历史数据导入:旧库 db_plan.dbo.* -> 新库同名表。

- ipadress(2530 条):保留旧主键 id,导入后调整自增起点
- ip_net_creator(旧库当前 0 条):网段创建人元信息
- bmid 按 migration_reports/department_map.json 重映射到新 departments.id
  (旧 1/2/8 -> 新 7/8/12);映射不到时置 NULL 并告警
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_ipadress --dry-run
    python -m scripts.import_ipadress
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"

IP_FIELDS = [
    "id", "netname", "bmid", "sqren", "net", "numb", "didian", "syren",
    "yongtu", "zt", "sqdate", "netdate",
]
CREATOR_FIELDS = ["netname", "creator", "createtime"]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def load_bmid_map() -> dict:
    if not MAP_FILE.exists():
        raise SystemExit(
            f"缺少部门映射文件 {MAP_FILE},请先运行 python -m scripts.import_departments"
        )
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in data.get("bmid_map", {}).items()}


def fetch_all(cur, table, fields):
    cur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{table}]")
    rows = [tuple(r) for r in cur.fetchall()]
    print(f"  {table}: 旧库 {len(rows)} 条")
    return rows


def write_table(cur, table, fields, rows, auto_increment=False):
    cur.execute(f"TRUNCATE TABLE `{table}`")
    placeholders = ", ".join(["%s"] * len(fields))
    sql = (f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in fields)
           + f") VALUES ({placeholders})")
    batch = []
    for r in rows:
        batch.append(tuple(r))
        if len(batch) >= 1000:
            cur.executemany(sql, batch)
            batch = []
    if batch:
        cur.executemany(sql, batch)
    if auto_increment:
        max_id = max((r[0] for r in rows), default=0)
        if max_id:
            cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
        print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")
    else:
        print(f"  {table}: 写入 {len(rows)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    bmid_map = load_bmid_map()
    missing = Counter()
    ips = []
    creators = []

    oc = old_conn()
    try:
        ocur = oc.cursor()
        raw_ips = fetch_all(ocur, "ipadress", IP_FIELDS)
        creators = fetch_all(ocur, "ip_net_creator", CREATOR_FIELDS)
    finally:
        oc.close()

    for row in raw_ips:
        rec = list(row)
        old_bmid = rec[2]
        if old_bmid is None:
            rec[2] = None
        else:
            new_bmid = bmid_map.get(int(old_bmid))
            if new_bmid is None:
                missing[old_bmid] += 1
            rec[2] = new_bmid
        ips.append(tuple(rec))

    print(f"  bmid 映射: {len(ips) - sum(missing.values())}/{len(ips)} 有映射")
    if missing:
        print(f"  未映射旧 bmid: {dict(missing)} (对应记录 bmid 置 NULL)")

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        ncur = new.cursor()
        try:
            write_table(ncur, "ipadress", IP_FIELDS, ips, auto_increment=True)
            write_table(ncur, "ip_net_creator", CREATOR_FIELDS, creators)
        except pymysql.err.ProgrammingError as exc:
            raise SystemExit(
                "目标表不存在,请先运行 python -m scripts.init_db 建表。"
                f"\n原始错误: {exc}"
            )
        new.commit()
    finally:
        new.close()


if __name__ == "__main__":
    main()
    print("完成")
