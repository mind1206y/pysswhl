"""合同登记/归集历史数据导入:旧库 ht_add / ht_tp / ht_zb_supplier → 新库同名表。

按 docs/数据迁移约定.md:
- 表名/字段沿用旧库,保留旧主键 id,可重复执行(TRUNCATE 重导);
- 旧 bb_bumen.id → 新 departments.id 走 department_map.json;
- 旧 bb_user.id → 新 users.id 走 user_map.json,映射不到时 djuser/spuserid 置空,
  同时把旧姓名写入 djuser_name/spuserid_name 快照列,列表仍能显示提交人;
- 附件物理文件在旧系统生产服务器,本机源码目录没有:
  拿到 Upload 目录后跑 --copy-files <旧系统 Upload 目录> 即可补齐。

用法(backend 目录下):
    python -m scripts.import_contracts                  # 全量导入(不动物理文件)
    python -m scripts.import_contracts --dry-run        # 只统计
    python -m scripts.import_contracts --copy-files E:\\sswhl\\sswhl\\Upload
"""

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"

MAIN_FIELDS = [
    "id", "name", "nr", "bz", "djdate", "editdate", "djuser", "spuserid", "zt",
    "niandu", "bh", "spdate", "locked", "jine", "allbh", "leibie", "duixiang",
    "biaodi", "zzdate", "lvxingqingkuang", "jingbanren", "qddate", "ssdate",
    "gjtime", "bumenid", "beizhu", "zhaobiaofangshi", "kongzhijia", "sfwjdw",
]
TP_FIELDS = ["id", "url", "htid", "oldname", "fsize"]
ZB_FIELDS = [
    "id", "htid", "gongyingshang", "toubiaojia", "zuizhongjia", "paixu", "sfzb",
    "swfs", "jsfs", "jgfs", "zfs", "beizhu",
]
INSERT_FIELDS = MAIN_FIELDS + ["djuser_name", "spuserid_name"]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def load_json(name):
    path = REPORT_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_maps(cur):
    dept_map = load_json("department_map.json").get("depts", {})
    user_map = load_json("user_map.json").get("user_map", {})
    cur.execute("SELECT id, unames, username FROM bb_user")
    users = {}
    for uid, unames, username in cur.fetchall():
        users[uid] = (unames or "").strip() or (username or "").strip()
    dept_by_old = {int(k): v for k, v in dept_map.items()}
    user_by_old = {int(k): v for k, v in user_map.items()}
    return dept_by_old, user_by_old, users


