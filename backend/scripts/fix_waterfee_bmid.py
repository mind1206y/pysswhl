"""修正迁移数据的 bmid:旧库 bb_bumen.id → 新库 departments.id(按部门名精确映射)。

背景:import_water_fee.py / import_projects.py 迁移时原样复制了旧 bb_bumen.id,而
新 departments 表是 init_db.py 手工重建的(id 与旧库不对应,如旧 7=海沧营业所,
新 7=售水事业部)。两边部门名称一一对应(旧 cj 层级码 = 新 parent_id 树)。
覆盖所有已迁移且带 bmid 的表:
    shuifeixitong / shuifeixitongquxiao / gongchenggl

⚠ **本脚本已完成使命,请勿再执行**(2026-11-08 起):
部门表由 import_departments.py 补齐到 38 个后,脚本按名称现算出的 mapping 从 9 项变成
38 项,而三张表里的 bmid 早已是「新 id」;旧/新 id 空间大量重叠(如 8→12、12→11),
一旦重跑(尤其 --force)会把已修好的值再次当旧 id 改掉,造成二次污染。
三张表已修完且逐行核对通过;后续补空统一用 repair_bmid_from_old.py(只补 NULL,幂等)。
检测到 department_map.json 时本脚本默认直接拒绝执行,确需强制运行加 --allow-legacy。

用法(backend 目录下):
    python -m scripts.fix_waterfee_bmid --dry-run   # 只显示映射与影响行数(安全)
    python -m scripts.fix_waterfee_bmid --allow-legacy  # 明确知晓风险后才可执行
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

TABLES = ["shuifeixitong", "shuifeixitongquxiao", "gongchenggl"]
SENTINEL = Path(__file__).parent / "migration_reports" / "bmid_fixed.json"
DEPT_MAP = Path(__file__).parent / "migration_reports" / "department_map.json"


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只显示映射与影响行数")
    parser.add_argument("--force", action="store_true",
                        help="忽略已修标记强制重跑(危险:重映射后旧/新 id 空间重叠,重跑会二次污染!)")
    parser.add_argument("--allow-legacy", action="store_true",
                        help="明确知晓二次污染风险,强制执行这个已退役的一次性脚本")
    args = parser.parse_args()

    if DEPT_MAP.exists() and not args.dry_run and not args.allow_legacy:
        print("⛔ 已拒绝执行:部门表已补齐(见 department_map.json),本脚本的一次性映射已失效。")
        print("   三张表的 bmid 早已是新 id,而 mapping 现在含 38 项,重跑会二次污染。")
        print("   补空请用 repair_bmid_from_old.py;确需强制运行加 --allow-legacy。")
        return

    # 防呆哨兵:旧/新 bmid 空间重叠(旧8=同安,新8=厦门),重跑会把已映射的新值再当旧值改掉
    done = json.loads(SENTINEL.read_text(encoding="utf-8")) if SENTINEL.exists() else {}

    oconn = old_conn()
    ocur = oconn.cursor()
    ocur.execute("SELECT id, bm FROM bb_bumen")
    old_depts = dict(ocur.fetchall())  # 旧 bmid → 部门名
    oconn.close()

    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM departments")
        by_name = {name: i for i, name in cur.fetchall()}

        mapping = {}
        for oid, name in old_depts.items():
            new_id = by_name.get(name)
            if new_id is not None:
                mapping[oid] = new_id
        print("映射表(旧 bmid → 新 departments.id):")
        for oid, nid in sorted(mapping.items()):
            mark = "  (相同,无需改)" if oid == nid else ""
            print(f"  {oid:>3} {old_depts[oid]:<8} → {nid}{mark}")

        # 用 CASE 一次性原子更新,避免链式覆盖(如 2→8 后又被 8→12 改掉)
        total = 0
        newly_done = []
        for t in TABLES:
            if t in done and not args.force:
                print(f"⏭ {t}: 已于 {done[t].get('fixed_at')} 修正过,跳过(确需重跑加 --force)")
                continue
            cur.execute(f"SELECT DISTINCT bmid FROM {t} WHERE bmid IS NOT NULL")
            used = {r[0] for r in cur.fetchall()}
            to_fix = {oid: nid for oid, nid in mapping.items() if oid in used and oid != nid}
            unmapped = used - set(mapping)
            if unmapped:
                print(f"⚠ {t} 存在新部门表找不到的 bmid: {sorted(unmapped)}(跳过,请先在部门管理补建同名部门)")
            if not to_fix:
                continue
            cases = " ".join(f"WHEN {oid} THEN {nid}" for oid, nid in sorted(to_fix.items()))
            ids = ",".join(str(oid) for oid in to_fix)
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE bmid IN ({ids})")
            n = cur.fetchone()[0]
            print(f"  {t}: 重映射 {len(to_fix)} 个 bmid,影响 {n} 行")
            for oid, nid in sorted(to_fix.items()):
                print(f"    {oid}({old_depts.get(oid)}) → {nid}({by_name.get(nid)})")
            total += n
            if not args.dry_run:
                cur.execute(f"UPDATE {t} SET bmid = CASE bmid {cases} END WHERE bmid IN ({ids})")
                newly_done.append(t)
        if not args.dry_run:
            conn.commit()
            for t in newly_done:
                done[t] = {"fixed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            SENTINEL.parent.mkdir(exist_ok=True)
            SENTINEL.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"完成,共更新 {total} 行;已修标记写入 {SENTINEL.name}")
        else:
            print(f"dry-run:共将更新 {total} 行,未写入")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
