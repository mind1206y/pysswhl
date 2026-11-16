"""通用增量补数:把旧库 SQL Server 里「新库缺失的行」补进新库 MySQL。

设计原则(比逐个重跑 import_xxx.py 更安全):
  * 只 INSERT 不存在的行,**不 TRUNCATE、不 DELETE、不 UPDATE 已有行**
    —— 新系统测试期录入的数据、脚本补过的字典项都不会被冲掉;
  * 按主键判定存在性(无自增主键的表按全部列比对);
  * 列名按小写匹配,另加固有映射(旧 MaterialId -> 新 material_id);
  * 旧库独有列(如 shuifeixitong.ksbriqiT 这类派生列)自动跳过;
  * 新库独有列(如 jh_ssdb.zhuanguan_name 这类展示冗余列)留空,
    由后置回填脚本按 users 表补名字;
  * bit -> 1/0,datetime/date/decimal/bytes 统一转字面量。

用法(backend 目录下):
    python -m scripts.sync_missing_rows --dry-run     # 只看每张表要补多少
    python -m scripts.sync_missing_rows               # 实际写入
    python -m scripts.sync_missing_rows --only jiaban,gongdancailiao
"""

import argparse
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"

# 旧列名 -> 新列名(小写后仍对不上时才需要写这里)
SPECIAL_COLMAP = {
    "lingliaodetail": {"MaterialId": "material_id"},
    "gongdan_neirong_dict": {"Id": "id"},
    "gongdan_caizhi_dict": {"Id": "id"},
}

# 没有自增主键的表:按全部列比对,不做 id 判定
NO_AI_TABLES = {"ip_net_creator"}

# 已知「新库比旧库多」的表——补数只处理缺口,这些表默认跳过(不删新库数据)
SKIP_IF_NEW_MORE = True


def old_conn():
    import os

    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=15,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )


def lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, Decimal)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.strftime("%Y-%m-%d") + "'"
    if isinstance(v, timedelta):
        total = int(v.total_seconds())
        sign = "-" if total < 0 else ""
        total = abs(total)
        return f"'{sign}{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}'"
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex() if v else "''"
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return "'" + s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "\\0") + "'"


def table_columns(ocur, ncur, table):
    """返回 (旧列顺序, [(新列名, 是否必填无默认)], 列映射 旧名->新名 或 None 表示跳过)。"""
    ocur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION",
        (table,),
    )
    old_cols = [r[0] for r in ocur.fetchall()]
    ncur.execute(
        "SELECT column_name, is_nullable, column_default, extra FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (settings.DB_NAME, table),
    )
    new_meta = {r[0].lower(): r for r in ncur.fetchall()}
    special = {k.lower(): v for k, v in SPECIAL_COLMAP.get(table, {}).items()}
    mapping = {}
    for oc in old_cols:
        low = oc.lower()
        if low in special:
            if special[low].lower() in new_meta:
                mapping[oc] = special[low]
            continue
        if low in new_meta:
            mapping[oc] = new_meta[low][0]
            continue
        # 去掉下划线再匹配一次(应对 MaterialId / material_id 这类)
        cand = low.replace("_", "")
        hit = [v[0] for k, v in new_meta.items() if k.replace("_", "") == cand]
        if len(hit) == 1:
            mapping[oc] = hit[0]
    return old_cols, new_meta, mapping


def process(table, ocur, ncur, dry_run):
    old_cols, new_meta, mapping = table_columns(ocur, ncur, table)
    usable = [c for c in old_cols if c in mapping]
    if not usable:
        return {"table": table, "skip": "无可对应列"}
    new_names = [mapping[c] for c in usable]
    has_ai = any(r[3] == "auto_increment" for r in new_meta.values())

    ocor_sql = f"SELECT {', '.join('[' + c + ']' for c in usable)} FROM [{table}]"
    ocur.execute(ocor_sql)
    old_rows = ocur.fetchall()

    # 新库现有键集合
    if has_ai and "id" in new_meta:
        ncur.execute(f"SELECT `id` FROM `{table}`")
        existing = {r[0] for r in ncur.fetchall()}
        key_idx = next(i for i, c in enumerate(usable) if mapping[c].lower() == "id")
        missing = [r for r in old_rows if r[key_idx] not in existing]
    else:
        ncur.execute(f"SELECT {', '.join('`' + n + '`' for n in new_names)} FROM `{table}`")
        existing = {tuple(r) for r in ncur.fetchall()}
        missing = [r for r in old_rows if tuple(r) not in existing]

    info = {"table": table, "old": len(old_rows), "new": len(existing),
            "to_add": len(missing), "cols": len(usable),
            "skipped_old_cols": [c for c in old_cols if c not in mapping],
            "filled_new_cols": [r[0] for k, r in new_meta.items()
                                if k not in {mapping[c].lower() for c in usable}]}
    if dry_run or not missing:
        return info

    insert_sql = (f"INSERT INTO `{table}` ({', '.join('`' + n + '`' for n in new_names)}) VALUES "
                  + "(" + ", ".join(["%s"] * len(new_names)) + ")")
    rows = [tuple(r) + (None,) * (len(usable) - len(r)) for r in missing]
    ncur.executemany(insert_sql, rows)
    info["added"] = len(rows)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔,只处理这些表")
    args = ap.parse_args()

    oc, nc = old_conn(), new_conn()
    report = {"at": datetime.now().isoformat(timespec="seconds"), "tables": []}
    try:
        ocur, ncur = oc.cursor(), nc.cursor()
        ocur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
        old_tables = [r[0] for r in ocur.fetchall()]
        ncur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (settings.DB_NAME,))
        new_set = {r[0].lower() for r in ncur.fetchall()}

        only = [t.strip().lower() for t in args.only.split(",") if t.strip()]
        total = 0
        for t in old_tables:
            if t.lower() not in new_set:
                continue
            if only and t.lower() not in only:
                continue
            ocur.execute(f"SELECT COUNT(*) FROM [{t}]")
            o = ocur.fetchone()[0]
            ncur.execute(f"SELECT COUNT(*) FROM `{t}`")
            n = ncur.fetchone()[0]
            if o <= n and SKIP_IF_NEW_MORE:
                if o < n:
                    print(f"  - {t:30s} 新库多 {n - o} 行,跳过(不删数据)")
                continue
            try:
                info = process(t, ocur, ncur, args.dry_run)
            except Exception as exc:  # 单表失败不影响其余表
                print(f"  ! {t:30s} 失败: {exc}")
                report["tables"].append({"table": t, "error": str(exc)})
                nc.rollback()
                continue
            report["tables"].append(info)
            if info.get("to_add"):
                total += info["to_add"]
                print(f"  + {t:30s} 旧 {info['old']:6d} 新 {info['new']:6d} 补 {info['to_add']:6d}"
                      f"{' (已写入)' if not args.dry_run else ''}")
            if not args.dry_run:
                nc.commit()
        print(f"\n合计{'预计' if args.dry_run else '实际'}补入 {total} 行")
    finally:
        oc.close()
        nc.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "dryrun" if args.dry_run else "applied"
    out = REPORT_DIR / f"sync_missing_{tag}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {out}")


if __name__ == "__main__":
    main()
