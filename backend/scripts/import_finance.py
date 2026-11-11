"""财务管理三模块历史数据导入:旧库 db_plan.dbo.{zc_*,wzcgsq*} → 新库同名表。

照 docs/数据迁移约定.md:
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点;可重复执行(逐表 TRUNCATE 重导)
- **bmid 必须重映射**:旧 bb_bumen.id 与新 departments.id 不对应且数字会撞车,
  一律读 migration_reports/department_map.json 的 bmid_map(⛔勿按名称现算)
- wzcgsq.userid 按 user_map.json 映射(新库只有 3 个账号,未匹配的置 NULL,
  归属判定回退按 username 文本,照旧 IsOwner)
- SQL Server datetime 精度 1/300 秒,统一截断微秒,避免 MySQL DATETIME(0) 四舍五入进 1 秒
- 只 TRUNCATE 本模块的 7 张新表,不触碰任何其它模块的表

用法(backend 目录下):
    python -m scripts.import_finance --dry-run
    python -m scripts.import_finance

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pymysql

from app.core.config import settings
from scripts.import_vehicles import fetch_all, old_conn, write_table

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"

ZC_LB = ["id", "lb"]
ZC_ND = ["id", "nd"]
ZC_CW = [
    "id", "lbid", "zccode", "sbname", "num", "bmid", "qyrq", "yz", "jz",
    "didian", "nd", "guige", "sbbh", "yujishiyong", "yishiyong", "beizhu",
    "beizhuren", "bzdate", "pandian", "baofeidanid", "baofeiqk", "baofeicztime",
]
ZC_BAOF = ["id", "riqi", "bmid", "caozuo", "czriqi", "zaiyao"]
ZC_BFTP = ["id", "dizhi", "bfdid"]
WZ_MAIN = ["id", "bumen", "sgyy", "hj", "cj", "djriqi", "username", "userid", "bmid"]
WZ_MX = [
    "id", "mainid", "wpmc", "ggxh", "danwei", "shuliang", "danjia", "xiaoji",
    "ysqk", "beizhu",
]

# (旧表名, 字段, 需要重映射的列下标: bmid / userid)
TABLES = [
    ("zc_lb", ZC_LB, None, None),
    ("zc_nd", ZC_ND, None, None),
    ("zc_cw", ZC_CW, ZC_CW.index("bmid"), None),
    ("zc_baofeidan", ZC_BAOF, ZC_BAOF.index("bmid"), None),
    ("zc_baofeitp", ZC_BFTP, None, None),
    ("wzcgsq", WZ_MAIN, WZ_MAIN.index("bmid"), WZ_MAIN.index("userid")),
    ("wzcgsq_mx", WZ_MX, None, None),
]


def _normalize(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        # nchar(10) 定长列(pandian)与 varchar 的尾空格,写 MySQL 前统一去掉
        return value.rstrip()
    return value


def load_maps():
    dept = json.loads((REPORT_DIR / "department_map.json").read_text(encoding="utf-8"))
    user = json.loads((REPORT_DIR / "user_map.json").read_text(encoding="utf-8"))
    return (
        {int(k): (int(v) if v else None) for k, v in dept["bmid_map"].items()},
        {int(k): int(v) for k, v in user["user_map"].items()},
    )


def remap(rows, bmid_idx, userid_idx, bmid_map, user_map):
    """逐行一次性重映射(禁止逐条 UPDATE 循环,会链式污染)。"""
    out = []
    missing_bm, missing_user = set(), set()
    for row in rows:
        r = list(row)
        if bmid_idx is not None:
            old = r[bmid_idx]
            if old is not None and int(old) not in bmid_map:
                missing_bm.add(int(old))
            r[bmid_idx] = bmid_map.get(int(old)) if old is not None else None
        if userid_idx is not None:
            old = r[userid_idx]
            if old is not None and int(old) not in user_map:
                missing_user.add(int(old))
            r[userid_idx] = user_map.get(int(old)) if old is not None else None
        out.append(tuple(_normalize(v) for v in r))
    if missing_bm:
        print(f"  ⚠ 未映射的旧 bmid: {sorted(missing_bm)}(置 NULL)")
    if missing_user:
        print(f"  ⚠ 未映射的旧 userid: {sorted(missing_user)}(置 NULL,归属按 username 回退)")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    bmid_map, user_map = load_maps()
    conn = old_conn()
    try:
        ocur = conn.cursor()
        data = {}
        for table, fields, bidx, uidx in TABLES:
            rows = fetch_all(ocur, table, fields)
            data[table] = remap(rows, bidx, uidx, bmid_map, user_map)

        # 旧库基线(金额是 float,合计本身有精度误差,新库用 0.01 容差核对)
        yz_i, jz_i = ZC_CW.index("yz"), ZC_CW.index("jz")
        old_yz = sum((r[yz_i] or 0) for r in data["zc_cw"])
        old_jz = sum((r[jz_i] or 0) for r in data["zc_cw"])
        hj_i = WZ_MAIN.index("hj")
        old_hj = sum(float(r[hj_i] or 0) for r in data["wzcgsq"])
        print(f"  旧库基线: zc_cw={len(data['zc_cw'])} SUM(yz)={old_yz:.2f} "
              f"SUM(jz)={old_jz:.2f}; wzcgsq={len(data['wzcgsq'])} SUM(hj)={old_hj:.2f}")
        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            for table, fields, _bidx, _uidx in TABLES:
                write_table(ncur, table, fields, data[table])
            new.commit()

            for table, _fields, _bidx, _uidx in TABLES:
                ncur.execute(f"SELECT COUNT(*) FROM `{table}`")
                got = ncur.fetchone()[0]
                if got != len(data[table]):
                    raise SystemExit(f"迁移校验失败:{table} 行数 {got} != {len(data[table])}")
            ncur.execute("SELECT COALESCE(SUM(yz),0), COALESCE(SUM(jz),0) FROM zc_cw")
            yz, jz = (float(v) for v in ncur.fetchone())
            ncur.execute("SELECT COALESCE(SUM(hj),0) FROM wzcgsq")
            hj = float(ncur.fetchone()[0])
            if abs(yz - old_yz) > 0.01 or abs(jz - old_jz) > 0.01 or abs(hj - old_hj) > 0.01:
                raise SystemExit(
                    f"迁移校验失败:金额合计不一致 新({yz:.2f},{jz:.2f},{hj:.2f}) "
                    f"旧({old_yz:.2f},{old_jz:.2f},{old_hj:.2f})"
                )
            print(f"  校验通过:7 表行数一致, SUM(yz/jz/hj) = {yz:.2f}/{jz:.2f}/{hj:.2f}")
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
