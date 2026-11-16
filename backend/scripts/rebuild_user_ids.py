"""把新库 users.id 重编号为旧库 bb_user.id（1:1 恒等），并同步修正引用列。

用法（在 backend 目录下）:
    python -m scripts.rebuild_user_ids --dry-run    # 只预览，不写库
    python -m scripts.rebuild_user_ids              # 正式重建（先自动备份）

## 为什么要重建

2026-11-15 用户全量迁移时，新库里**早已存在** id=1 admin、id=7 林春，
旧库 id=3 林春 / id=7 陈毅清 / id=207 admin 无法原样落位，产生 3 个特例：
    旧 3(林春)   -> 新 7
    旧 7(陈毅清) -> 新 383
    旧 207(admin) -> 新 1

但下面这些历史表是**直接搬旧 bb_user.id**、没有走 user_map 映射的：
    sms_contact.id / gx_user_gxgz.userid / jh_ssdb.zhuanguan /
    jh_ssdbpz.zhuanguan / jh_yyfq.zgy / jh_yyfq.opid /
    ht_add.djuser / jc_printcolum.userid / wzcgsq.userid
而 plan_common.resolve_user_id() 在**新增/编辑**时写入的是当前 users.id。
两套口径不一致 -> 历史行与新行按 userid 关联/过滤时对不上（重建前约 1.2 万行悬空）。

让 users.id == 旧 bb_user.id 之后，这两类列自动统一，无需改动历史表。

## 映射（当前 id -> 目标 id）

    1   (admin)            -> 207
    7   (林春)             -> 3
    383 (陈毅清)           -> 7
    21  (guitest 测试超管)  -> 删除（旧库无此账号；避免生产环境留免改密超管）
    其余 196 个账号保持原 id 不动

## 两个必须遵守的实现约束

1. **两段式更新**：先把待改值整体挪到 +100000 临时区，再改回目标值。
   user_role / user_department 是复合主键，若单条 CASE 直接把 7->3、383->7，
   MySQL 逐行更新时可能先撞上尚未腾空的 7。两段式彻底避开。
   ⛔ 禁止逐条 UPDATE 循环（旧/新 id 数字重叠会链式污染，见部门 bmid 的坑）。
2. **外键**：user_role / user_department 对 users 是 ON UPDATE NO ACTION，
   改主键期间必须 SET FOREIGN_KEY_CHECKS=0，结束后恢复并逐列校验 0 悬空。

## 不受影响（不要动）

- 存旧 id 的列（A 类，见 OLD_ID_COLUMNS）：重建后自动对齐。
- overtime_record.userid -> overtime_user.id(1~19)、jiaban.nameid -> jiabanrenyuan.id(1~60)，
  属于别的 id 空间。
- 所有 *.username / CreateUser 等 varchar 列存的是姓名/登录名文本。
"""

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"

# 当前 users.id -> 旧 bb_user.id
ID_MAP = {1: 207, 7: 3, 383: 7}
# 旧库没有、需要清掉的测试账号
DELETE_IDS = {21}
OFFSET = 100000

# 存「当前新 users.id」的列，必须跟着重映射。
# 前 8 个来自 import_overtime.py；后 4 个来自 import_contracts / import_finance /
# import_jcxt —— 它们也是按 user_map 映射过的（旧 3 林春当时被映射成 7），
# ⚠ 别误当成「直接搬旧 id」的列：只看悬空会发现不了「7 指向错的人」，
#   必须同时用姓名快照做语义校验（见 SEMANTIC_PAIRS / 实机排查记录）。
NEW_ID_COLUMNS = {
    "user_role": ["user_id"],
    "user_department": ["user_id"],
    "overtime_apply": ["apply_user_id", "verify_user_id"],
    "overtime_apply_detail": ["apply_user_id"],
    "overtime_approver": ["bb_user_id"],
    "overtime_apply_approval": ["approver_id"],
    "overtime_comp_leave": ["create_user_id"],
    "overtime_personnel": ["bb_user_id"],
    "ht_add": ["djuser", "spuserid"],
    "wzcgsq": ["userid"],
    "jc_printcolum": ["userid"],
}

