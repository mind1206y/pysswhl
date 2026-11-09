"""工程管理历史数据导入:旧库 db_plan.dbo.gongchenggl → 新库 gongchenggl。

按 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点
- 脚本可重复执行(先 TRUNCATE 目标表)

用法(backend 目录下):
    python -m scripts.import_projects --dry-run     # 只统计,不写入
    python -m scripts.import_projects --limit 20    # 试导 20 条
    python -m scripts.import_projects               # 全量导入

依赖:pyodbc + "ODBC Driver 17 for SQL Server"(不用 pymssql,2.4.x 对老版本
SQL Server 握手不稳定)。中文由 ODBC 驱动原生 Unicode 转换,无乱码。

旧库连接参数读环境变量(缺省本机):
    OLD_DB_HOST(默认 127.0.0.1) OLD_DB_PORT(默认 1433) OLD_DB_USER(默认 sa)
    OLD_DB_PASSWORD(默认 swgps) OLD_DB_NAME(默认 db_plan)
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

# 直接搬的字段(新旧同名同义)
FIELDS = [
    "id", "bmid", "pianqu", "xiangmuname", "xiangmudizhi", "xiangmuyezhu",
    "daijiandanwei", "shejidanwei", "jianlidanwei", "shigongdanwei",
    "lianxiren", "dianhua", "shenbaoriqi", "isyijiao", "yijiaoriqi",
    "isguidang", "guidangriqi", "CreateTime", "CreateUser", "xmleibie",
    "zijinleixing", "Status", "StatusRemark", "LastUpdateTime", "updateUser",
    "Remark",
]


def old_conn():
    host = os.environ.get("OLD_DB_HOST", "127.0.0.1")
    port = os.environ.get("OLD_DB_PORT", "1433")
    user = os.environ.get("OLD_DB_USER", "sa")
    password = os.environ.get("OLD_DB_PASSWORD", "swgps")
    name = os.environ.get("OLD_DB_NAME", "db_plan")
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={host},{port};"
        f"DATABASE={name};UID={user};PWD={password};",
        timeout=10,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--limit", type=int, default=0, help="最多导入 N 条(0=不限)")
    args = parser.parse_args()

    conn = old_conn()
    try:
        cur = conn.cursor()
        where = ""
        if args.limit:
            where = f" WHERE id IN (SELECT TOP {args.limit} id FROM gongchenggl ORDER BY id)"
        cur.execute(f"SELECT {', '.join(FIELDS)} FROM gongchenggl{where}")
        rows = [tuple(r) for r in cur.fetchall()]
        print(f"旧库取出 {len(rows)} 条")

        # 字典值核对(约定第4条):状态分布
        status_idx = FIELDS.index("Status")
        status_dist = {}
        for r in rows:
            status_dist[r[status_idx]] = status_dist.get(r[status_idx], 0) + 1
        print("Status 分布:", dict(sorted(status_dist.items(), key=lambda kv: (kv[0] is None, kv[0]))))

        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            # bmid 重映射:旧 bb_bumen.id → 新 departments.id(按部门名,与 import_water_fee 同规则)
            oc = old_conn()
            try:
                oc_cur = oc.cursor()
                oc_cur.execute("SELECT id, bm FROM bb_bumen")
                old_depts = dict(oc_cur.fetchall())
            finally:
                oc.close()
            ncur.execute("SELECT id, name FROM departments")
            by_name = {name: i for i, name in ncur.fetchall()}
            bmid_map = {oid: by_name.get(name) for oid, name in old_depts.items()}
            bidx = FIELDS.index("bmid")
            missing = set()
            fixed = []
            for r in rows:
                lst = list(r)
                v = lst[bidx]
                if v is not None:
                    lst[bidx] = bmid_map.get(v)
                    if lst[bidx] is None:
                        missing.add(v)
                fixed.append(tuple(lst))
            rows = fixed
            if missing:
                print(f"⚠ 旧 bmid {sorted(missing)} 在新 departments 无同名部门,已置空")

            ncur.execute("TRUNCATE TABLE gongchenggl")
            placeholders = ", ".join(["%s"] * len(FIELDS))
            sql = f"INSERT INTO gongchenggl ({', '.join(FIELDS)}) VALUES ({placeholders})"
            ncur.executemany(sql, rows)
            max_id = max(r[0] for r in rows) if rows else 0
            ncur.execute(f"ALTER TABLE gongchenggl AUTO_INCREMENT = {max_id + 1}")
            new.commit()
            print(f"已导入 {len(rows)} 条,自增起点调整为 {max_id + 1}")
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
