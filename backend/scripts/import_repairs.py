"""车辆维修(chelwx)历史数据导入:旧库 db_plan.dbo.* → 新库同名表。

表:cl_wxdw(维修单位)、cl_wxdan(维修单)、cl_wxmx(维修明细)、cl_wxdTP(图片)。
- 保留旧主键 id,导完调整自增起点;可重复执行(逐表 TRUNCATE 重导)
- 维修单部门来自 cl_che.bmid,本模块表本身不带 bmid,无需部门重映射
- 旧图片表当前 0 条;图片物理文件在旧生产服务器 /Upload/weixiudanImages/

用法(backend 目录下):
    python -m scripts.import_repairs --dry-run
    python -m scripts.import_repairs
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

WXDW = ["id", "dwname"]
WXDAN = [
    "id", "jcriqi", "bxren", "gonglinum", "xiangmu", "jine", "ccriqi", "cheid",
    "djriqi", "username", "wxdw", "gongshifei", "peijianfei", "zk", "lx", "sp",
    "spren", "sptime",
]
WXMX = [
    "id", "wxdid", "xiangmu", "danjia", "shuliang", "zonge", "pjorgs", "djriqi",
    "username", "guige", "gjz", "cheid", "zkqiandanjia",
]
WXDTP = ["id", "wxdid", "url"]

TABLES = [
    ("cl_wxdw", WXDW),
    ("cl_wxdan", WXDAN),
    ("cl_wxmx", WXMX),
    ("cl_wxdTP", WXDTP),
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
    max_id = max((r[0] for r in rows), default=0)
    if max_id:
        cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        data = {t: fetch_all(ocur, t, f) for t, f in TABLES}
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            for table, fields in TABLES:
                write_table(ncur, table, fields, data[table])
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
