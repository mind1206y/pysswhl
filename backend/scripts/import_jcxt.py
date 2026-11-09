"""稽查系统历史数据导入:旧库 db_plan.dbo.jc_* -> 新库同名表。

- jc_jcxx(稽查信息) / jc_tupian(图片) / jc_printcolum(自选导出列) /
  jcdan(稽查单) / jc_wzlb(违章类别) / jc_wzdw(违章单位,旧 0 条) /
  jcjiangli(月度奖励) / jcjiangliFp(分配明细)
- 全部保留旧主键 id,导入后调整自增起点;逐表 TRUNCATE 可重导
- 部门 id 重映射(jc_jcxx.ssbmid / jcdan.bmid / jcjiangli.bmid /
  jcjiangliFp.bmid)按 migration_reports/department_map.json,映射不到置 NULL 并告警
- jc_printcolum.userid:旧 bb_user.id 先走 user_map.json,再按旧用户名匹配新
  users.username;匹配不到的行跳过(导出列是个人偏好,不造孤儿数据)
- 支持 --dry-run;导出迁移报告到 migration_reports/

用法(backend 目录下):
    python -m scripts.import_jcxt --dry-run
    python -m scripts.import_jcxt
"""

import argparse
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
import pymysql
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent
REPORT_DIR = BASE / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"
USER_MAP_FILE = REPORT_DIR / "user_map.json"

TABLES = {
    "jc_wzlb": ["id", "lbname", "ssname"],
    "jc_wzdw": ["id", "weizhangren"],
    "jc_jcxx": [
        "id", "gongdanhao", "caozuoriqi", "chuliriqi", "weizhangriqi",
        "weizhangren", "weizhangdianhua", "weizhangdizhi", "zhuijiaoshuifei",
        "zhuijiaogongliaofei", "jubaoren", "ssbmid", "zhuijiaobm",
        "zuihougengxin", "jbjiangli", "zhuijiaojiangli", "zhuangtai",
        "zhixingqingkuang", "lbid", "caozuoname", "yingjiaoshuiliang",
        "yingjiaoshuifei", "yingjiaogongliaofei", "beizhu", "jubaoleibie",
        "xinxilaiyuan", "banjietianshu", "weizhangneirong", "zhuijiaoshuiliang",
        "guancai", "guanjing", "nongcunjicha", "oldid", "danjia", "intguanjing",
        "spren", "spzt", "spdate", "peibiaofei", "wzleibie", "ssspren", "jcdanid",
    ],
    "jc_tupian": ["id", "url", "jcxxid"],
    "jc_printcolum": ["id", "userid", "printcolum"],
    "jcdan": [
        "id", "gongdanhao", "weizhangdanwei", "bmid", "bianhao", "jbren",
        "fstime", "didian", "nr", "wzren", "usname", "bz", "jbleibie",
        "addtime", "edtime", "kpren", "weizhangdianhua", "jcxxid",
    ],
    "jcjiangli": [
        "id", "bmid", "nd", "yue", "jianglijine", "zjshuifei", "zjbutie",
        "jbjiangli", "usname", "utime", "zjbutie_int",
    ],
    "jcjiangliFp": ["id", "fpname", "jlid", "bmid", "fpjine", "uname", "utime", "xmu"],
}

BMID_FIELDS = {"jc_jcxx": ["ssbmid"], "jcdan": ["bmid"],
               "jcjiangli": ["bmid"], "jcjiangliFp": ["bmid"]}


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def new_conn():
    conn = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "sswhl_app"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "sswhl_new"),
        charset="utf8mb4", autocommit=False,
    )
    return conn


def load_maps():
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    bmid_map = {int(k): v for k, v in data.get("bmid_map", {}).items()}
    user_map = {}
    if USER_MAP_FILE.exists():
        um = json.loads(USER_MAP_FILE.read_text(encoding="utf-8"))
        user_map = {int(k): v for k, v in um.get("user_map", {}).items()}
    return bmid_map, user_map


def fetch_all(cur, table, fields):
    cols = ", ".join(f"[{f}]" for f in fields)
    cur.execute(f"SELECT {cols} FROM [{table}]")
    rows = [dict(zip(fields, r)) for r in cur.fetchall()]
    print(f"  旧库 {table}: {len(rows)} 条")
    return rows


def clean(v):
    """pyodbc -> MySQL 兼容清洗。"""
    if isinstance(v, str):
        return v.replace("\x00", "").strip() or None
    return v


