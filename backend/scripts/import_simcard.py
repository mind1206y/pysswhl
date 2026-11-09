"""SIM 卡管理历史数据导入:旧库 db_plan → 新库。

表:
- sim_edit_log   字段修改日志
- sim_taocan / sim_vpn / sim_wangluo / sim_zhuangtai  字典
- feiyong        月度话费(84879 条,含 bm 部门重映射)
- linshi         旧上传核对临时表(通常 0 条)

主表 sim 由「手机管理」的 scripts.import_phones 一并迁移(两模块共用 sim 表)。
如需在本脚本里重导主表,加 --include-sim --force。

部门映射:读取 scripts/migration_reports/department_map.json 的 bmid_map,
旧 bb_bumen.id → 新 departments.id;匹配不到置 NULL 并输出报告。

用法(backend 目录下):
    python -m scripts.import_simcard --dry-run
    python -m scripts.import_simcard
    python -m scripts.import_simcard --force            # 目标表已有数据也重导
    python -m scripts.import_simcard --include-sim --force
"""

import argparse
import csv
import json
import os
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
DEPT_MAP_FILE = REPORT_DIR / "department_map.json"

SIM_FIELDS = [
    "id", "kahao", "xuliehao", "imhao", "ip", "vpn", "taocan", "zt",
    "yongtu", "didian", "wangluo", "bz", "dengjiren", "djriqi", "zhriqi",
    "bianjiren", "bm", "glren", "syren", "delf", "zhanghu",
]
LOG_FIELDS = [
    "id", "sim_id", "field_name", "old_value", "new_value", "edit_user",
    "edit_time", "edit_type",
]
TAOCAN_FIELDS = ["id", "taocan"]
VPN_FIELDS = ["id", "vpn"]
WANGLUO_FIELDS = ["id", "wangluo"]
ZHUANGTAI_FIELDS = ["id", "zhuangtai"]
FEIYONG_FIELDS = ["id", "kahao", "jine", "nian", "yue", "syren", "bm", "bz"]
LINSHI_FIELDS = ["id", "kahao", "op"]

TABLES = [
    ("sim_edit_log", LOG_FIELDS),
    ("sim_taocan", TAOCAN_FIELDS),
    ("sim_vpn", VPN_FIELDS),
    ("sim_wangluo", WANGLUO_FIELDS),
    ("sim_zhuangtai", ZHUANGTAI_FIELDS),
    ("feiyong", FEIYONG_FIELDS),
    ("linshi", LINSHI_FIELDS),
]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def load_bmid_map():
    if not DEPT_MAP_FILE.exists():
        raise SystemExit(f"缺少部门映射 {DEPT_MAP_FILE},请先运行 scripts.import_departments")
    data = json.loads(DEPT_MAP_FILE.read_text(encoding="utf-8"))
    return {int(k): v for k, v in (data.get("bmid_map") or {}).items()}


def fetch(cur, table, fields):
    cur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{table}] ORDER BY id")
    return [tuple(r) for r in cur.fetchall()]


def remap_bm(rows, fields, bmid_map, missing):
    if "bm" not in fields:
        return rows
    idx = fields.index("bm")
    out = []
    for r in rows:
        old = r[idx]
        if old is None:
            out.append(r)
            continue
        new = bmid_map.get(int(old))
        if new is None:
            missing.add(int(old))
        row = list(r)
        row[idx] = new
        out.append(tuple(row))
    return out


def write_table(ncur, table, fields, rows):
    ncur.execute(f"TRUNCATE TABLE `{table}`")
    if rows:
        ph = ", ".join(["%s"] * len(fields))
        sql = (f"INSERT INTO `{table}` (" + ", ".join(f"`{f}`" for f in fields)
               + f") VALUES ({ph})")
        batch = []
        for r in rows:
            batch.append(r)
            if len(batch) >= 1000:
                ncur.executemany(sql, batch)
                batch = []
        if batch:
            ncur.executemany(sql, batch)
        max_id = max(r[0] for r in rows)
        ncur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--force", action="store_true", help="目标表已有数据也 TRUNCATE 重导")
    parser.add_argument("--include-sim", action="store_true", help="同时重导主表 sim")
    args = parser.parse_args()

    bmid_map = load_bmid_map()
    missing = set()
    tables = list(TABLES)
    if args.include_sim:
        tables.insert(0, ("sim", SIM_FIELDS))

    conn = old_conn()
    try:
        cur = conn.cursor()
        data = {}
        for table, fields in tables:
            rows = fetch(cur, table, fields)
            if table in ("sim", "feiyong"):
                rows = remap_bm(rows, fields, bmid_map, missing)
            data[table] = (rows, fields)
            print(f"{table}: 旧库 {len(rows)} 条")
        if missing:
            print(f"警告: 旧 bm {sorted(missing)} 无部门映射,已置 NULL")

        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            if not args.force:
                for table, _fields in tables:
                    ncur.execute(f"SELECT COUNT(*) FROM `{table}`")
                    existing = ncur.fetchone()[0]
                    if existing:
                        raise SystemExit(
                            f"新库 {table} 已有 {existing} 条,未覆盖(需要重导请加 --force)"
                        )
            for table, (rows, fields) in data.items():
                write_table(ncur, table, fields, rows)
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()

    if missing:
        REPORT_DIR.mkdir(exist_ok=True)
        path = REPORT_DIR / "simcard_missing_bm.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["旧bb_bumen.id", "说明"])
            for old in sorted(missing):
                w.writerow([old, "无部门映射,已置 NULL"])
        print(f"部门映射失败明细: {path}")


if __name__ == "__main__":
    main()
    print("完成")
