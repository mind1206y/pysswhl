"""水费系统历史数据导入:旧库 shuifeixitong/_biandong/_quxiao/_log → 新库同名表。

按 docs/数据迁移约定.md:表名/字段沿用旧库,保留旧主键 id,可重复执行(TRUNCATE 重导)。
日期转换:旧系统优惠起止实际存于 *T 字符串列("年月"文本),新系统为正规日期列——
导入时统一从 T 列解析(支持 YYYYMM/YYYY-MM/YYYY.M/YYYY年MM月 等),解析失败的行
记录到 scripts/migration_reports/waterfee_date_errors.csv,表内该字段置 NULL。

用法(backend 目录下):
    python -m scripts.import_water_fee            # 全量导入四张表
    python -m scripts.import_water_fee --dry-run  # 只统计
    python -m scripts.import_water_fee --nd 2026  # 只导主表指定年度(调试用)

旧库连接参数同 import_projects.py(环境变量 OLD_DB_*)。
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"

MAIN_FIELDS = [
    "id", "shi", "quxian", "xiangzhen", "cun", "shixiang", "xingming", "sfz",
    "juzhudizhi", "dianhua", "kaihuming", "yinhangzhanghao", "kaihuhang",
    "kaihushenfenzheng", "yinhangbeizhu", "tekunlei", "gongyangfangshi",
    "gongyangjigou", "bm", "caozuo", "caozuoriqi", "yonghuhao", "qitayongshui",
    "beizhu", "shouliriqi", "daoruqingkuang", "fanhuiminzhengju", "guitaishouli",
    "nd", "bmid", "yueshu", "biaoming", "wenjianxuhao", "quxiaoriqi",
]
MAIN_DATES = {"ksbriqi": "ksbriqiT", "jsbriqi": "jsbriqiT",
              "youhuiksriqi": "youhuiksriqiT", "youhuijsriqi": "youhuijsriqiT"}

BIANDONG_FIELDS = [
    "id", "zhuid", "biandongriqi", "yonghuhao", "qitayongshui", "beizhu",
    "wushuifeihetui", "daoruqingkuang", "fanhuiminzhengju", "guitaishouli",
    "yueshu", "caozuo", "shoulishijian", "juzhudizhi",
]
BIANDONG_DATES = {"youhuiksriqi": "youhuiksriqiT", "youhuijsriqi": "youhuijsriqiT"}

QUXIAO_FIELDS = [
    "id", "shi", "quxian", "xiangzhen", "cun", "shixiang", "xingming", "sfz",
    "juzhudizhi", "dianhua", "kaihuming", "yinhangzhanghao", "kaihuhang",
    "kaihushenfenzheng", "yinhangbeizhu", "tekunlei", "gongyangfangshi",
    "gongyangjigou", "bm", "caozuo", "caozuoriqi", "yonghuhao", "qitayongshui",
    "beizhu", "shouliriqi", "daoruqingkuang", "fanhuiminzhengju", "guitaishouli",
    "nd", "bmid", "yueshu", "biaoming", "wenjianxuhao",
    "quxiaoyuanyin", "quxiaoren", "quxiaoriqi", "yuanyinid",
    "quxiaoshenheren", "quxiaoshenheshijian", "quxiaozhuangtai",
]
QUXIAO_DATES = {"ksbriqi": "ksbriqiT", "jsbriqi": "jsbriqiT",
                "youhuiksriqi": "youhuiksriqiT", "youhuijsriqi": "youhuijsriqiT"}

LOG_FIELDS = ["id", "main_id", "field_name", "old_value", "new_value",
              "update_user", "update_time", "source"]

DATE_PARSE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y%m", "%Y-%m", "%Y.%m", "%Y年%m月", "%Y年%m", "%Y"]


def parse_date(text):
    if text in (None, ""):
        return None
    if hasattr(text, "year"):
        return text
    s = str(text).strip()
    for fmt in DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return "__FAIL__"


class DateErrorReport:
    def __init__(self):
        REPORT_DIR.mkdir(exist_ok=True)
        self.f = open(REPORT_DIR / "waterfee_date_errors.csv", "w", newline="", encoding="utf-8-sig")
        self.w = csv.writer(self.f)
        self.w.writerow(["表", "记录id", "字段", "原值", "原因"])
        self.count = 0

    def add(self, table, rid, field, raw):
        self.w.writerow([table, rid, field, str(raw), "无法解析为日期,已置空"])
        self.count += 1

    def close(self):
        self.f.close()
        print(f"日期解析失败 {self.count} 处,明细见 {REPORT_DIR / 'waterfee_date_errors.csv'}")


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def fetch_table(cur, table, fields, dates, where="", report=None):
    """读取一张表:普通字段直取,日期字段从旧 T 字符串列解析。"""
    tcols = list(dates.values())
    cur.execute(f"SELECT {', '.join(fields)}, {', '.join(tcols)} FROM {table}{where} ORDER BY id")
    out_fields = list(fields) + list(dates.keys())
    rows = []
    for r in cur.fetchall():
        rec = {}
        for i, f in enumerate(fields):
            v = r[i]
            rec[f] = int(v) if isinstance(v, bool) else v
        for j, (field, _tcol) in enumerate(dates.items()):
            raw = r[len(fields) + j]
            parsed = parse_date(raw)
            if parsed == "__FAIL__":
                if report:
                    report.add(table, rec["id"], field, raw)
                rec[field] = None
            else:
                rec[field] = parsed
        rows.append(tuple(rec.values()))
    return rows, out_fields

def build_bmid_map(ocur, ncur):
    """旧 bb_bumen.id → 新 departments.id(按部门名精确匹配;找不到为 None)。

    旧库迁移进来的 bmid 是 bb_bumen.id,与新 departments.id 不对应
    (如旧 7=海沧营业所,新 7=售水事业部),写入前必须重映射。
    """
    ocur.execute("SELECT id, bm FROM bb_bumen")
    old = dict(ocur.fetchall())
    ncur.execute("SELECT id, name FROM departments")
    by_name = {name: i for i, name in ncur.fetchall()}
    return {oid: by_name.get(name) for oid, name in old.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--nd", type=int, help="只导主表指定年度(调试用)")
    args = parser.parse_args()

    conn = old_conn()
    report = DateErrorReport()
    tables = {}
    try:
        cur = conn.cursor()
        where = f" WHERE nd = {args.nd}" if args.nd else ""
        tables["shuifeixitong"] = fetch_table(cur, "shuifeixitong", MAIN_FIELDS, MAIN_DATES, where, report)
        tables["shuifeixitongbiandong"] = fetch_table(cur, "shuifeixitongbiandong", BIANDONG_FIELDS, BIANDONG_DATES, "", report)
        tables["shuifeixitongquxiao"] = fetch_table(cur, "shuifeixitongquxiao", QUXIAO_FIELDS, QUXIAO_DATES, "", report)
        cur.execute(f"SELECT {', '.join(LOG_FIELDS)} FROM shuifeixitong_log ORDER BY id")
        tables["shuifeixitong_log"] = ([tuple(r) for r in cur.fetchall()], LOG_FIELDS)

        for t, (rows, _f) in tables.items():
            print(f"{t}: 旧库 {len(rows)} 条")

        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            # bmid 重映射:旧 bb_bumen.id → 新 departments.id(按部门名)
            bmid_map = build_bmid_map(cur, ncur)
            for t in ("shuifeixitong", "shuifeixitongquxiao"):
                rows, fields = tables[t]
                idx = fields.index("bmid")
                missing = set()
                fixed = []
                for r in rows:
                    lst = list(r)
                    v = lst[idx]
                    if v is not None:
                        lst[idx] = bmid_map.get(v)
                        if lst[idx] is None:
                            missing.add(v)
                    fixed.append(tuple(lst))
                tables[t] = (fixed, fields)
                if missing:
                    print(f"⚠ {t} 旧 bmid {sorted(missing)} 在新 departments 无同名部门,已置空")
            for t, (rows, fields) in tables.items():
                ncur.execute(f"TRUNCATE TABLE {t}")
                if rows:
                    ph = ", ".join(["%s"] * len(fields))
                    ncur.executemany(f"INSERT INTO {t} ({', '.join(fields)}) VALUES ({ph})", rows)
                    ncur.execute(f"ALTER TABLE {t} AUTO_INCREMENT = {max(r[0] for r in rows) + 1}")
                    print(f"{t}: 已导入 {len(rows)} 条,自增起点 {max(r[0] for r in rows) + 1}")
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()
        report.close()


if __name__ == "__main__":
    main()
    print("完成")