# 存「旧 bb_user.id」的列，原样保留，仅用于验收（重建后应 0 悬空）
OLD_ID_COLUMNS = {
    "sms_contact": ["id"],
    "gx_user_gxgz": ["userid"],
    "jh_ssdb": ["zhuanguan"],
    "jh_ssdbpz": ["zhuanguan"],
    "jh_yyfq": ["zgy", "opid"],
}

# (表, 用户 id 列, 姓名快照列)：光查「id 是否存在」不够，还要核对 id 指向的人对不对
SEMANTIC_PAIRS = [
    ("sms_contact", "id", "real_name"),
    ("gx_user_gxgz", "userid", "username"),
    ("jh_ssdb", "zhuanguan", "zhuanguan_name"),
    ("jh_ssdbpz", "zhuanguan", "zhuanguan_name"),
    ("jh_yyfq", "zgy", "zgy_name"),
    ("jh_yyfq", "opid", "opname"),
    ("ht_add", "djuser", "djuser_name"),
    ("wzcgsq", "userid", "username"),
]


def old_conn():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};SERVER="
        f"{os.environ.get('OLD_DB_HOST', '127.0.0.1,1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};"
        f"PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')}",
        timeout=10,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )


def json_default(v):
    if isinstance(v, (datetime, Decimal)):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return str(v)


def backup(cur, stamp):
    """把 users 与所有待改表整表备份成 JSON，便于回滚核对。"""
    tables = ["users"] + sorted(NEW_ID_COLUMNS)
    out = {"generated_at": stamp, "tables": {}}
    for t in tables:
        cur.execute(f"SELECT * FROM `{t}`")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        out["tables"][t] = {"columns": cols, "rows": rows}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    p = REPORT_DIR / f"user_ids_backup_{stamp}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=json_default),
                 encoding="utf-8")
    print(f"  已备份 {len(tables)} 张表 -> {p.name}")
    return p


def two_phase(cur, table, column, id_map):
    """两段式：先全部挪到临时区，再从临时区改回目标值。返回 affected 行数。"""
    src = sorted(id_map)
    tmp = [v + OFFSET for v in src]
    case = " ".join(f"WHEN {v + OFFSET} THEN {id_map[v]}" for v in src)
    cur.execute(
        f"UPDATE `{table}` SET `{column}` = `{column}` + %s "
        f"WHERE `{column}` IN ({','.join(['%s'] * len(src))})",
        (OFFSET, *src),
    )
    n1 = cur.rowcount
    cur.execute(
        f"UPDATE `{table}` SET `{column}` = CASE `{column}` {case} END "
        f"WHERE `{column}` IN ({','.join(['%s'] * len(tmp))})",
        tuple(tmp),
    )
    n2 = cur.rowcount
    if n1 != n2:
        raise RuntimeError(f"{table}.{column} 两段式行数不一致: {n1} vs {n2}")
    return n1


def dangling(cur, table, column):
    cur.execute(
        f"SELECT COUNT(*) FROM `{table}` a LEFT JOIN users u ON u.id = a.`{column}` "
        f"WHERE a.`{column}` IS NOT NULL AND u.id IS NULL"
    )
    return cur.fetchone()[0]


def semantic_mismatch(cur, table, id_col, name_col):
    """id 存在但指向的人与姓名快照不符（比悬空更隐蔽的错位）。"""
    cur.execute(
        f"SELECT COUNT(*) FROM `{table}` a JOIN users u ON u.id = a.`{id_col}` "
        f"WHERE a.`{id_col}` IS NOT NULL AND a.`{name_col}` IS NOT NULL "
        f"AND TRIM(a.`{name_col}`) <> '' "
        f"AND a.`{name_col}` NOT IN (u.real_name, u.username)"
    )
    return cur.fetchone()[0]


