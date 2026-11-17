"""为旧系统「短信发送」(bb_quanx 80, /SmsRecord)菜单用户补授新系统 sms:view 权限。

增量、可重复执行;只追加 legacy_sms_view 角色与权限绑定,不碰用户其它数据。
import_users.py 的 QX_TO_PERM 已同步 80→sms:view,重跑用户导入结果一致。

用法(backend 目录下):
    python -m scripts.grant_sms_perms --dry-run
    python -m scripts.grant_sms_perms
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import pymysql

from app.core.config import settings
from scripts.import_vehicles import old_conn

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"
SMS_QXID = 80  # 旧 bb_quanx「短信发送」
ROLE_CODE = "legacy_sms_view"
PERM_CODE = "sms:view"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
    args = parser.parse_args()

    # 旧库:有「短信发送」菜单的用户
    oc = old_conn()
    try:
        cur = oc.cursor()
        cur.execute(
            "SELECT u.[id], u.[username], u.[unames] FROM bb_qxfenpei q "
            "JOIN bb_user u ON u.[id]=q.[userid] WHERE q.[qxid]=?", (SMS_QXID,)
        )
        old_users = [(int(r.id), r.username, r.unames) for r in cur.fetchall()]
    finally:
        oc.close()

    mapping = json.loads(
        (REPORT_DIR / "user_map.json").read_text(encoding="utf-8")
    )["user_map"]
    wanted = []
    unmapped = []
    for old_id, username, unames in old_users:
        new_id = mapping.get(str(old_id))
        if new_id is None:
            unmapped.append((old_id, username))
        else:
            wanted.append((old_id, new_id, username, unames))
    print(f"旧系统有「短信发送」菜单的用户 {len(old_users)} 人 → 可映射 {len(wanted)} 人")
    for old_id, new_id, username, unames in wanted:
        print(f"  旧#{old_id} {username}({unames}) → 新#{new_id}")
    if unmapped:
        print(f"  ⚠ user_map 缺失,跳过: {unmapped}")
    if args.dry_run:
        print("dry-run 结束,未写入")
        return

    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM permissions WHERE code=%s", (PERM_CODE,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"权限码 {PERM_CODE} 不存在,请先跑 scripts.init_db")
        pid = row[0]

        cur.execute("SELECT id FROM roles WHERE code=%s", (ROLE_CODE,))
        row = cur.fetchone()
        if row:
            rid = row[0]
        else:
            cur.execute(
                "INSERT INTO roles (name, code, remark, created_at) "
                "VALUES (%s,%s,%s,NOW())",
                ("短信记录查看", ROLE_CODE,
                 "旧系统「短信发送」菜单权限迁移生成 · 对应权限码 sms:view"),
            )
            rid = cur.lastrowid
        # ⚠ 角色只是容器,必须同时写 role_permission,否则用户权限为空
        cur.execute(
            "INSERT IGNORE INTO role_permission (role_id, permission_id) VALUES (%s,%s)",
            (rid, pid),
        )

        cur.execute("SELECT id FROM users WHERE is_superuser=1")
        superusers = {r[0] for r in cur.fetchall()}
        granted = []
        for old_id, new_id, username, _unames in wanted:
            if new_id in superusers:
                continue
            cur.execute(
                "INSERT IGNORE INTO user_role (user_id, role_id) VALUES (%s,%s)",
                (new_id, rid),
            )
            granted.append((old_id, new_id, username))
        conn.commit()
        print(f"  已补授 {len(granted)} 人 legacy_sms_view 角色")

        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "old_users": old_users, "granted": granted, "unmapped": unmapped,
            "role_id": rid, "permission_id": pid,
        }
        out = REPORT_DIR / "sms_perm_grant_report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {out}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
