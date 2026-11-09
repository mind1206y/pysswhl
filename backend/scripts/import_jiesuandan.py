"""领料结算历史数据导入:旧库 db_plan.dbo.* -> 新库。

- jiesuancailiao   结算单主表(bmid 按 department_map.json 重映射)
- jiesuandetail    结算明细(保留旧 id,引用旧 lingliaodetail.id)
- cailiao_fujian   结算单附件(旧文件在旧生产服务器 Uploads/Jiesuan/,新库仅保留记录)

可重复执行(逐表 TRUNCATE 重导),支持 --dry-run。

用法(backend 目录下):
    python -m scripts.import_jiesuandan --dry-run
    python -m scripts.import_jiesuandan
"""

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"
OLD_SITE_DIR = Path(os.environ.get("OLD_SITE_DIR", r"E:\sswhl\sswhl"))
UPLOAD_ROOT = Path(settings.UPLOAD_DIR)

MAIN_MAP = [
    ("id", "id"), ("jiesuandanno", "jiesuandanno"), ("gongyingshang", "gongyingshang"),
    ("jiesuanriqi", "jiesuanriqi"), ("zonge", "zonge"), ("shzt", "shzt"),
    ("shriqi", "shriqi"), ("shren", "shren"), ("createuser", "createuser"),
    ("bmid", "bmid"), ("beizhu", "beizhu"),
]
DETAIL_MAP = [
    ("id", "id"), ("jiesuanid", "jiesuanid"),
    ("lingliaodetailid", "lingliaodetailid"), ("num", "num"),
    ("danjia", "danjia"), ("jine", "jine"),
]
FILE_MAP = [
    ("id", "id"), ("jiesuancailiao_id", "jiesuancailiao_id"),
    ("filename", "filename"), ("filepath", "filepath"), ("filesize", "filesize"),
    ("uploaduser", "uploaduser"), ("uploadtime", "uploadtime"),
]

# 旧表名 -> (新表名, 字段映射, bmid 下标)
TABLES = {
    "jiesuancailiao": ("jiesuancailiao", MAIN_MAP, 9),
    "jiesuandetail": ("jiesuandetail", DETAIL_MAP, None),
    "cailiao_fujian": ("cailiao_fujian", FILE_MAP, None),
}


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def load_bmid_map() -> dict:
    if not MAP_FILE.exists():
        raise SystemExit(f"缺少部门映射文件 {MAP_FILE},请先运行 python -m scripts.import_departments")
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in data.get("bmid_map", {}).items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()
    bmid_map = load_bmid_map()
    missing = Counter()

    oc = old_conn()
    data = {}
    try:
        ocur = oc.cursor()
        for old_table, (_new, field_map, _bmid_idx) in TABLES.items():
            fields = [f for f, _n in field_map]
            ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{old_table}]")
            data[old_table] = [list(r) for r in ocur.fetchall()]
            print(f"  {old_table}: 旧库 {len(data[old_table])} 条")
    finally:
        oc.close()

    rows = data["jiesuancailiao"]
    for rec in rows:
        value = rec[9]
        if value is None:
            continue
        new_bmid = bmid_map.get(int(value))
        if new_bmid is None:
            missing[value] += 1
        rec[9] = new_bmid
    print(f"  jiesuancailiao.bmid 映射: {len(rows) - sum(missing.values())}/{len(rows)} 条有映射")
    if missing:
        print(f"  未映射旧 bmid: {dict(missing)} (对应记录 bmid 置 NULL)")

    # 附件:旧路径 /Uploads/Jiesuan/... 或 /Upload/Jiesuan/... -> 新 UPLOAD_DIR/Jiesuan/...
    copied = 0
    missing_files = 0
    for rec in data["cailiao_fujian"]:
        old_path = (rec[3] or "").replace("\\", "/")
        rel = old_path
        for prefix in ("/Uploads/", "/Upload/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        rel = rel.lstrip("/")
        if not rel.lower().startswith("jiesuan/"):
            rel = "Jiesuan/" + rel
        rec[3] = rel
        src = OLD_SITE_DIR / old_path.lstrip("/")
        dest = UPLOAD_ROOT / rel
        if old_path and src.is_file():
            if not args.dry_run and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            copied += 1
        else:
            missing_files += 1
    print(f"  cailiao_fujian 附件文件: 可复制 {copied} / 缺失 {missing_files}"
          f"(源目录 {OLD_SITE_DIR})")

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        ncur = new.cursor()
        for old_table, (new_table, field_map, _bmid_idx) in TABLES.items():
            rows = data[old_table]
            fields = [n for _o, n in field_map]
            ncur.execute(f"TRUNCATE TABLE `{new_table}`")
            sql = (
                f"INSERT INTO `{new_table}` (" + ", ".join(f"`{c}`" for c in fields)
                + f") VALUES ({', '.join(['%s'] * len(fields))})"
            )
            batch = []
            for rec in rows:
                batch.append(tuple(rec))
                if len(batch) >= 500:
                    ncur.executemany(sql, batch)
                    batch = []
            if batch:
                ncur.executemany(sql, batch)
            max_id = max((r[0] for r in rows), default=0)
            if max_id:
                ncur.execute(f"ALTER TABLE `{new_table}` AUTO_INCREMENT = {max_id + 1}")
            print(f"  {new_table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")
        new.commit()
        ncur.execute("SELECT COUNT(*), COALESCE(SUM(zonge),0) FROM jiesuancailiao")
        print("  新库 jiesuancailiao:", ncur.fetchone())
        ncur.execute("SELECT COUNT(*), COALESCE(SUM(jine),0) FROM jiesuandetail")
        print("  新库 jiesuandetail:", ncur.fetchone())
    except pymysql.err.ProgrammingError as exc:
        raise SystemExit(
            "目标表不存在,请先运行 python -m scripts.init_db 建表。"
            f"\n原始错误: {exc}"
        )
    finally:
        new.close()
    print("完成")


if __name__ == "__main__":
    main()