def main():
    ap = argparse.ArgumentParser(description="users.id 1:1 重编号为旧 bb_user.id")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    args = ap.parse_args()

    oc = old_conn().cursor()
    oc.execute("SELECT id, username FROM dbo.bb_user ORDER BY id")
    old_users = {int(r[0]): r[1] for r in oc.fetchall()}

    cn = new_conn()
    cur = cn.cursor()
    cur.execute("SELECT id, username FROM users ORDER BY id")
    cur_users = {int(r[0]): r[1] for r in cur.fetchall()}

    print(f"旧库 bb_user: {len(old_users)} 个账号, id {min(old_users)}~{max(old_users)}")
    print(f"新库 users  : {len(cur_users)} 个账号, id {min(cur_users)}~{max(cur_users)}")

    # ---- 前置校验：确认当前就是「3 个特例 + 1 个测试账号」的状态 ----
    # 7 既是源号也是目标号：两段式会先把 7 腾空，所以允许当前被占用；
    # 其余目标号(3、207)必须为空，否则会撞主键。
    bad_target = sorted((set(ID_MAP.values()) & set(cur_users)) - set(ID_MAP))
    present_source = sorted(set(ID_MAP) - set(cur_users))
    print(f"\n[前置] 目标号 3/207 当前为空: {not bad_target}")
    if bad_target:
        raise RuntimeError(f"目标 id 已被占用且不会被腾空: {bad_target}")
    if present_source:
        raise RuntimeError(f"待改的源 id 不存在: {present_source}")
    for oid, uname in ((1, "admin"), (7, "林春"), (383, "陈毅清")):
        if cur_users.get(oid) != uname:
            raise RuntimeError(f"id={oid} 期望 {uname}，实际 {cur_users.get(oid)}")
    if cur_users.get(21) != "guitest":
        raise RuntimeError("id=21 不是 guitest，拒绝删除")
    # 各引用列里，3/207 必须为空（否则两段式落位会撞复合主键）
    for t, cs in NEW_ID_COLUMNS.items():
        for c in cs:
            cur.execute(f"SELECT COUNT(*) FROM `{t}` WHERE `{c}` IN (3,207)")
            if cur.fetchone()[0]:
                raise RuntimeError(f"{t}.{c} 已占用目标号 3/207，不能重建")
    # 恒等部分必须逐账号一致（旧 3/7/207 当前不在新库，跳过）
    skip_old = set(ID_MAP.values())
    for oid, uname in old_users.items():
        if oid in skip_old:
            continue
        if cur_users.get(oid) != uname:
            raise RuntimeError(f"id={oid} 新旧用户名不一致: 旧 {uname} / 新 {cur_users.get(oid)}")
    print(f"[前置] ✔ 196 个账号已恒等，仅 {ID_MAP} 需改，{DELETE_IDS} 需删")

    before = {f"{t}.{c}": dangling(cur, t, c)
              for t, cs in OLD_ID_COLUMNS.items() for c in cs}
    print(f"[前置] 旧 id 列悬空合计 {sum(before.values())} 行: {before}")

    if args.dry_run:
        print("\n--dry-run: 以下操作将被执行（未写库）")
        print(f"  1) users.id 两段式 {ID_MAP}；删除 id={sorted(DELETE_IDS)}")
        print(f"  2) 重映射 {sum(len(v) for v in NEW_ID_COLUMNS.values())} 个引用列: "
              f"{ {t: cs for t, cs in NEW_ID_COLUMNS.items()} }")
        print(f"  3) 重建后 users.id 应 == 旧库 id 集合；旧 id 列悬空应降到 "
              f"{before.get('jh_yyfq.opid', 0)} 行（opid 有 1 个旧库已删账号）")
        cn.rollback()
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("\n[1] 备份")
    bak = backup(cur, stamp)
    cn.commit()  # 备份读取结束，开启新事务

    try:
        print("[2] 关闭外键检查")
        cur.execute("SET FOREIGN_KEY_CHECKS=0")

        print("[3] 清理测试超管 id=21 及其关联")
        for t, cs in NEW_ID_COLUMNS.items():
            for c in cs:
                cur.execute(f"DELETE FROM `{t}` WHERE `{c}` IN "
                            f"({','.join(['%s'] * len(DELETE_IDS))})", tuple(DELETE_IDS))
        cur.execute("DELETE FROM users WHERE id IN "
                    f"({','.join(['%s'] * len(DELETE_IDS))})", tuple(DELETE_IDS))
        print(f"    users 删除 {cur.rowcount} 行")

        print("[4] users.id 两段式重编号")
        n = two_phase(cur, "users", "id", ID_MAP)
        print(f"    改了 {n} 行")

        print("[5] 引用列两段式重映射")
        for t, cs in NEW_ID_COLUMNS.items():
            for c in cs:
                k = two_phase(cur, t, c, ID_MAP)
                print(f"    {t}.{c}: {k} 行")

        cn.commit()
        print("[6] 恢复外键检查并重设自增")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        cur.execute("SELECT MAX(id) FROM users")
        cur.execute(f"ALTER TABLE users AUTO_INCREMENT = {cur.fetchone()[0] + 1}")
        cn.commit()
    except Exception:
        cn.rollback()
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        cn.commit()
        raise

    # ---- 验收 ----
    print("\n[验收]")
    cur.execute("SELECT id, username FROM users ORDER BY id")
    after = {int(r[0]): r[1] for r in cur.fetchall()}
    ok = True
    ok &= check("users.id 集合 == 旧 bb_user.id 集合", set(after) == set(old_users),
                (len(after), len(old_users)))
    ok &= check("每个 id 的用户名与旧库一致",
                all(after.get(k) == v for k, v in old_users.items()),
                [(k, v, after.get(k)) for k, v in old_users.items()
                 if after.get(k) != v][:5])
    ok &= check("测试超管已清除", "guitest" not in after.values())
    for t, cs in NEW_ID_COLUMNS.items():
        for c in cs:
            ok &= check(f"新 id 列 {t}.{c} 0 悬空", dangling(cur, t, c) == 0,
                        dangling(cur, t, c))
    after_dangling = {f"{t}.{c}": dangling(cur, t, c)
                      for t, cs in OLD_ID_COLUMNS.items() for c in cs}
    print(f"  旧 id 列悬空合计 {sum(after_dangling.values())} 行: {after_dangling}")
    ok &= check("旧 id 列悬空降到 1 行(opid 历史脏值)",
                sum(after_dangling.values()) == 1, after_dangling)
    semantic = {f"{t}.{c}": semantic_mismatch(cur, t, c, n)
                for t, c, n in SEMANTIC_PAIRS}
    print(f"  姓名快照语义错位合计 {sum(semantic.values())} 行: {semantic}")
    ok &= check("id 指向的人与姓名快照全部一致", sum(semantic.values()) == 0, semantic)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "backup": str(bak), "id_map": ID_MAP, "deleted_ids": sorted(DELETE_IDS),
        "before_dangling": before, "after_dangling": after_dangling,
        "semantic_mismatch": semantic, "users_rows": len(after), "passed": bool(ok),
    }
    (REPORT_DIR / f"user_ids_rebuild_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + ("✔ 重建完成且全部校验通过" if ok else "✘ 有校验未通过，请检查上方输出"))
    if not ok:
        sys.exit(1)


def check(label, cond, extra=""):
    print(f"  {'✔' if cond else '✘'} {label}" + ("" if cond else f"  {extra}"))
    return bool(cond)


if __name__ == "__main__":
    main()
