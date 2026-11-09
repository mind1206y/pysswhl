"""年度计划模块历史数据导入:旧库 db_plan.dbo.* -> 新库同名表。

覆盖 4 个页面共 10 张表:
- gx_gxgz(4428) / gx_jindu(41) / gx_user_gxgz(1022) / gx_jilu(835) / gx_jiluTupian(367)
- jh_yyfq(1107) / jh_ssdb(1614) / jh_ssdbpz(34425)
- shuifeixitong_log 与特殊群体管理共用,已由 import_water_fee 全量导入,本脚本不碰
- consol_tb 不导(开关默认关闭,由页面维护)

映射规则:
- 旧部门 id -> 新 departments.id,走 migration_reports/department_map.json 的 bmid_map;
  映射不到的 bmid/bumenid/zb 置 NULL 并告警
- 旧用户名 -> *name 快照列(bb_user.username);新系统用户表是重建的,不保证能映射
- 保留旧主键 id,导入后调整自增起点;可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_plans --dry-run
    python -m scripts.import_plans
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"

# 导入顺序:先父表后子表;清空时反向
TABLES = [
    # (新表, 旧表, 旧字段列表, 主键字段, 是否自增)
    ("gx_jindu", "gx_jindu", ["id", "leixing", "value"], "id", True),
    ("gx_gxgz", "gx_gxgz", [
        "id", "xh", "name", "bz", "jine", "lb", "zb", "fzr", "bm", "nd", "ssusers",
        "rongyu", "zongji", "bmid", "xmbz", "nxuhao", "zgy", "zbj", "zbjrq",
        "zbjdjr", "zbjdjriqi", "khbj",
    ], "id", True),
    ("gx_user_gxgz", "gx_user_gxgz", [
        "id", "userid", "gxgzid", "rongyu1", "rongyu2",
    ], "id", True),
    ("gx_jilu", "gx_jilu", [
        "id", "miaoshu", "beizhu", "caozuotime", "riqi", "guanzhuid",
        "zhuangtaiid", "fukuan", "jindu",
    ], "id", True),
    ("gx_jiluTupian", "gx_jiluTupian", ["id", "url", "jiuid"], "id", True),
    ("jh_yyfq", "jh_yyfq", [
        "id", "faqiname", "bz", "jine", "zgy", "jhlb", "zt", "opid", "niandu",
        "bmid", "fqtimep", "lastop", "beginTime", "startjine", "zongtouzi",
        "kgny", "jgny", "xjxl",
    ], "id", True),
    ("jh_ssdb", "jh_ssdb", [
        "id", "xuhao", "daibanname", "bz", "jine", "zb", "fzr", "niandu", "jhlb",
        "zt", "zhuanguan", "opname", "bumenid", "faqiid", "dbtimep", "kstimep",
        "pizhu", "lastop", "nxuhao", "yincang", "leibie", "startjine",
        "zongtouzi", "kgny", "jgny", "xjxl", "FlowInstanceId", "FlowStatus",
    ], "id", True),
    ("jh_ssdbpz", "jh_ssdbpz", [
        "dbid", "id", "xuhao", "daibanname", "bz", "jine", "zb", "fzr", "niandu",
        "jhlb", "zt", "zhuanguan", "opname", "bumenid", "faqiid", "dbtimep",
        "kstimep", "pizhu", "lastop", "nxuhao", "yincang", "leibie", "startjine",
        "zongtouzi", "kgny", "jgny", "xjxl",
    ], "dbid", True),
]

# shuifeixitong_log 与「特殊群体管理」共用,已由 import_water_fee 全量导入
# (old source=jhssdb 479 条 id 7907~8385),本脚本不碰,避免清掉水费日志。

# 从旧部门 id 映射到新部门 id 的列
DEPT_COLS = {
    "gx_gxgz": ["bmid"],
    "jh_yyfq": ["bmid"],
    "jh_ssdb": ["zb", "bumenid"],
    "jh_ssdbpz": ["zb", "bumenid"],
}

# 需要补 username 快照的列:(新表, 旧用户id列, 新快照列)
USER_NAME_COLS = {
    "gx_user_gxgz": ("userid", "username"),
    "jh_yyfq": ("zgy", "zgy_name"),
    "jh_ssdb": ("zhuanguan", "zhuanguan_name"),
    "jh_ssdbpz": ("zhuanguan", "zhuanguan_name"),
}

# jh_yyfq 的发起人姓名快照
YYFQ_OPNAME = ("opid", "opname")


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )


def load_dept_map() -> tuple[dict, dict]:
    if not MAP_FILE.exists():
        raise SystemExit(
            f"缺少部门映射文件 {MAP_FILE},请先运行 python -m scripts.import_departments"
        )
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    bmid_map = {int(k): int(v) for k, v in data.get("bmid_map", {}).items()}
    return bmid_map, data.get("depts", {})


def load_users(ocur) -> dict:
    """旧 bb_user.id -> username。"""
    try:
        cur = ocur.cursor()
        cur.execute("SELECT [id], [username] FROM [bb_user]")
        return {int(r[0]): (r[1] or "") for r in cur.fetchall()}
    except Exception as exc:  # pragma: no cover
        print(f"  警告:读取 bb_user 失败({exc}),用户姓名快照将为空")
        return {}


def fetch_table(ocur, table, fields):
    cols = ", ".join(f"[{f}]" for f in fields)
    cur = ocur.cursor()
    cur.execute(f"SELECT {cols} FROM [{table}]")
    return [tuple(r) for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    bmid_map, dept_meta = load_dept_map()
    ocur = old_conn()
    ncur = new_conn().cursor()

    users = load_users(ocur)
    print(f"旧部门映射 {len(bmid_map)} 项,旧用户 {len(users)} 人")

    # 先拉取并加工全部数据
    prepared = {}
    for new_table, old_table, fields, pk, _ai in TABLES:
        rows = fetch_table(ocur, old_table, fields)
        print(f"  读取 {old_table}: {len(rows)} 条")
        idx = {f: i for i, f in enumerate(fields)}

        # 部门映射
        for col in DEPT_COLS.get(new_table, []):
            j = idx[col]
            unmapped = Counter()
            new_rows = []
            for r in rows:
                r = list(r)
                if r[j] is not None:
                    mapped = bmid_map.get(int(r[j]))
                    if mapped is None:
                        unmapped[int(r[j])] += 1
                        r[j] = None
                    else:
                        r[j] = mapped
                new_rows.append(tuple(r))
            rows = new_rows
            if unmapped:
                print(f"    警告:{new_table}.{col} 未映射部门: {dict(unmapped)}")

        # 用户名快照
        if new_table in USER_NAME_COLS:
            uid_col, name_col = USER_NAME_COLS[new_table]
            j = idx[uid_col]
            names = []
            for r in rows:
                uid = r[j]
                names.append(users.get(int(uid)) if uid is not None else "")
            fields = fields + [name_col]
            rows = [tuple(list(r) + [names[i]]) for i, r in enumerate(rows)]

        if new_table == "jh_yyfq":
            uid_col, name_col = YYFQ_OPNAME
            j = idx[uid_col]
            names = [users.get(int(r[j])) if r[j] is not None else "" for r in rows]
            fields = fields + [name_col]
            rows = [tuple(list(r) + [names[i]]) for i, r in enumerate(rows)]

        prepared[new_table] = (fields, rows)

    if args.dry_run:
        print("\n[dry-run] 不写入数据库")
        return

    nconn = new_conn()
    ncur = nconn.cursor()
    # 部门旧系统元信息(排序号/主办标记)回填,计划编号前缀与主办部门下拉复用
    for old_id, meta in dept_meta.items():
        new_id = meta.get("new_id")
        if not new_id:
            continue
        ncur.execute(
            "UPDATE departments SET xuhaotou=%s, dnnum=%s, zg=%s WHERE id=%s",
            (meta.get("xuhaotou"), meta.get("dnnum") or 0, meta.get("zg") or "", int(new_id)),
        )
    nconn.commit()
    # 反向清空(子表先删)
    for new_table, *_ in reversed(TABLES):
        ncur.execute(f"TRUNCATE TABLE `{new_table}`")
    nconn.commit()

    for new_table, _old, _fields, pk, _ai in TABLES:
        fields, rows = prepared[new_table]
        if not rows:
            print(f"  {new_table}: 0 条")
            continue
        placeholders = ", ".join(["%s"] * len(fields))
        sql = (f"INSERT INTO `{new_table}` (" + ", ".join(f"`{c}`" for c in fields)
               + f") VALUES ({placeholders})")
        batch = []
        for r in rows:
            batch.append(tuple(r))
            if len(batch) >= 1000:
                ncur.executemany(sql, batch)
                batch = []
        if batch:
            ncur.executemany(sql, batch)
        nconn.commit()
        pk_i = fields.index(pk)
        max_id = max((r[pk_i] for r in rows if r[pk_i] is not None), default=0)
        if max_id:
            ncur.execute(f"ALTER TABLE `{new_table}` AUTO_INCREMENT = {max_id + 1}")
            nconn.commit()
        print(f"  {new_table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")

    # 开关表默认关闭(存在则保留现值,不存在则补两条)
    for name in ("锁定营业所计划", "jhsshz浏览锁定"):
        ncur.execute("SELECT id FROM consol_tb WHERE conName=%s", (name,))
        if ncur.fetchone() is None:
            ncur.execute(
                "INSERT INTO consol_tb (conName, val, intval) VALUES (%s, 0, NULL)", (name,)
            )
    nconn.commit()
    nconn.close()
    ocur.close()
    print("导入完成")


if __name__ == "__main__":
    main()
