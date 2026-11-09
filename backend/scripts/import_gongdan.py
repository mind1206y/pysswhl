"""工单信息录入 Gongdan 模块历史数据导入:旧库 db_plan.dbo.* -> 新库。

⛔ 只导本模块新增的 3 张表,**不碰已迁移的 gongdancailiao / qiangxiurenyuan /
work_order / material_record / material_library**(分别由 import_workorder.py、
import_roadrepair.py、import_materials.py 负责;重导会清掉其它模块的新数据)。

- gongdan(76870)               热线工单本地镜像,仅作数据保全与计数(⛔不与内网 flow 工单混用)
- gongdan_neirong_dict(72)     工作内容下拉字典
- gongdan_caizhi_dict(21)      材质下拉字典
- 全部保留旧主键 id,导入后调整自增起点;这 3 张表均无 bmid 字段,无需部门映射
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_gongdan --dry-run
    python -m scripts.import_gongdan
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"

# 旧表名 -> (新表名, [(旧列, 新列), ...])
TABLES = {
    "gongdan": ("gongdan", [
        ("id", "id"), ("gongdanid", "gongdanid"),
        ("chuangjiandanwei", "chuangjiandanwei"), ("shouliren", "shouliren"),
        ("diaodupingtai", "diaodupingtai"), ("chuangjianriqi", "chuangjianriqi"),
        ("laidianhao", "laidianhao"), ("lianxidianhua", "lianxidianhua"),
        ("leixing", "leixing"), ("zileixing", "zileixing"), ("jinji", "jinji"),
        ("chuliren", "chuliren"), ("dizhi", "dizhi"), ("yonghuhao", "yonghuhao"),
        ("wentimiaoshu", "wentimiaoshu"), ("laiyuan", "laiyuan"),
        ("caozuoriqi", "caozuoriqi"), ("jindu", "jindu"),
        ("cuibancishu", "cuibancishu"), ("zuihouneirong", "zuihouneirong"),
        ("jiedanfangshi", "jiedanfangshi"), ("jiedanren", "jiedanren"),
        ("jiedanbm", "jiedanbm"), ("zuihouriqi", "zuihouriqi"),
        ("pipesize", "pipesize"),
    ]),
    "gongdan_neirong_dict": ("gongdan_neirong_dict", [
        ("Id", "id"), ("neirong", "neirong"), ("use_count", "use_count"),
        ("last_used_time", "last_used_time"),
    ]),
    "gongdan_caizhi_dict": ("gongdan_caizhi_dict", [
        ("Id", "id"), ("caizhi", "caizhi"), ("use_count", "use_count"),
        ("last_used_time", "last_used_time"),
    ]),
}

DICT_TABLES = ("gongdan_neirong_dict", "gongdan_caizhi_dict")


def old_conn():
    import os

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    oc = old_conn()
    try:
        ocur = oc.cursor()
        old_counts = {}
        old_use_sums = {}
        for old_table, (_new, field_map) in TABLES.items():
            ocur.execute(f"SELECT COUNT(*) FROM [{old_table}]")
            old_counts[old_table] = ocur.fetchone()[0]
            if old_table in DICT_TABLES:
                ocur.execute(f"SELECT ISNULL(SUM(use_count),0) FROM [{old_table}]")
                old_use_sums[old_table] = int(ocur.fetchone()[0])
            print(f"  旧库 {old_table}: {old_counts[old_table]} 条"
                  + (f", SUM(use_count)={old_use_sums[old_table]}" if old_table in DICT_TABLES else ""))
        ocur.execute("SELECT COUNT(*) FROM [gongdancailiao]")
        old_gdc = ocur.fetchone()[0]
    finally:
        oc.close()

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    nc = new_conn()
    report = {"at": datetime.now().isoformat(timespec="seconds"), "tables": {}, "checks": {}}
    try:
        ncur = nc.cursor()
        # 保护:记录迁移前 gongdancailiao 行数,迁移后不变才算没误伤共享表
        ncur.execute("SELECT COUNT(*) FROM `gongdancailiao`")
        before_gdc = ncur.fetchone()[0]

        oc = old_conn()
        try:
            ocur = oc.cursor()
            for old_table, (new_table, field_map) in TABLES.items():
                old_fields = [o for o, _n in field_map]
                new_fields = [n for _o, n in field_map]
                ncur.execute(f"TRUNCATE TABLE `{new_table}`")
                ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in old_fields)} FROM [{old_table}]")
                insert_sql = (
                    f"INSERT INTO `{new_table}` (" + ", ".join(f"`{c}`" for c in new_fields)
                    + f") VALUES ({', '.join(['%s'] * len(new_fields))})"
                )
                written = 0
                max_id = 0
                while True:
                    batch = ocur.fetchmany(1000)
                    if not batch:
                        break
                    rows = [tuple(r) for r in batch]
                    ncur.executemany(insert_sql, rows)
                    written += len(rows)
                    max_id = max(max_id, *(int(r[0] or 0) for r in rows))
                if max_id:
                    ncur.execute(f"ALTER TABLE `{new_table}` AUTO_INCREMENT = {max_id + 1}")
                report["tables"][new_table] = {"rows": written, "auto_increment": max_id + 1}
                print(f"  {new_table}: 写入 {written} 条,自增起点 {max_id + 1}")
        finally:
            oc.close()

        nc.commit()

        # 校验 1:新库行数与旧库一致
        for old_table, (new_table, _fm) in TABLES.items():
            ncur.execute(f"SELECT COUNT(*) FROM `{new_table}`")
            new_count = ncur.fetchone()[0]
            ok = new_count == old_counts[old_table]
            report["checks"][f"rows_{new_table}"] = {"old": old_counts[old_table],
                                                     "new": new_count, "ok": ok}
            print(f"  校验行数 {new_table}: 旧 {old_counts[old_table]} / 新 {new_count} "
                  f"{'一致 ✓' if ok else '不一致 ✗'}")
            if not ok:
                raise SystemExit(f"{new_table} 行数不一致,请检查")

        # 校验 2:字典 use_count 合计一致
        for t in DICT_TABLES:
            ncur.execute(f"SELECT COALESCE(SUM(use_count),0) FROM `{t}`")
            new_sum = int(ncur.fetchone()[0])
            ok = new_sum == old_use_sums[t]
            report["checks"][f"use_count_{t}"] = {"old": old_use_sums[t],
                                                  "new": new_sum, "ok": ok}
            print(f"  校验 SUM(use_count) {t}: 旧 {old_use_sums[t]} / 新 {new_sum} "
                  f"{'一致 ✓' if ok else '不一致 ✗'}")
            if not ok:
                raise SystemExit(f"{t} use_count 不一致,请检查")

        # 校验 3:共享表未被误伤
        ncur.execute("SELECT COUNT(*) FROM `gongdancailiao`")
        after_gdc = ncur.fetchone()[0]
        ok = (before_gdc == after_gdc == old_gdc)
        report["checks"]["gongdancailiao_untouched"] = {
            "old": old_gdc, "before": before_gdc, "after": after_gdc, "ok": ok,
        }
        print(f"  校验共享表 gongdancailiao 未重导: 旧 {old_gdc} / 前 {before_gdc} / 后 {after_gdc} "
              f"{'一致 ✓' if ok else '不一致 ✗'}")
        if not ok:
            raise SystemExit("gongdancailiao 行数异常,请检查")
    except pymysql.err.ProgrammingError as exc:
        raise SystemExit(
            "目标表不存在,请先运行 python -m scripts.init_db 建表。"
            f"\n原始错误: {exc}"
        )
    finally:
        nc.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"gongdan_import_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {out}")
    print("完成")


if __name__ == "__main__":
    main()
