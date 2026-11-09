"""工单材料库历史数据导入:旧库 db_plan.dbo.* -> 新库。

- material_library(695) / in_stock_record(1020) / material_record(31194)
  / material_image(236) / work_order(10976,材料库出库关联用,完整工单模块后续复刻共用)
- 全部保留旧主键 id,导入后调整自增起点
- bmid(material_library / work_order)按 migration_reports/department_map.json
  重映射到新 departments.id;映射不到时置 NULL 并告警
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run
- 历史图片物理文件在旧生产服务器 /Upload/MaterialImages/,接口缺文件返回 404 提示

用法(backend 目录下):
    python -m scripts.import_materials --dry-run
    python -m scripts.import_materials
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"

# (旧字段, 新列名);bmid 字段下标在各自元组第二项
MATLIB_MAP = [
    ("Id", "id"), ("MaterialName", "material_name"), ("Spec", "spec"),
    ("Remark", "remark"), ("num", "num"), ("Unit", "unit"), ("biaoji", "biaoji"),
    ("yujing", "yujing"), ("dakoujing", "dakoujing"), ("Model", "model"),
    ("lastdanjia", "lastdanjia"), ("bmid", "bmid"),
    ("Alias1", "alias1"), ("Alias2", "alias2"), ("Alias3", "alias3"),
]
INSTOCK_MAP = [
    ("Id", "id"), ("MaterialId", "material_id"), ("Quantity", "quantity"),
    ("Operator", "operator"), ("InStockTime", "in_stock_time"), ("Remark", "remark"),
    ("lei", "lei"), ("LingliaoDetailId", "lingliao_detail_id"),
]
MATREC_MAP = [
    ("Id", "id"), ("WorkOrderId", "work_order_id"), ("Receiver", "receiver"),
    ("MaterialId", "material_id"), ("Quantity", "quantity"),
    ("CreateTime", "create_time"), ("Status", "status"), ("ReceiveTime", "receive_time"),
]
MATIMG_MAP = [
    ("Id", "id"), ("MaterialId", "material_id"), ("FileName", "file_name"),
    ("FilePath", "file_path"), ("FileSize", "file_size"), ("ThumbPath", "thumb_path"),
    ("remark", "remark"), ("CreateTime", "create_time"),
]
WORKORDER_MAP = [
    ("Id", "id"), ("WorkOrderNo", "work_order_no"), ("Creator", "creator"),
    ("CreateTime", "create_time"), ("Remark", "remark"), ("banzu", "banzu"),
    ("WkCreateTime", "wk_create_time"), ("beizhu", "beizhu"), ("editor", "editor"),
    ("edittime", "edittime"), ("bmid", "bmid"), ("IsUsed", "is_used"),
    ("lingliaotype", "lingliaotype"),
]

# 旧表名 -> (新表名, 字段映射, 含 bmid 的下标, 是否重置自增)
TABLES = {
    "MaterialLibrary": ("material_library", MATLIB_MAP, {11}, True),
    "InStockRecord": ("in_stock_record", INSTOCK_MAP, set(), True),
    "WorkOrder": ("work_order", WORKORDER_MAP, {10}, True),
    "MaterialRecord": ("material_record", MATREC_MAP, set(), True),
    "MaterialImage": ("material_image", MATIMG_MAP, set(), True),
}


def old_conn():
    import os

    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def load_bmid_map() -> dict:
    if not MAP_FILE.exists():
        raise SystemExit(
            f"缺少部门映射文件 {MAP_FILE},请先运行 python -m scripts.import_departments"
        )
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
        for old_table, (_new_table, field_map, bmid_idx, _ai) in TABLES.items():
            old_fields = [f for f, _n in field_map]
            ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in old_fields)} FROM [{old_table}]")
            rows = [list(r) for r in ocur.fetchall()]
            print(f"  {old_table}: 旧库 {len(rows)} 条")
            for rec in rows:
                for i in bmid_idx:
                    v = rec[i]
                    if v is None:
                        rec[i] = None
                        continue
                    new_bmid = bmid_map.get(int(v))
                    if new_bmid is None:
                        missing[v] += 1
                    rec[i] = new_bmid
            data[old_table] = rows
    finally:
        oc.close()

    total_recs = sum(len(rows) for rows in data.values())
    mapped_recs = total_recs - sum(missing.values())
    print(f"  bmid 映射: {mapped_recs}/{total_recs} 条有映射")
    if missing:
        print(f"  未映射旧 bmid: {dict(missing)} (对应记录 bmid 置 NULL)")

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        ncur = new.cursor()
        for old_table, (new_table, field_map, _bmid_idx, auto_inc) in TABLES.items():
            rows = data[old_table]
            new_fields = [n for _o, n in field_map]
            ncur.execute(f"TRUNCATE TABLE `{new_table}`")
            sql = (
                f"INSERT INTO `{new_table}` (" + ", ".join(f"`{c}`" for c in new_fields)
                + f") VALUES ({', '.join(['%s'] * len(new_fields))})"
            )
            batch = []
            for rec in rows:
                batch.append(tuple(rec))
                if len(batch) >= 1000:
                    ncur.executemany(sql, batch)
                    batch = []
            if batch:
                ncur.executemany(sql, batch)
            max_id = max((r[0] for r in rows), default=0)
            if auto_inc and max_id:
                ncur.execute(f"ALTER TABLE `{new_table}` AUTO_INCREMENT = {max_id + 1}")
            print(f"  {new_table}: 写入 {len(rows)} 条"
                  + (f",自增起点 {max_id + 1}" if auto_inc and max_id else ""))
        new.commit()
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
