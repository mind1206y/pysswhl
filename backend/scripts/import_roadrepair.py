"""路面修复管理历史数据导入:旧库 db_plan.dbo.* -> 新库同名表。

- road_repair(508) / road_repair_progress(7) / road_price(37) /
  road_repair_attachment(60) / qiangxiurenyuan(14):全部保留旧主键 id,导入后调整自增
- qiangxiurenyuan.bmid 按 migration_reports/department_map.json 重映射到新
  departments.id;映射不到时置 NULL 并告警(road_repair 系列表无 bmid 字段,不涉及)
- 附件 file_path 原样保留(物理文件在旧生产服务器 ~/Uploads/Repair/,接口缺文件
  返回「附件文件缺失」)
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_roadrepair --dry-run
    python -m scripts.import_roadrepair
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

REPAIR_FIELDS = [
    "id", "address", "dig_date", "road_type", "reason", "remark", "area",
    "final_area", "price", "total", "company", "current_progress",
    "operator_name", "operate_time", "banzu",
]
PROGRESS_FIELDS = ["id", "repair_id", "progress", "progress_date", "operator_name"]
PRICE_FIELDS = ["id", "company", "road_type", "price", "operator_name", "operate_time"]
ATT_FIELDS = ["id", "repair_id", "file_name", "file_path", "file_size",
              "upload_time", "operator_name"]
QX_FIELDS = ["id", "name", "bmid"]

TABLES = [
    ("road_repair", REPAIR_FIELDS),
    ("road_repair_progress", PROGRESS_FIELDS),
    ("road_price", PRICE_FIELDS),
    ("road_repair_attachment", ATT_FIELDS),
    ("qiangxiurenyuan", QX_FIELDS),
]


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


def write_table(cur, table, fields, rows):
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
    max_id = max((r[0] for r in rows if r[0] is not None), default=0)
    if max_id:
        cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    bmid_map = load_bmid_map()
    missing = Counter()

    oc = old_conn()
    data = {}
    try:
        ocur = oc.cursor()
        for table, fields in TABLES:
            data[table] = fetch_all(ocur, table, fields)
    finally:
        oc.close()

    # qiangxiurenyuan.bmid 重映射(唯一带 bmid 的表)
    mapped = []
    qx_fields = dict(TABLES)["qiangxiurenyuan"]
    bmid_idx = qx_fields.index("bmid")
    for row in data["qiangxiurenyuan"]:
        rec = list(row)
        old_bmid = rec[bmid_idx]
        if old_bmid is None:
            rec[bmid_idx] = None
        else:
            new_bmid = bmid_map.get(int(old_bmid))
            if new_bmid is None:
                missing[old_bmid] += 1
            rec[bmid_idx] = new_bmid
        mapped.append(tuple(rec))
    data["qiangxiurenyuan"] = mapped
    total_qx = len(mapped)
    print(
        f"  qiangxiurenyuan.bmid 映射: {total_qx - sum(missing.values())}/{total_qx} 有映射"
    )
    if missing:
        print(f"  未映射旧 bmid: {dict(missing)} (对应记录 bmid 置 NULL)")

    # 汇总校验口径
    sum_total = sum(float(r[9] or 0) for r in data["road_repair"])
    print(f"  road_repair SUM(total) = {sum_total:.2f}")

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
            for table, fields in TABLES:
                write_table(ncur, table, fields, data[table])
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