def fetch_all(cur, table, fields):
    cur.execute(f"SELECT {', '.join(fields)} FROM {table} ORDER BY id")
    return [list(r) for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
    parser.add_argument("--copy-files", metavar="UPLOAD_DIR",
                        help="旧系统 Upload 目录(其下有 htdjPDF 子目录),用于补齐 PDF 物理文件")
    parser.add_argument("--no-truncate", action="store_true", help="保留新库已有数据(调试用)")
    args = parser.parse_args()

    conn = old_conn()
    try:
        cur = conn.cursor()
        dept_by_old, user_by_old, old_users = build_maps(cur)
        adds = fetch_all(cur, "ht_add", MAIN_FIELDS)
        tps = fetch_all(cur, "ht_tp", TP_FIELDS)
        zbs = fetch_all(cur, "ht_zb_supplier", ZB_FIELDS)
        cur.execute("SELECT id, bm, htdaihao FROM bb_bumen")
        old_depts = cur.fetchall()
    finally:
        conn.close()

    print(f"ht_add: {len(adds)} 条, ht_tp: {len(tps)} 条, ht_zb_supplier: {len(zbs)} 条")

    mapped_dept, missing_dept = 0, set()
    mapped_user, missing_user = 0, set()
    out_adds = []
    for row in adds:
        rec = dict(zip(MAIN_FIELDS, row))
        old_bm = rec.get("bumenid")
        if old_bm is not None:
            new_bm = dept_by_old.get(int(old_bm), {}).get("new_id")
            if new_bm is None:
                missing_dept.add(old_bm)
            else:
                mapped_dept += 1
            rec["bumenid"] = new_bm
        dj_name = ""
        for key, name_key in (("djuser", "djuser_name"), ("spuserid", "spuserid_name")):
            old_uid = rec.get(key)
            if old_uid is None:
                rec[name_key] = ""
                continue
            new_uid = user_by_old.get(int(old_uid))
            dj_name = old_users.get(int(old_uid), "")
            if new_uid is None:
                missing_user.add(old_uid)
            else:
                mapped_user += 1
            rec[key] = new_uid
            rec[name_key] = dj_name
        out_adds.append([rec[f] for f in INSERT_FIELDS])

    print(f"部门映射: {mapped_dept}/{len(adds)} 条, 未映射部门 {sorted(missing_dept) or '无'}")
    print(f"用户映射: {mapped_user} 个用户字段, 未映射用户 {len(missing_user)} 个(置空并用姓名快照)")
    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ht_add": len(out_adds), "ht_tp": len(tps), "ht_zb_supplier": len(zbs),
        "mapped_dept_rows": mapped_dept, "missing_dept_ids": sorted(missing_dept),
        "missing_user_ids": sorted(missing_user), "copied_files": 0, "missing_files": 0,
    }
    try:
        ncur = new.cursor()
        # 部门合同代号(htdaihao):按旧部门名回填,新合同编号前缀依赖它
        dept_codes = {
            int(v["new_id"]): v.get("htdaihao") or ""
            for v in dept_by_old.values()
            if v.get("new_id") and v.get("htdaihao")
        }
        for new_id, code in dept_codes.items():
            ncur.execute("UPDATE departments SET htdaihao=%s WHERE id=%s", (code, new_id))
        print(f"部门合同代号已回填 {len(dept_codes)} 个")

        if not args.no_truncate:
            for t in ("ht_tp", "ht_zb_supplier", "ht_add"):
                ncur.execute(f"TRUNCATE TABLE {t}")
        if out_adds:
            ph = ", ".join(["%s"] * len(INSERT_FIELDS))
            ncur.executemany(f"INSERT INTO ht_add ({', '.join(INSERT_FIELDS)}) VALUES ({ph})", out_adds)
            ncur.execute(f"ALTER TABLE ht_add AUTO_INCREMENT = {max(r[0] for r in out_adds) + 1}")
        if zbs:
            ph = ", ".join(["%s"] * len(ZB_FIELDS))
            ncur.executemany(f"INSERT INTO ht_zb_supplier ({', '.join(ZB_FIELDS)}) VALUES ({ph})", zbs)
            ncur.execute(f"ALTER TABLE ht_zb_supplier AUTO_INCREMENT = {max(r[0] for r in zbs) + 1}")
        if tps:
            ph = ", ".join(["%s"] * len(TP_FIELDS))
            ncur.executemany(f"INSERT INTO ht_tp ({', '.join(TP_FIELDS)}) VALUES ({ph})", tps)
            ncur.execute(f"ALTER TABLE ht_tp AUTO_INCREMENT = {max(r[0] for r in tps) + 1}")
        new.commit()
        print(f"已导入: ht_add {len(out_adds)}, ht_zb_supplier {len(zbs)}, ht_tp {len(tps)}")
    finally:
        new.close()

    # 物理附件:旧 url 形如 /Upload/htdjPDF/2023/9/11/xxx.pdf
    if args.copy_files:
        src_root = Path(args.copy_files)
        src = src_root / "htdjPDF" if (src_root / "htdjPDF").is_dir() else src_root
        dst_root = Path(settings.UPLOAD_DIR) / "htdjPDF"
        copied = missing = 0
        for tp in tps:
            url = (tp[1] or "").replace("\\", "/")
            marker = "/htdjPDF/"
            if marker not in url:
                missing += 1
                continue
            rel = url.split(marker, 1)[1]
            src_file = src / rel
            if not src_file.exists():
                missing += 1
                continue
            dst_file = dst_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
        report["copied_files"], report["missing_files"] = copied, missing
        print(f"附件文件复制: {copied} 个, 缺失 {missing} 个")
    else:
        print("未指定 --copy-files: 只导入了附件记录,PDF 文件仍缺失(下载时会提示文件缺失)")
        print("拿到旧系统生产服务器的 Upload 目录后,重跑并加 --copy-files <该目录> 即可补齐")

    report_path = REPORT_DIR / f"contract_import_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {report_path}")


if __name__ == "__main__":
    main()
    print("完成")
