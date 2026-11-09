"""油卡台账历史数据导入:旧库 db_plan.dbo.OilCard → 新库 OilCard。

旧表主键 id 与 cl_che.id 在新库中保持不变(车辆数据已按原 id 导入),因此直接保留。
只操作 OilCard 一张表;新表已有数据时默认拒绝执行,需加 --force 才会 TRUNCATE 重导。

用法(backend 目录下):
    python -m scripts.import_oilcards --dry-run
    python -m scripts.import_oilcards
    python -m scripts.import_oilcards --force
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

FIELDS = [
    "id", "kanum", "djdate", "editdate", "chehao", "zt", "youpin",
    "bfj", "ye", "yujing", "carid", "handadd", "yanzhengma", "bz",
]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};"
        f"PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--force", action="store_true", help="新表已有数据时仍 TRUNCATE 重导")
    args = parser.parse_args()

    old = old_conn()
    try:
        cur = old.cursor()
        cur.execute(f"SELECT {', '.join('[' + f + ']' for f in FIELDS)} FROM [OilCard]")
        rows = [tuple(r) for r in cur.fetchall()]
    finally:
        old.close()
    print(f"旧库 OilCard:{len(rows)} 条")
    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        ncur = new.cursor()
        ncur.execute("SELECT COUNT(*) FROM `OilCard`")
        existing = ncur.fetchone()[0]
        if existing and not args.force:
            print(f"新库 OilCard 已有 {existing} 条,未覆盖(需要重导请加 --force)")
            return
        ncur.execute("TRUNCATE TABLE `OilCard`")
        placeholders = ", ".join(["%s"] * len(FIELDS))
        sql = ("INSERT INTO `OilCard` (" + ", ".join(f"`{c}`" for c in FIELDS)
               + f") VALUES ({placeholders})")
        batch = []
        for r in rows:
            batch.append(tuple(r))
            if len(batch) >= 1000:
                ncur.executemany(sql, batch)
                batch = []
        if batch:
            ncur.executemany(sql, batch)
        max_id = max((r[0] for r in rows), default=0)
        if max_id:
            ncur.execute(f"ALTER TABLE `OilCard` AUTO_INCREMENT = {max_id + 1}")
        new.commit()
        print(f"写入 {len(rows)} 条,自增起点 {max_id + 1}")
    finally:
        new.close()


if __name__ == "__main__":
    main()
    print("完成")
