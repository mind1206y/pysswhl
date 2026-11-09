"""车辆各类费用历史数据导入:旧库 db_plan.dbo.cl_feiyong → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库(仅备注类 varchar 放宽),保留旧主键 id,导完调整自增起点
- 脚本可重复执行(TRUNCATE 重导),支持 --dry-run
- 本表不含 bmid:部门归属通过 cheid → cl_che.bmid 取得,无需部门重映射
- cl_che 由 import_vehicles.py 迁移,⛔本脚本严禁重导车辆表

用法(backend 目录下):
    python -m scripts.import_clfeiyong --dry-run
    python -m scripts.import_clfeiyong

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
from datetime import datetime

import pymysql

from app.core.config import settings
from scripts.import_vehicles import fetch_all, old_conn, write_table

FIELDS = [
    "id", "cheid", "lx", "jine", "bz", "username", "djdate", "zuihoudate",
    "feiyongdate", "dw", "fangshi", "jingshou",
]


def _normalize(value):
    """SQL Server datetime 精度为 1/300 秒(如 08:49:17.997),直接写 MySQL
    DATETIME(0) 会被四舍五入成 08:49:18,逐列比对会差 1 秒。统一截断到秒。
    """
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        rows = [tuple(_normalize(v) for v in r)
                for r in fetch_all(ocur, "cl_feiyong", FIELDS)]
        jine_idx = FIELDS.index("jine")
        old_sum = sum((r[jine_idx] or 0) for r in rows)
        print(f"  旧库 cl_feiyong: {len(rows)} 条, SUM(jine)={old_sum}")
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            write_table(ncur, "cl_feiyong", FIELDS, rows)
            new.commit()
            ncur.execute("SELECT COUNT(*), COALESCE(SUM(jine), 0) FROM cl_feiyong")
            count, total = ncur.fetchone()
            print(f"  新库核对: {count} 条, SUM(jine)={total}")
            if count != len(rows) or float(total) != float(old_sum):
                raise SystemExit("迁移校验失败:行数或金额合计与旧库不一致")
            print("  校验通过:行数与金额合计与旧库一致")
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