def remap_bmid(table, row, field, bmid_map, unmapped):
    v = row.get(field)
    if v is None:
        return None
    nv = bmid_map.get(int(v))
    if nv is None:
        unmapped.add((table, field, int(v)))
        return None
    return nv


def main(dry_run: bool):
    bmid_map, user_map = load_maps()
    ocon = old_conn()
    ocur = ocon.cursor()
    ncon = new_conn()
    ncur = ncon.cursor()

    # 旧 bb_user id -> username(jc_printcolum 按用户名兜底匹配)
    old_users = {}
    try:
        for uid, uname in ocur.execute(
                "SELECT [id], [username] FROM [bb_user]").fetchall():
            old_users[int(uid)] = uname
    except Exception as e:
        print(f"  读取 bb_user 失败({e}),jc_printcolum 仅按 user_map 映射")

    # 新 users.username -> id
    ncur.execute("SELECT id, username FROM users")
    new_users = {name: uid for uid, name in ncur.fetchall()}

    report = {"generated_at": datetime.now().isoformat(), "tables": {},
              "bmid_unmapped": [], "printcolum_skipped": 0}
    unmapped: set = set()
    skipped_pc = 0

    for table, fields in TABLES.items():
        rows = fetch_all(ocur, table, fields)
        if not dry_run:
            ncur.execute(f"TRUNCATE TABLE `{table}`")
        for row in rows:
            vals = {}
            for f in fields:
                v = clean(row.get(f))
                if f in ("ssbmid", "bmid"):
                    v = remap_bmid(table, row, f, bmid_map, unmapped)
                vals[f] = v
            if table == "jc_printcolum":
                uid = row.get("userid")
                nid = user_map.get(int(uid)) if uid is not None else None
                if nid is None and uid is not None:
                    uname = old_users.get(int(uid))
                    nid = new_users.get(uname) if uname else None
                if nid is None:
                    skipped_pc += 1
                    continue
                vals["userid"] = nid
            cols = ", ".join(f"`{k}`" for k in fields)
            ph = ", ".join(["%s"] * len(fields))
            if not dry_run:
                ncur.execute(
                    f"INSERT INTO `{table}` ({cols}) VALUES ({ph})",
                    [vals[f] for f in fields],
                )
            # 调整自增起点
            if not dry_run and rows:
                max_id = max(int(r["id"]) for r in rows)
                ncur.execute(
                    f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
        report["tables"][table] = len(rows)
        print(f"  新库 {table}: {'dry-run' if dry_run else '已写入'} {len(rows)} 条")

    report["bmid_unmapped"] = sorted({f"{t}.{f}:{v}" for t, f, v in unmapped})
    report["printcolum_skipped"] = skipped_pc

    # 一致性校验(金额/数量合计)
    checks = {
        "jc_jcxx": ["zhuijiaoshuifei", "zhuijiaogongliaofei", "jbjiangli",
                    "zhuijiaojiangli", "peibiaofei"],
        "jcjiangli": ["zjshuifei", "jbjiangli", "zjbutie", "jianglijine"],
        "jcjiangliFp": ["fpjine"],
    }
    sums = {}
    for t, fs in checks.items():
        for f in fs:
            ocur.execute(f"SELECT ISNULL(SUM([{f}]),0) FROM [{t}]")
            old_v = Decimal(str(ocur.fetchone()[0]))
            new_v = Decimal("0")
            if not dry_run:
                ncur.execute(f"SELECT COALESCE(SUM(`{f}`),0) FROM `{t}`")
                new_v = Decimal(str(ncur.fetchone()[0]))
            sums[f"{t}.{f}"] = [str(old_v), str(new_v), old_v == new_v]
    report["sum_checks"] = sums

    if dry_run:
        print("[dry-run] 未写入新库")
    else:
        ncon.commit()
        print("已提交新库")
    print("部门未映射:", report["bmid_unmapped"] or "无")
    print("printcolum 跳过(无匹配用户):", skipped_pc)
    for k, v in sums.items():
        flag = "OK" if v[2] else "!!"
        print(f"  [{flag}] {k}: 旧 {v[0]} / 新 {v[1]}" if not dry_run
              else f"  旧 {k}: {v[0]}")

    if not dry_run:
        REPORT_DIR.mkdir(exist_ok=True)
        out = REPORT_DIR / f"jcxt_import_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"报告: {out}")

    ocon.close()
    ncon.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(args.dry_run)
