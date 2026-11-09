"""手机管理历史数据导入:旧库 db_plan → 新库。

迁移表(保留旧主键 id,可重复执行 TRUNCATE 重导):
- shouji             手机台账(388 条)
- shouji_attachment  附件元数据(物理文件在旧生产服务器 Uploads/ShoujiAttachments/)
- shouji_huishou     回收登记
- shouji_edit_log    字段变更日志

另外:若新库 sim 表为空,顺带导入旧库 sim(手机编辑选号查卡信息用)。sim 属于
SIM 卡管理模块,已有数据时本脚本不覆盖,避免与 scripts.import_simcards 互相清表。

部门 id:旧 bb_bumen.id → 新 departments.id,统一读
scripts/migration_reports/department_map.json 的 bmid_map;映射不到置 NULL 并记录报告。

用法(backend 目录下):
    python -m scripts.import_phones --dry-run
    python -m scripts.import_phones
    python -m scripts.import_phones --force   # 新库已有数据时仍重导
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

SHOUJI_FIELDS = [
    "id", "bh", "pinpai", "guige", "qiyongdate", "jiage", "caozuotime",
    "caozuo", "bmid", "shiyongren", "yongtu", "haoma", "huishoudate",
    "huishouuser", "querendate", "querenuser", "bz", "djuser", "djtime",
    "zt", "liyou",
]
ATT_FIELDS = [
    "id", "shouji_id", "file_name", "file_path", "file_size",
    "upload_time", "operator_name",
]
HUISHOU_FIELDS = [
    "id", "huishoudate", "bmid", "huishouren", "shuliang", "shuoming",
    "djuser", "djtime",
]
LOG_FIELDS = [
    "id", "shouji_id", "field_name", "old_value", "new_value",
    "edit_user", "edit_time", "edit_type",
]
SIM_FIELDS = [
    "id", "kahao", "xuliehao", "imhao", "ip", "vpn", "taocan", "zt",
    "yongtu", "didian", "wangluo", "bz", "dengjiren", "djriqi", "zhriqi",
    "bianjiren", "bm", "glren", "syren", "delf", "zhanghu",
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
    raw = data.get("bmid_map") or {}
    return {int(k): v for k, v in raw.items()}


def fetch(cur, table, fields):
    cur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{table}] ORDER BY id")
    return [tuple(r) for r in cur.fetchall()]


def remap_bmid(rows, fields, field_name, bmid_map, missing):
    if field_name not in fields:
        return rows
    idx = fields.index(field_name)
    out = []
    for r in rows:
        lst = list(r)
        v = lst[idx]
        if v is not None:
            new = bmid_map.get(int(v))
            if new is None:
                missing.add(int(v))
            lst[idx] = new
        out.append(tuple(lst))
    return out


class MissingReport:
    def __init__(self):
        REPORT_DIR.mkdir(exist_ok=True)
        self.f = open(REPORT_DIR / "phone_bmid_unmapped.csv", "w", newline="", encoding="utf-8-sig")
        self.w = csv.writer(self.f)
        self.w.writerow(["表", "旧bmid", "处理"])
        self.count = 0

    def add(self, table, old_id):
        self.w.writerow([table, old_id, "新 departments 无对应部门,已置空"])
        self.count += 1

    def close(self):
        self.f.close()
        if self.count:
            print(f"⚠ 部门映射失败 {self.count} 处,明细见 {REPORT_DIR / 'phone_bmid_unmapped.csv'}")


def _insert(ncur, table, fields, rows):
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
    ncur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max(r[0] for r in rows) + 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--force", action="store_true", help="新表已有数据时仍 TRUNCATE 重导")
    args = parser.parse_args()

    bmid_map = load_bmid_map()
    report = MissingReport()
    conn = old_conn()
    try:
        cur = conn.cursor()
        tables = {
            "shouji": (fetch(cur, "shouji", SHOUJI_FIELDS), SHOUJI_FIELDS),
            "shouji_attachment": (fetch(cur, "shouji_attachment", ATT_FIELDS), ATT_FIELDS),
            "shouji_huishou": (fetch(cur, "shouji_huishou", HUISHOU_FIELDS), HUISHOU_FIELDS),
            "shouji_edit_log": (fetch(cur, "shouji_edit_log", LOG_FIELDS), LOG_FIELDS),
        }
        sim_rows = fetch(cur, "sim", SIM_FIELDS)

        for table, bmid_field in (("shouji", "bmid"), ("shouji_huishou", "bmid")):
            rows, fields = tables[table]
            missing = set()
            rows = remap_bmid(rows, fields, bmid_field, bmid_map, missing)
            tables[table] = (rows, fields)
            for old_id in sorted(missing):
                report.add(table, old_id)
            if missing:
                print(f"⚠ {table}.{bmid_field} 旧值 {sorted(missing)} 无映射,已置空")

        missing_sim = set()
        sim_rows = remap_bmid(sim_rows, SIM_FIELDS, "bm", bmid_map, missing_sim)
        if missing_sim:
            print(f"⚠ sim.bm 旧值 {sorted(missing_sim)} 无映射,已置空")

        for table, (rows, _fields) in tables.items():
            print(f"{table}: 旧库 {len(rows)} 条")
        print(f"sim: 旧库 {len(sim_rows)} 条(仅当新库为空时导入)")

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
                for table in tables:
                    ncur.execute(f"SELECT COUNT(*) FROM `{table}`")
                    existing = ncur.fetchone()[0]
                    if existing:
                        raise SystemExit(
                            f"新库 {table} 已有 {existing} 条,未覆盖(需要重导请加 --force)"
                        )
            for table, (rows, fields) in tables.items():
                ncur.execute(f"TRUNCATE TABLE `{table}`")
                if rows:
                    _insert(ncur, table, fields, rows)
                    print(f"{table}: 已导入 {len(rows)} 条,自增起点 {max(r[0] for r in rows) + 1}")
            ncur.execute("SELECT COUNT(*) FROM `sim`")
            if ncur.fetchone()[0] == 0 and sim_rows:
                ncur.execute("TRUNCATE TABLE `sim`")
                _insert(ncur, "sim", SIM_FIELDS, sim_rows)
                print(f"sim: 已导入 {len(sim_rows)} 条,自增起点 {max(r[0] for r in sim_rows) + 1}")
            else:
                print("sim: 新库已有数据,跳过(由 SIM 卡管理模块维护)")
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()
        report.close()


if __name__ == "__main__":
    main()
    print("完成")
