"""工单领料模块历史数据导入:旧库 db_plan.dbo.* -> 新库。

⛔ 只导本模块缺的两张表,**不重导已迁移的 work_order / material_record / material_library /
in_stock_record / material_image / qiangxiurenyuan**(分别由 import_materials.py 与
import_roadrepair.py 负责;重导会清掉材料库与路面修复模块的新数据)。

- gongdancailiao(19689):工单材料登记。旧系统列表的「已领用」= EXISTS(gongdanhao=WorkOrderNo),
  WorkOrder.IsUsed 是死列;整表导入只为还原该判定,后续 Gongdan 模块复刻时直接复用此表。
- WorkOrder_attachment(旧库 0 条):工单附件,导入只为幂等对齐(历史物理文件也不存在)。
- 全部保留旧主键 id,导入后调整自增起点;bmid 按 department_map.json 重映射,无映射置 NULL+告警。
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_workorder --dry-run
    python -m scripts.import_workorder
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

GDC_MAP = [
    ("id", "id"), ("ksriqi", "ksriqi"), ("jsriqi", "jsriqi"),
    ("shijian", "shijian"), ("dizhi", "dizhi"), ("neirong", "neirong"),
    ("caizhi", "caizhi"), ("guanjing", "guanjing"), ("gongdanhao", "gongdanhao"),
    ("tingshui", "tingshui"), ("shuiliang", "shuiliang"), ("cailiao", "cailiao"),
    ("shuliang", "shuliang"), ("qiangxiurenyuan", "qiangxiurenyuan"),
    ("djriqi", "djriqi"), ("zuihouriqi", "zuihouriqi"), ("djren", "djren"),
    ("pipesize", "pipesize"), ("beizhu", "beizhu"), ("bmid", "bmid"),
]
ATT_MAP = [
    ("id", "id"), ("workorderid", "workorderid"), ("filename", "filename"),
    ("filepath", "filepath"), ("filesize", "filesize"),
    ("uploadtime", "uploadtime"), ("operator_name", "operator_name"),
]

# 旧表名 -> (新表名, 字段映射, bmid 下标集合)
TABLES = {
    "gongdancailiao": ("gongdancailiao", GDC_MAP, {19}),
    "WorkOrder_attachment": ("work_order_attachment", ATT_MAP, set()),
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
        # 旧库「已领用」工单数,导入后新库应一致
        ocur.execute("SELECT COUNT(*) FROM WorkOrder w WHERE EXISTS "
                     "(SELECT 1 FROM gongdancailiao g WHERE g.gongdanhao = w.WorkOrderNo)")
        old_used = ocur.fetchone()[0]
        print(f"  旧库已领用工单数(EXISTS 判定): {old_used}")
    finally:
        oc.close()

    rows = data["gongdancailiao"]
    for rec in rows:
        v = rec[19]
        if v is None:
            continue
        new_bmid = bmid_map.get(int(v))
        if new_bmid is None:
            missing[v] += 1
        rec[19] = new_bmid
    print(f"  gongdancailiao.bmid 映射: {len(rows) - sum(missing.values())}/{len(rows)} 条有映射")
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
        ncur.execute("SELECT COUNT(*) FROM work_order w WHERE EXISTS "
                     "(SELECT 1 FROM gongdancailiao g WHERE g.gongdanhao = w.work_order_no)")
        new_used = ncur.fetchone()[0]
        print(f"  新库已领用工单数: {new_used} (旧库 {old_used},"
              f"{'一致 ✓' if new_used == old_used else '不一致 ✗ 请检查'})")
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
