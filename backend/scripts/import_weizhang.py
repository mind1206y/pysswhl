"""车辆违章历史数据导入:旧库 db_plan.dbo.clweizhang → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点
- 脚本可重复执行(TRUNCATE 重导),支持 --dry-run
- 本表不含 bmid,无需部门重映射

用法(backend 目录下):
    python -m scripts.import_weizhang --dry-run
    python -m scripts.import_weizhang

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse

import pymysql

from app.core.config import settings
from scripts.import_vehicles import fetch_all, old_conn, write_table

WEIZHANG = [
    "id", "cheid", "wzriqi", "lu", "jine", "fen", "xingming", "wz", "dj",
    "djriqi", "zhriqi", "gongli",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        rows = fetch_all(ocur, "clweizhang", WEIZHANG)
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            write_table(ncur, "clweizhang", WEIZHANG, rows)
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
