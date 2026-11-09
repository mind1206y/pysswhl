"""旧 bb_user 联系人目录 -> 新库 sms_contact(短信发送手机号回退)。

新系统 users 是重建账号,历史计划里的专管员/发起人大多没有新账号。
短信发送先查 users.phone,再按姓名查本表,保证旧人员仍能收到提醒。

用法(backend 目录下):
    python -m scripts.import_sms_contacts --dry-run
    python -m scripts.import_sms_contacts
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings

FIELDS = ["id", "username", "unames", "tel", "zw", "otherqx"]


def old_conn():
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ocur = old_conn()
    try:
        cur = ocur.cursor()
        cur.execute("SELECT [id], [username], [unames], [tel], [zw], [otherqx] FROM [bb_user]")
        rows = [tuple(r) for r in cur.fetchall()]
    finally:
        ocur.close()

    print(f"读取 bb_user: {len(rows)} 条")
    if args.dry_run:
        print("[dry-run] 不写入数据库")
        return

    conn = new_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE `sms_contact`")
            sql = (
                "INSERT INTO `sms_contact` (`id`,`username`,`real_name`,`phone`,`zw`,`otherqx`)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
            )
            batch = []
            for rid, username, unames, tel, zw, otherqx in rows:
                batch.append((
                    int(rid), (username or "")[:50], (unames or "")[:50],
                    (tel or "")[:20], (zw or "")[:50], (otherqx or "")[:200],
                ))
                if len(batch) >= 500:
                    cur.executemany(sql, batch)
                    batch = []
            if batch:
                cur.executemany(sql, batch)
        conn.commit()
    finally:
        conn.close()
    print(f"写入 sms_contact: {len(rows)} 条")


if __name__ == "__main__":
    main()
