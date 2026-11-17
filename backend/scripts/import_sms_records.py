"""旧 db_plan.dbo.SmsRecord → 新库 sms_record(短信发送记录全量迁移)。

照旧 SmsRecordController 只读展示,历史记录(2024-11 起)照搬:
保留旧 id、TRUNCATE 可重导、重设自增。

用法(backend 目录下):
    python -m scripts.import_sms_records --dry-run
    python -m scripts.import_sms_records
"""

import argparse
import os

import pyodbc
import pymysql

from app.core.config import settings


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
        cur.execute(
            "SELECT [id], [lb], [riqi], [nr], [tel], [ren], [zt], [sender] "
            "FROM [SmsRecord] ORDER BY [id]"
        )
        rows = [tuple(r) for r in cur.fetchall()]
    finally:
        ocur.close()

    print(f"读取旧 SmsRecord: {len(rows)} 条")
    if args.dry_run:
        for r in rows[:3]:
            print("  样例:", r)
        print("[dry-run] 不写入数据库")
        return

    conn = new_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE `sms_record`")
            sql = (
                "INSERT INTO `sms_record` (`id`,`lb`,`riqi`,`nr`,`tel`,`ren`,`zt`,`sender`)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            batch = []
            for rid, lb, riqi, nr, tel, ren, zt, sender in rows:
                batch.append((
                    int(rid), (lb or "")[:50], riqi, (nr or "")[:500],
                    (tel or "")[:20], (ren or "")[:50], (zt or "")[:310],
                    (sender or "")[:50],
                ))
                if len(batch) >= 500:
                    cur.executemany(sql, batch)
                    batch = []
            if batch:
                cur.executemany(sql, batch)
            max_id = max((int(r[0]) for r in rows), default=0)
            if max_id:
                cur.execute(f"ALTER TABLE `sms_record` AUTO_INCREMENT = {max_id + 1}")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), MIN(riqi), MAX(riqi) FROM `sms_record`")
            print(f"写入 sms_record: {cur.fetchone()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
