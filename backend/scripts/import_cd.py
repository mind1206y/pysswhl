"""传导完好率分组 4 模块历史数据导入:旧库 db_plan.dbo.CD_* → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点;可重复执行(逐表 TRUNCATE 重导)
- **bmid 必须重映射**:旧 bb_bumen.id 与新 departments.id 不对应且数字会撞车,
  一律读 migration_reports/department_map.json 的 bmid_map(⛔勿按名称现算)
- SQL Server datetime 精度 1/300 秒,统一截断微秒,避免 MySQL DATETIME(0) 四舍五入进 1 秒
- 锁定开关 consol_tb(conName='锁定传导报表') 只在缺失时插入,不覆盖页面上已改的状态
- 只 TRUNCATE 本模块的 4 张新表,不触碰任何其它模块的表

用法(backend 目录下):
    python -m scripts.import_cd --dry-run
    python -m scripts.import_cd

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pymysql

from app.core.config import settings
from scripts.import_vehicles import fetch_all, old_conn, write_table

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"

CD_WHL = [
    "id", "bmid", "ts", "sytss", "gztss", "whtss", "whl", "bbdate", "xzts",
    "bfts", "dcts", "tyts", "bz", "adddate", "finadate", "username",
    "decgztss", "decwhtss",
]
CD_GZ = [
    "id", "bmid", "sbname", "guanjing", "guancai", "didian", "ksdate", "jsdate",
    "yy", "ts", "bz", "bbdate", "adddate", "finadate", "username", "dects",
]
CD_DAXIU = [
    "id", "bbdate", "daxiudate", "lb", "nr", "gdh", "gdkj", "xbqkj", "fmkj",
    "xfskj", "num", "bz", "cfd", "sgy", "sgtel", "bmid", "adddate", "finadate",
    "username",
]
CD_XZ = [
    "id", "sbname", "bmid", "bbdate", "bdlb", "adddate", "finadate", "username",
]

# (旧表名, 字段, bmid 所在下标)
TABLES = [
    ("CD_whl", CD_WHL, CD_WHL.index("bmid")),
    ("CD_gz", CD_GZ, CD_GZ.index("bmid")),
    ("CD_daxiu", CD_DAXIU, CD_DAXIU.index("bmid")),
    ("CD_xz", CD_XZ, CD_XZ.index("bmid")),
]

LOCK_NAME = "锁定传导报表"


def _normalize(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        return value.rstrip()
    return value


def load_bmid_map():
    dept = json.loads((REPORT_DIR / "department_map.json").read_text(encoding="utf-8"))
    return {int(k): (int(v) if v else None) for k, v in dept["bmid_map"].items()}


def remap(rows, bmid_idx, bmid_map, table):
    """逐行一次性重映射(禁止逐条 UPDATE 循环,会链式污染)。"""
    out, missing = [], set()
    for row in rows:
        r = list(row)
        old = r[bmid_idx]
        if old is not None:
            if int(old) not in bmid_map:
                missing.add(int(old))
            r[bmid_idx] = bmid_map.get(int(old))
        out.append(tuple(_normalize(v) for v in r))
    if missing:
        print(f"  ⚠ {table}: 未映射的旧 bmid {sorted(missing)}(置 NULL)")
    return out


def old_baseline(data):
    def col_sum(table, fields, col):
        i = fields.index(col)
        return sum(float(r[i] or 0) for r in data[table])

    return {
        "CD_whl": {"ts": col_sum("CD_whl", CD_WHL, "ts"),
                   "sytss": col_sum("CD_whl", CD_WHL, "sytss"),
                   "decgztss": col_sum("CD_whl", CD_WHL, "decgztss"),
                   "decwhtss": col_sum("CD_whl", CD_WHL, "decwhtss")},
        "CD_gz": {"dects": col_sum("CD_gz", CD_GZ, "dects")},
        "CD_daxiu": {"num": col_sum("CD_daxiu", CD_DAXIU, "num")},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    bmid_map = load_bmid_map()
    conn = old_conn()
    try:
        ocur = conn.cursor()
        data = {}
        for table, fields, bidx in TABLES:
            rows = fetch_all(ocur, table, fields)
            data[table] = remap(rows, bidx, bmid_map, table)
        ocur.execute("SELECT val FROM consolTb WHERE conName=?", LOCK_NAME)
        lock_row = ocur.fetchone()
        old_lock = bool(lock_row[0]) if lock_row and lock_row[0] is not None else False

        baseline = old_baseline(data)
        print(f"  旧库基线: {[(t, len(v)) for t, v in data.items()]}; SUM={baseline}")
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            for table, fields, _bidx in TABLES:
                write_table(ncur, table, fields, data[table])
            # 锁定开关只在缺失时插入(重跑迁移不改变页面上已切换的状态)
            ncur.execute("SELECT id FROM consol_tb WHERE conName=%s", (LOCK_NAME,))
            if ncur.fetchone() is None:
                ncur.execute(
                    "INSERT INTO consol_tb (conName, val, intval) VALUES (%s, %s, NULL)",
                    (LOCK_NAME, int(old_lock)),
                )
                print(f"  补入开关 {LOCK_NAME} = {old_lock}")
            new.commit()

            for table, _fields, _bidx in TABLES:
                ncur.execute(f"SELECT COUNT(*) FROM `{table}`")
                got = ncur.fetchone()[0]
                if got != len(data[table]):
                    raise SystemExit(f"迁移校验失败:{table} 行数 {got} != {len(data[table])}")
            checks = [
                ("CD_whl", "SUM(ts)", baseline["CD_whl"]["ts"]),
                ("CD_whl", "SUM(sytss)", baseline["CD_whl"]["sytss"]),
                ("CD_whl", "SUM(decgztss)", baseline["CD_whl"]["decgztss"]),
                ("CD_whl", "SUM(decwhtss)", baseline["CD_whl"]["decwhtss"]),
                ("CD_gz", "SUM(dects)", baseline["CD_gz"]["dects"]),
                ("CD_daxiu", "SUM(num)", baseline["CD_daxiu"]["num"]),
            ]
            for table, expr, expect in checks:
                ncur.execute(f"SELECT COALESCE({expr},0) FROM `{table}`")
                got = float(ncur.fetchone()[0])
                if abs(got - expect) > 0.01:
                    raise SystemExit(
                        f"迁移校验失败:{table} {expr} 新={got:.2f} 旧={expect:.2f}"
                    )
            print("  校验通过:4 表行数一致,SUM(ts/sytss/decgztss/decwhtss/dects/num) 逐列 0 差异")

            report = {
                "source": "db_plan.dbo.CD_whl / CD_gz / CD_daxiu / CD_xz",
                "target": settings.DB_NAME,
                "rows": {t: len(v) for t, v in data.items()},
                "baseline": baseline,
                "bmid_map": {str(k): v for k, v in bmid_map.items()},
                "old_lock": old_lock,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            out = REPORT_DIR / "cd_import_report.json"
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  报告: {out}")
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
