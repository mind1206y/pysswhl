"""维抢修加班 Jiaban 模块历史数据导入:旧库 db_plan.dbo.* -> 新库。

- jiaban(3095)                 加班记录;lei(bit) 转成 1/0/NULL
- jiabanrenyuan(51)            加班人员
- jiaban_attachment(508)       附件记录(旧服务器文件本机缺失,只迁元数据,下载 404 兜底)
- 全部保留旧主键 id,导入后调整自增起点;三张表均无 bmid 字段,无需部门映射
- ⛔ 不碰 gongdancailiao(工单历史记录来源,由 import_workorder.py 维护)
- 可重复执行(逐表 TRUNCATE 重导),支持 --dry-run

用法(backend 目录下):
    python -m scripts.import_jiaban --dry-run
    python -m scripts.import_jiaban
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
    "jiaban": ("jiaban", [
        ("id", "id"), ("nameid", "nameid"), ("riqi", "riqi"),
        ("gongdanNo", "gongdanNo"), ("kjshijian", "kjshijian"),
        ("dizhi", "dizhi"), ("neirong", "neirong"), ("shijian", "shijian"),
        ("beishu", "beishu"), ("zongshu", "zongshu"), ("username", "username"),
        ("createtime", "createtime"), ("kstime", "kstime"), ("jstime", "jstime"),
        ("lei", "lei"),
    ]),
    "jiabanrenyuan": ("jiabanrenyuan", [
        ("id", "id"), ("name", "name"), ("bmlb", "bmlb"),
        ("danjia", "danjia"), ("gonghao", "gonghao"),
    ]),
    "jiaban_attachment": ("jiaban_attachment", [
        ("id", "id"), ("jiabanDate", "jiabanDate"), ("file_name", "file_name"),
        ("filePath", "filePath"), ("fileSize", "fileSize"),
        ("uploadTime", "uploadTime"), ("operator_name", "operator_name"),
    ]),
}

# jiaban.lei 单独处理:旧 bit(True/False/None) -> 新 1/0/NULL


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


def _norm_lei(v):
    """旧 bit -> 新 tinyint:True->1 / False->0 / None->NULL。"""
    if v is None:
        return None
    return 1 if v else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    args = parser.parse_args()

    oc = old_conn()
    try:
        ocur = oc.cursor()
        old_counts = {}
        old_sums = {}
        for old_table, (_new, field_map) in TABLES.items():
            ocur.execute(f"SELECT COUNT(*) FROM [{old_table}]")
            old_counts[old_table] = ocur.fetchone()[0]
            print(f"  旧库 {old_table}: {old_counts[old_table]} 条")
        ocur.execute("SELECT ISNULL(SUM(shijian),0), ISNULL(SUM(zongshu),0) FROM [jiaban]")
        row = ocur.fetchone()
        old_sums["jiaban"] = (float(row[0]), float(row[1]))
        ocur.execute("SELECT ISNULL(SUM(danjia),0) FROM [jiabanrenyuan]")
        old_sums["danjia"] = float(ocur.fetchone()[0])
        ocur.execute("SELECT ISNULL(SUM(fileSize),0) FROM [jiaban_attachment]")
        old_sums["fileSize"] = int(ocur.fetchone()[0])
    finally:
        oc.close()

    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    nc = new_conn()
    report = {"at": datetime.now().isoformat(timespec="seconds"), "tables": {}, "checks": {}}
    try:
        ncur = nc.cursor()
        # 保护:记录迁移前 gongdancailiao 行数(工单历史记录来源,本脚本不碰)
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
                    # pyodbc 会截断行尾的 NULL 列:统一补齐到查询列数,再按位转换
                    rows = [r + (None,) * (len(old_fields) - len(r)) for r in rows]
                    lei_idx = old_fields.index("lei") if old_table == "jiaban" else None
                    if lei_idx is not None:
                        rows = [
                            r[:lei_idx] + (_norm_lei(r[lei_idx]),) + r[lei_idx + 1:]
                            for r in rows
                        ]
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

        # 校验 2:金额/时长合计一致
        ncur.execute("SELECT COALESCE(SUM(shijian),0), COALESCE(SUM(zongshu),0) FROM `jiaban`")
        nsj, nzs = ncur.fetchone()
        ok = (round(float(nsj), 2) == round(old_sums["jiaban"][0], 2)
              and round(float(nzs), 2) == round(old_sums["jiaban"][1], 2))
        report["checks"]["sum_jiaban"] = {
            "old": old_sums["jiaban"], "new": [float(nsj), float(nzs)], "ok": ok}
        print(f"  校验 SUM(shijian/zongshu): 旧 {old_sums['jiaban']} / 新 {[float(nsj), float(nzs)]} "
              f"{'一致 ✓' if ok else '不一致 ✗'}")
        if not ok:
            raise SystemExit("jiaban 合计不一致,请检查")

        ncur.execute("SELECT COALESCE(SUM(danjia),0) FROM `jiabanrenyuan`")
        ndj = float(ncur.fetchone()[0])
        ok = round(ndj, 2) == round(old_sums["danjia"], 2)
        report["checks"]["sum_danjia"] = {"old": old_sums["danjia"], "new": ndj, "ok": ok}
        print(f"  校验 SUM(danjia): 旧 {old_sums['danjia']} / 新 {ndj} "
              f"{'一致 ✓' if ok else '不一致 ✗'}")

        ncur.execute("SELECT COALESCE(SUM(fileSize),0) FROM `jiaban_attachment`")
        nfs = int(ncur.fetchone()[0])
        ok = nfs == old_sums["fileSize"]
        report["checks"]["sum_fileSize"] = {"old": old_sums["fileSize"], "new": nfs, "ok": ok}
        print(f"  校验 SUM(fileSize): 旧 {old_sums['fileSize']} / 新 {nfs} "
              f"{'一致 ✓' if ok else '不一致 ✗'}")

        # 校验 3:共享表 gongdancailiao 未被误伤
        ncur.execute("SELECT COUNT(*) FROM `gongdancailiao`")
        after_gdc = ncur.fetchone()[0]
        ok = before_gdc == after_gdc
        report["checks"]["gongdancailiao_untouched"] = {
            "before": before_gdc, "after": after_gdc, "ok": ok}
        print(f"  校验共享表 gongdancailiao 未误伤: 前 {before_gdc} / 后 {after_gdc} "
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
    out = REPORT_DIR / f"jiaban_import_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {out}")
    print("完成")


if __name__ == "__main__":
    main()
