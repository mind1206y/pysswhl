"""测漏成果历史数据导入:旧库 db_plan.dbo.celouTb / CLdui → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点
- 脚本可重复执行(逐表 TRUNCATE 重导),支持 --dry-run
- **bmid 必须重映射**:旧 bb_bumen.id 与新 departments.id 完全不对应且数字会撞车,
  按部门名精确匹配;旧部门名另存 celouTb.bm,便于导出「经办部门」列与回溯。
  本模块 6 个旧部门(2/5/6/7/8/9)在新库均有同名部门,实测 0 行对不上。

用法(backend 目录下):
    python -m scripts.import_celou --dry-run
    python -m scripts.import_celou

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

CELOU_TB = [
    "id", "gongdan", "bgdate", "xiufudate", "didian", "guanjing", "guancai",
    "yy", "dwwucha", "dingliang", "louliang", "bmid", "celoudw", "nian",
    "yue", "scdatetime", "username", "bh", "gjsmall", "gjbig", "yudingliang",
    "zuobiao_leibie", "zuobiao_jingdu", "zuobiao_weidu",
]
CLDUI = ["id", "coname"]

TABLES = [
    ("celouTb", CELOU_TB, CELOU_TB.index("bmid")),
    ("CLdui", CLDUI, None),
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


def build_bmid_map(ocur, ncur):
    """旧 bb_bumen.id → 新 departments.id(按部门名精确匹配;找不到为 None)。"""
    ocur.execute("SELECT id, bm FROM bb_bumen")
    old = dict(ocur.fetchall())
    ncur.execute("SELECT id, name FROM departments")
    by_name = {name: i for i, name in ncur.fetchall()}
    return {oid: by_name.get(name) for oid, name in old.items()}, old


def fetch_all(ocur, table, fields):
    ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{table}]")
    rows = [tuple(r) for r in ocur.fetchall()]
    print(f"  {table}: 旧库 {len(rows)} 条")
    return rows


def remap(rows, idx, bmid_map, table):
    """bmid 一次性按映射表替换(禁止逐条 UPDATE,避免旧/新 id 空间重叠链式污染)。"""
    missing = set()
    out = []
    for r in rows:
        lst = list(r)
        v = lst[idx]
        if v is not None:
            lst[idx] = bmid_map.get(v)
            if lst[idx] is None:
                missing.add(v)
        out.append(tuple(lst))
    if missing:
        print(f"  ⚠ {table}: 旧 bmid {sorted(missing)} 在新 departments 无同名部门,已置空")
    return out


def write_table(ncur, table, fields, rows):
    ncur.execute(f"TRUNCATE TABLE `{table}`")
    placeholders = ", ".join(["%s"] * len(fields))
    sql = (f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in fields)
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
        ncur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        data = {t: fetch_all(ocur, t, f) for t, f, _ in TABLES}
        print("--- 数据核对 ---")
        che = data["celouTb"]
        bi = CELOU_TB.index("bmid")
        depts = {}
        for r in che:
            depts[r[bi]] = depts.get(r[bi], 0) + 1
        print(f"  旧 bmid 分布: {dict(sorted(depts.items(), key=lambda kv: str(kv[0])))}")
        li = CELOU_TB.index("louliang")
        print(f"  漏量合计: {sum(float(r[li] or 0) for r in che):.2f}")
        ni = CELOU_TB.index("nian")
        print(f"  年度分布: {dict(sorted({y: sum(1 for r in che if r[ni] == y) for y in {r[ni] for r in che}}.items()))}")
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            bmid_map, old_depts = build_bmid_map(ocur, ncur)
            print(f"  bmid 映射(本模块用到的): "
                  f"{ {k: v for k, v in bmid_map.items() if k in depts} }")
            for table, fields, bidx in TABLES:
                rows = data[table]
                if table == "celouTb":
                    # 旧部门名另存 bm 列(必须在 bmid 重映射之前取,否则查到的是新 id)
                    rows = [r + (old_depts.get(r[bi]) or "",) for r in rows]
                    fields = CELOU_TB + ["bm"]
                if bidx is not None:
                    rows = remap(rows, bidx, bmid_map, table)
                write_table(ncur, table, fields, rows)
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
