"""车辆保险(CLbaoxian)历史数据导入:旧库 db_plan.dbo.cl_baoxian → 新库同名表。

- 保留旧主键 id,导完调整自增起点;可重复执行(TRUNCATE 重导)
- cl_baoxian 本身不带 bmid,部门经 cheid → cl_che(已按旧 id 原样迁移),无需部门重映射
- 校验:新旧行数/SUM(jine) 对齐;cheid 孤儿(旧车辆未迁移)检查

用法(backend 目录下):
    python -m scripts.import_baoxian --dry-run
    python -m scripts.import_baoxian
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

FIELDS = [
    "id", "cheid", "tbdate", "bdnumber", "lx", "jine", "bxcom", "dqdate",
    "djname", "djdate", "jingshou", "bz",
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
    args = parser.parse_args()

    oc = old_conn()
    ocur = oc.cursor()
    ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in FIELDS)} FROM [cl_baoxian]")
    rows = [tuple(r) for r in ocur.fetchall()]
    osum = ocur.execute("SELECT SUM(jine) FROM cl_baoxian").fetchone()[0] or 0
    print(f"旧库 cl_baoxian: {len(rows)} 条,SUM(jine)={osum}")
    oc.close()

    # cheid 孤儿检查(旧 id 应已随 import_vehicles.py 原样迁入新 cl_che)
    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute("SELECT id FROM cl_che")
    car_ids = {r[0] for r in cur.fetchall()}
    orphans = [r[0] for r in rows if r[1] is not None and r[1] not in car_ids]
    if orphans:
        print(f"⚠️ {len(orphans)} 条记录的 cheid 在新 cl_che 中不存在: {orphans[:20]}")
    else:
        print("cheid 全部匹配新 cl_che.id,无孤儿")

    if args.dry_run:
        conn.close()
        print("dry-run 完成,未写入")
        return

    cur.execute("TRUNCATE TABLE `cl_baoxian`")
    placeholders = ", ".join(["%s"] * len(FIELDS))
    sql = (f"INSERT INTO `cl_baoxian` (" + ", ".join(f"`{c}`" for c in FIELDS)
           + f") VALUES ({placeholders})")
    batch = []
    for r in rows:
        batch.append(tuple(r))
        if len(batch) >= 1000:
            cur.executemany(sql, batch)
            batch = []
    if batch:
        cur.executemany(sql, batch)
    max_id = max((r[0] for r in rows), default=0)
    if max_id:
        cur.execute(f"ALTER TABLE `cl_baoxian` AUTO_INCREMENT = {max_id + 1}")
    conn.commit()

    cur.execute("SELECT COUNT(*), SUM(jine) FROM cl_baoxian")
    n, s = cur.fetchone()
    print(f"新库写入: {n} 条,SUM(jine)={s}")
    ok = (n == len(rows)) and (abs(float(s or 0) - float(osum)) < 0.0001)
    print("校验:", "通过 ✓" if ok else "不一致 ✗")
    conn.close()


if __name__ == "__main__":
    main()
