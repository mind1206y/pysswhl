"""为旧系统「传导完好率」菜单用户补授新系统权限(增量、可重复执行)。

背景:2026-11-15 用户全量迁移时传导 4 个模块尚未复刻,import_users.py 把旧菜单
68~71 列为「未复刻」不产生权限。模块复刻后需要给这些用户补上角色,否则登录后看不到菜单。
本脚本只**追加** legacy_cd* 角色与对应权限,不碰用户密码/部门/其它角色,
也不会删除任何现有数据;以后重跑 import_users.py(其 QX_TO_PERM 已同步)结果一致。

用法(backend 目录下):
    python -m scripts.grant_cd_perms --dry-run
    python -m scripts.grant_cd_perms
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pymysql

from app.core.config import settings
from scripts.import_users import (
    QX_TO_PERM, fetch_old_grants, load_user_map, split_tags,
)
from scripts.import_vehicles import old_conn

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"
CD_MENUS = {68: "cdwhl:view", 69: "cdgz:view", 70: "cddaxiu:view", 71: "cdbd:view"}
CD_ADMIN = set(CD_MENUS.values()) | {"cdwhl:manage"}
ROLE_PREFIX = "legacy_"


def old_cd_perms(ocur):
    """旧 userid → 应补的传导权限码集合。"""
    grants = fetch_old_grants(ocur)
    ocur.execute("SELECT [id], [otherqx] FROM [bb_user]")
    otherqx = {int(r[0]): r[1] or "" for r in ocur.fetchall()}
    out = defaultdict(set)
    for uid, qxids in grants.items():
        for qxid in qxids & CD_MENUS.keys():
            out[uid].add(CD_MENUS[qxid])
    for uid, tags_text in otherqx.items():
        tags = set(split_tags(tags_text))
        if "传导管理" in tags:
            out[uid].add("cdwhl:manage")
        if "admin" in tags:
            # 旧 otherqx 含 admin 是模块管理员,照 import_users.ADMIN_PERMS 给全部传导权限
            out[uid].update(CD_ADMIN)
    return {uid: sorted(codes) for uid, codes in out.items() if codes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
    args = parser.parse_args()

    user_map = load_user_map()
    conn = old_conn()
    try:
        wanted = old_cd_perms(conn.cursor())
    finally:
        conn.close()
    print(f"旧系统有传导权限的用户 {len(wanted)} 人, 权限码分布: "
          f"{sorted({c for v in wanted.values() for c in v})}")
    unmapped = sorted(uid for uid in wanted if uid not in user_map)
    if unmapped:
        print(f"  ⚠ user_map 缺失 {len(unmapped)} 人,跳过: {unmapped[:20]}")
    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    new = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    granted = defaultdict(list)
    try:
        cur = new.cursor()
        cur.execute("SELECT id, code, name FROM permissions")
        perms = {code: (pid, name) for pid, code, name in cur.fetchall()}
        missing_perms = sorted({c for v in wanted.values() for c in v} - set(perms))
        if missing_perms:
            raise SystemExit(f"权限码不存在,请先跑 scripts.init_db:{missing_perms}")

        role_ids = {}
        for code in sorted({c for v in wanted.values() for c in v}):
            role_code = ROLE_PREFIX + code.replace(":", "_")
            cur.execute("SELECT id FROM roles WHERE code=%s", (role_code,))
            row = cur.fetchone()
            if row:
                rid = row[0]
            else:
                cur.execute(
                    "INSERT INTO roles (name, code, remark, created_at) "
                    "VALUES (%s,%s,%s,NOW())",
                    (perms[code][1], role_code,
                     "旧系统传导菜单权限迁移生成 · 对应权限码 " + code),
                )
                rid = cur.lastrowid
            role_ids[code] = rid
            # ⚠ 角色只是容器,必须同时写 role_permission,否则用户权限为空
            cur.execute(
                "INSERT IGNORE INTO role_permission (role_id, permission_id) VALUES (%s,%s)",
                (rid, perms[code][0]),
            )

        cur.execute("SELECT id FROM users WHERE is_superuser=1")
        superusers = {r[0] for r in cur.fetchall()}
        for old_uid, codes in sorted(wanted.items()):
            new_uid = user_map.get(old_uid)
            if new_uid is None or new_uid in superusers:
                continue
            for code in codes:
                cur.execute(
                    "INSERT IGNORE INTO user_role (user_id, role_id) VALUES (%s,%s)",
                    (new_uid, role_ids[code]),
                )
                granted[new_uid].append(code)
        new.commit()

        cur.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_role ur "
            "JOIN roles r ON r.id=ur.role_id "
            "JOIN role_permission rp ON rp.role_id=r.id "
            "JOIN permissions p ON p.id=rp.permission_id "
            "WHERE p.code LIKE 'cd%'"
        )
        total_users = cur.fetchone()[0]
        print(f"  已给 {len(granted)} 个用户补授传导角色;库中拥有传导权限的用户共 {total_users} 人")
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "old_users": len(wanted), "granted_users": len(granted),
            "unmapped_old_userids": unmapped,
            "roles": {c: i for c, i in role_ids.items()},
            "detail": {str(k): v for k, v in granted.items()},
        }
        out = REPORT_DIR / "cd_perm_grant_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {out}")
    finally:
        new.close()


if __name__ == "__main__":
    main()
