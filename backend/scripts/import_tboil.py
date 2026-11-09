"""加油统计(tboil)历史数据导入:旧库 db_plan.dbo.tboil → 新库同名表。

tboil 是旧系统「日常用车-提取整年公里数」生成的月度油量/公里数聚合表,
oiltj(车辆油量统计报表)的子表格/图表/月度年度导出都以它为数据源。

- 旧 id 原样保留,导完调整自增起点
- 无 bmid 列(只有 bumen 文本列),不需要部门 id 重映射
- cheid 沿用旧 cl_che.id;import_vehicles.py 保留旧主键,故无需重映射
- 可重复执行(先 TRUNCATE 再全量重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_tboil --dry-run
    python -m scripts.import_tboil
"""

import argparse
import os

import pyodbc
import pymysql
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

FIELDS = ["id", "cheid", "oildate", "oilnum", "lei", "username", "riqi",
          "glnum", "nian", "yue", "bumen", "oiljine"]


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

    conn = old_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join('[' + f + ']' for f in FIELDS)} FROM [tboil]")
    rows = [tuple(r) for r in cur.fetchall()]
    old_cnt = len(rows)
    old_sum_num = sum(r[3] for r in rows if r[3] is not None)
    old_sum_je = sum(r[11] for r in rows if r[11] is not None)
    print(f"旧库 tboil: {old_cnt} 条, SUM(oilnum)={old_sum_num}, SUM(oiljine)={old_sum_je}")

    with engine.connect() as c:
        new_ids = {i for (i,) in c.execute(text("SELECT id FROM cl_che"))}
    missing = {r[1] for r in rows if r[1] is not None} - new_ids
    if missing:
        print(f"⚠ {len(missing)} 个旧 cheid 在新库 cl_che 无对应车辆(车辆已删),记录保留原值")
        print(f"  样例: {sorted(missing)[:10]}")

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    placeholders = ", ".join(["%s"] * len(FIELDS))
    sql = ("INSERT INTO `tboil` (" + ", ".join(f"`{c}`" for c in FIELDS)
           + f") VALUES ({placeholders})")

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        ncur = new.cursor()
        ncur.execute("TRUNCATE TABLE tboil")
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
            ncur.execute(f"ALTER TABLE tboil AUTO_INCREMENT = {max_id + 1}")
        new.commit()
        print(f"写入 {len(rows)} 条,自增起点 {max_id + 1}")
    finally:
        new.close()

    # ===== 新旧对齐校验 =====
    with engine.connect() as c:
        n_cnt = c.execute(text("SELECT COUNT(*) FROM tboil")).scalar()
        n_sum_num = c.execute(text("SELECT SUM(oilnum) FROM tboil")).scalar()
        n_sum_je = c.execute(text("SELECT SUM(oiljine) FROM tboil")).scalar()
    print(f"新库 tboil: {n_cnt} 条, SUM(oilnum)={n_sum_num}, SUM(oiljine)={n_sum_je}")
    ok = (n_cnt == old_cnt
          and abs(float(n_sum_num or 0) - float(old_sum_num)) < 0.01
          and abs(float(n_sum_je or 0) - float(old_sum_je)) < 0.01)
    print("✅ 新旧完全对齐" if ok else "❌ 对齐失败,请检查")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
