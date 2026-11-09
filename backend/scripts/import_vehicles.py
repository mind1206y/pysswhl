"""车辆管理历史数据导入:旧库 db_plan.dbo.* → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点
- 脚本可重复执行(逐表 TRUNCATE 重导),支持 --dry-run
- **bmid 必须重映射**:旧 bb_bumen.id 与新 departments.id 完全不对应且数字会撞车,
  按部门名精确匹配;新库没有同名部门的置 NULL,并把旧部门名写进 cl_che.bm 保留显示。

用法(backend 目录下):
    python -m scripts.import_vehicles --dry-run
    python -m scripts.import_vehicles
    python -m scripts.import_vehicles --copy-files "E:/旧系统/Upload"

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
import os
import shutil
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

# (旧表名, 字段清单, bmid 所在下标或 None)
CL_CHE = [
    "id", "lx", "jiashiyuan", "telphone", "chehao", "chuchang", "pingshi", "zhoumo",
    "bmid", "yongtu", "caozuo", "zuihoutime", "shenheren", "delf", "pinpai", "spren",
    "spzt", "spdate", "oil", "oilcard", "jsz", "jiage", "grriqi", "etc", "danganhao",
    "syxingzhi", "zws", "fadongjihao", "chejiahao", "pailiang", "LastReminderDate",
    "ReminderYear", "ReminderLevel", "IsInspected", "InspectionDate",
    "NextInspectionDate", "xinghao",
]
CHETUPIAN = ["id", "cheid", "url", "file_name"]
CHUXIAN = ["id", "riqi", "bm", "cheid", "zeren", "jiashiyuan", "jine", "miaoshu",
           "caozuo", "zuihou", "dizhi", "gongli"]
CXTP = ["id", "cxid", "url"]
PLUSOIL = ["id", "oill", "lei", "jine", "ptime", "kaid", "cheid", "addtime",
           "bmid", "didian", "leibie"]
YONGCHERC = [
    "id", "ksdate", "jsdate", "ksgl", "jsgl", "yuanyin", "beizhu", "didian",
    "usercar", "shenhe", "bumenld", "cheid", "cz", "czy", "shenheqz", "shenpi",
    "shtime", "sptime", "tingfang", "shenQingTime", "ok", "sj",
]
YONGCHERC_TP = ["id", "url", "yongchercid"]
WXDAN = [
    "id", "jcriqi", "bxren", "gonglinum", "xiangmu", "jine", "ccriqi", "cheid",
    "djriqi", "username", "wxdw", "gongshifei", "peijianfei", "zk", "lx", "sp",
    "spren", "sptime",
]

TABLES = [
    ("cl_che", CL_CHE, CL_CHE.index("bmid")),
    ("cl_chetupian", CHETUPIAN, None),
    ("cl_chuxian", CHUXIAN, None),
    ("cl_cxTP", CXTP, None),
    ("PlusOil", PLUSOIL, PLUSOIL.index("bmid")),
    ("yongcherc", YONGCHERC, None),
    ("yongchercTP", YONGCHERC_TP, None),
    ("cl_wxdan", WXDAN, None),
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
    """bmid 一次性按映射表替换(不做逐条 UPDATE,避免旧/新 id 空间重叠链式污染)。"""
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


def copy_images(conn, source: Path):
    """把旧系统生产服务器 Upload/cheliangImages 下的图片拷进 backend/uploads。

    url 形如 /Upload/cheliangImages/2021/7/28/x.jpg → uploads/cheliangImages/2021/7/28/x.jpg
    """
    cur = conn.cursor()
    urls = []
    for table in ("cl_chetupian", "cl_cxTP", "yongchercTP"):
        cur.execute(f"SELECT url FROM [{table}]")
        urls += [r[0] for r in cur.fetchall() if r[0]]
    dest_root = Path(settings.UPLOAD_DIR)
    ok, missing = 0, 0
    for url in urls:
        rel = (url or "").replace("\\", "/").lstrip("/")
        if rel.lower().startswith("upload/"):
            rel = rel[len("upload/"):]
        # 源目录可能是 Upload 目录,也可能直接是 cheliangImages 目录,两种都兼容
        src = source / rel
        if not src.exists() and rel.lower().startswith("cheliangimages/"):
            src = source / rel[len("cheliangimages/"):]
        if not src.exists():
            missing += 1
            continue
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        ok += 1
    print(f"图片复制:成功 {ok} 个,源目录缺失 {missing} 个(缺失的可稍后补拷,记录仍在)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--copy-files", default="", help="旧系统 Upload 目录,复制历史车辆图片")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        data = {t: fetch_all(ocur, t, f) for t, f, _ in TABLES}
        print("--- 字典值核对 ---")
        che = data["cl_che"]
        for label, idx in (("delf", CL_CHE.index("delf")), ("lx", CL_CHE.index("lx")),
                           ("yongtu", CL_CHE.index("yongtu")), ("oil", CL_CHE.index("oil")),
                           ("spzt", CL_CHE.index("spzt"))):
            dist = {}
            for r in che:
                k = r[idx] if r[idx] is not None else "(空)"
                dist[k] = dist.get(k, 0) + 1
            print(f"  {label}: {dict(sorted(dist.items(), key=lambda kv: str(kv[0])))}")
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
            print(f"  bmid 映射(仅列可匹配的): { {k: v for k, v in bmid_map.items() if v} }")
            for table, fields, bidx in TABLES:
                rows = data[table]
                if table == "cl_che":
                    # 旧部门名另存 bm 列(必须在 bmid 重映射之前取,否则查到的是新 id)
                    bi = CL_CHE.index("bmid")
                    rows = [r + (old_depts.get(r[bi]) or "",) for r in rows]
                    fields = CL_CHE + ["bm"]
                if bidx is not None:
                    rows = remap(rows, bidx, bmid_map, table)
                write_table(ncur, table, fields, rows)
            new.commit()
        finally:
            new.close()

        if args.copy_files:
            copy_images(conn, Path(args.copy_files))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
