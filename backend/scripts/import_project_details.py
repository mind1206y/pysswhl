"""工程管理子表历史数据导入:进度/问题/附件 (+可选复制附件物理文件)。

按 docs/数据迁移约定.md:表名/字段沿用旧库,保留旧主键 id,可重复执行(TRUNCATE 重导)。

用法(backend 目录下):
    python -m scripts.import_project_details            # 导三张子表
    python -m scripts.import_project_details --dry-run  # 只统计
    python -m scripts.import_project_details --copy-files [源目录]
                                                       # 再从旧系统 Upload/GongChengGuanliFujian
                                                       # 复制附件文件到新目录(可重复,已存在跳过)

附件说明:旧库 283 条记录的文件存在旧系统生产服务器(本机源码目录里没有),
先导记录;以后拿到文件目录后用 --copy-files 补齐,下载即恢复可用。

旧库连接参数同 import_projects.py(环境变量 OLD_DB_*)。
"""

import argparse
import os
import shutil
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

TABLES = {
    "gongchenggl_jindu": [
        "id", "gcglid", "jindu", "riqi", "jinduzhuangtai",
        "CreateUser", "UpdateUser", "UpdateTime",
    ],
    "gongchenggl_jianguan": [
        "id", "gcglid", "qingkuangshuoming", "riqi", "chulshuoming", "isjiejue",
        "CreateUser", "UpdateUser", "UpdateTime",
    ],
    # url 入库时去掉旧前缀,只存文件名(与新系统磁盘布局一致)
    "gongchenggl_fujian": [
        "id", "gcglid", "url", "wjname", "size", "CreateTime", "CreateUser",
    ],
}

FUJIAN_SUBDIR = "GongChengGuanliFujian"
# 旧库 url 形如 /Upload/GongChengGuanliFujian/xxx.jpg,取最后一段文件名
OLD_URL_PREFIX = "/Upload/GongChengGuanliFujian/"


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def transform(table, fields, row):
    if table == "gongchenggl_fujian":
        row = list(row)
        i = fields.index("url")
        url = row[i] or ""
        if url.startswith(OLD_URL_PREFIX):
            url = url[len(OLD_URL_PREFIX):]
        row[i] = url
    return tuple(row)


def copy_files(src_dir: str):
    src = Path(src_dir)
    dst = Path(settings.UPLOAD_DIR) / FUJIAN_SUBDIR
    dst.mkdir(parents=True, exist_ok=True)
    files = [p for p in src.iterdir() if p.is_file()] if src.exists() else []
    if not src.exists():
        print(f"源目录不存在:{src}")
        return
    copied = skipped = 0
    for p in files:
        target = dst / p.name
        if target.exists():
            skipped += 1
            continue
        shutil.copy2(p, target)
        copied += 1
    print(f"附件文件复制完成:新复制 {copied},已存在跳过 {skipped},源目录共 {len(files)} 个文件")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument(
        "--copy-files", nargs="?", const="default", metavar="源目录",
        help="复制附件文件;不带参数则用默认源 E:/sswhl/sswhl/Upload/GongChengGuanliFujian",
    )
    args = parser.parse_args()

    if args.copy_files:
        src = args.copy_files if args.copy_files != "default" else "E:/sswhl/sswhl/Upload/GongChengGuanliFujian"
        copy_files(src)
        if not args.dry_run:
            return

    conn = old_conn()
    try:
        cur = conn.cursor()
        all_rows = {}
        for table, fields in TABLES.items():
            cur.execute(f"SELECT {', '.join(fields)} FROM {table}")
            rows = [transform(table, fields, r) for r in cur.fetchall()]
            all_rows[table] = (fields, rows)
            print(f"{table}: 旧库 {len(rows)} 条")

        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            for table in TABLES:
                fields, rows = all_rows[table]
                ncur.execute(f"TRUNCATE TABLE {table}")
                if rows:
                    placeholders = ", ".join(["%s"] * len(fields))
                    ncur.executemany(
                        f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})", rows
                    )
                    max_id = max(r[0] for r in rows)
                    ncur.execute(f"ALTER TABLE {table} AUTO_INCREMENT = {max_id + 1}")
                    print(f"{table}: 已导入 {len(rows)} 条,自增起点 {max_id + 1}")
                else:
                    print(f"{table}: 旧库为空,已清空目标表")
            new.commit()
        finally:
            new.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
