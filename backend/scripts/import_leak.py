"""测漏笔记历史数据导入:旧库 db_plan.dbo.LeakRecord / LeakFile → 新库同名表。

约定(见 docs/数据迁移约定.md):
- 表名/字段名沿用旧库,保留旧主键 id,导完调整自增起点
- 脚本可重复执行(逐表 TRUNCATE 重导),支持 --dry-run
- 远程 115 文件 URL 原样保留(新系统通过 /api/leak/files 代理访问)
- 本地 /Uploads/Leak/... 文件可用 --copy-files 从旧系统 Upload 目录复制

用法(backend 目录下):
    python -m scripts.import_leak --dry-run
    python -m scripts.import_leak
    python -m scripts.import_leak --copy-files "E:/sswhl/sswhl/Uploads"

依赖:pyodbc + ODBC Driver 17 for SQL Server(不要用 pymssql)。
"""

import argparse
import os
import shutil
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

LEAK_RECORD = [
    "Id", "Title", "Location", "PipelineInfo", "DetectTime", "DetectUser",
    "Pressure", "Area", "FlowRate", "Remark", "Creator", "CreateTime",
    "AreaExpression", "LeakMethod", "Time1", "Time2", "Time3", "AvgTime",
    "BucketLiters", "paicha", "PaichaType", "MeterTime", "MeterVolume",
    "ExperienceDesc", "ExperienceFlow", "DetectCom", "FlowMeta", "QuantifyTime",
]
LEAK_FILE = [
    "Id", "LeakId", "FileType", "FileUrl", "FileName", "CreateTime",
    "FileId", "ThumbUrl",
]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},"
        f"{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};"
        f"PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def fetch_all(ocur, table, fields):
    ocur.execute(f"SELECT {', '.join('[' + f + ']' for f in fields)} FROM [{table}]")
    rows = [tuple(r) for r in ocur.fetchall()]
    print(f"  {table}: 旧库 {len(rows)} 条")
    return rows


def write_table(ncur, table, fields, rows):
    ncur.execute(f"TRUNCATE TABLE `{table}`")
    placeholders = ", ".join(["%s"] * len(fields))
    sql = (f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in fields)
           + f") VALUES ({placeholders})")
    batch = []
    for row in rows:
        batch.append(tuple(row))
        if len(batch) >= 500:
            ncur.executemany(sql, batch)
            batch = []
    if batch:
        ncur.executemany(sql, batch)
    max_id = max((row[0] for row in rows), default=0)
    if max_id:
        ncur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")
    print(f"  {table}: 写入 {len(rows)} 条,自增起点 {max_id + 1}")


def is_remote(url: str) -> bool:
    return bool(url) and str(url).lower().startswith(("http://", "https://"))


def local_rel(url: str) -> str:
    rel = str(url or "").replace("\\", "/").lstrip("/")
    lowered = rel.lower()
    if lowered.startswith("uploads/"):
        rel = rel[len("uploads/"):]
    elif lowered.startswith("upload/"):
        rel = rel[len("upload/"):]
    return rel


def copy_files(conn, source: Path):
    cur = conn.cursor()
    urls = []
    cur.execute("SELECT FileUrl, ThumbUrl FROM LeakFile")
    for file_url, thumb_url in cur.fetchall():
        for url in (file_url, thumb_url):
            if url and not is_remote(url):
                urls.append(url)
    urls = sorted(set(urls))

    dest_root = Path(settings.UPLOAD_DIR)
    ok, missing = 0, 0
    missing_samples = []
    for url in urls:
        rel = local_rel(url)
        if not rel:
            continue
        candidates = [
            source / rel,
            source / "Uploads" / rel,
            source / "Upload" / rel,
        ]
        if rel.lower().startswith("leak/"):
            candidates.append(source / rel[len("Leak/"):])
        src = next((p for p in candidates if p.is_file()), None)
        if src is None:
            missing += 1
            if len(missing_samples) < 5:
                missing_samples.append(rel)
            continue
        dst = dest_root / rel
        if src.resolve() == dst.resolve():
            ok += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        ok += 1
    print(f"  本地附件复制:成功 {ok} 个,源目录缺失 {missing} 个")
    if missing_samples:
        print(f"  缺失样例: {missing_samples}")
    print("  远程 115 附件保持 URL 不变,新系统会通过代理访问")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--copy-files", default="", help="旧系统 Upload 根目录,用于复制本地附件")
    args = parser.parse_args()

    conn = old_conn()
    try:
        ocur = conn.cursor()
        records = fetch_all(ocur, "LeakRecord", LEAK_RECORD)
        files = fetch_all(ocur, "LeakFile", LEAK_FILE)

        print("--- 数据核对 ---")
        titles = [r[LEAK_RECORD.index("Title")] for r in records]
        creators = {}
        for r in records:
            key = r[LEAK_RECORD.index("Creator")] or ""
            creators[key] = creators.get(key, 0) + 1
        teams = {}
        for r in records:
            key = r[LEAK_RECORD.index("DetectCom")] or ""
            teams[key] = teams.get(key, 0) + 1
        methods = {}
        for r in records:
            key = r[LEAK_RECORD.index("LeakMethod")] or ""
            methods[key] = methods.get(key, 0) + 1
        flow_idx = LEAK_RECORD.index("FlowRate")
        flow_sum = sum(float(r[flow_idx] or 0) for r in records)
        remote = sum(1 for r in files if is_remote(r[LEAK_FILE.index("FileUrl")]))
        local = len(files) - remote
        types = {}
        for r in files:
            key = r[LEAK_FILE.index("FileType")] or ""
            types[key] = types.get(key, 0) + 1
        print(f"  记录人: {creators}")
        print(f"  测漏队伍: {teams}")
        print(f"  计量方法: {methods}")
        print(f"  漏量合计: {flow_sum:.2f}")
        print(f"  附件: 远程 {remote} / 本地 {local},类型 {types}")
        print(f"  标题非空: {sum(1 for t in titles if t)} / {len(titles)}")

        if args.dry_run:
            print("dry-run 结束,未写入")
            return

        new = pymysql.connect(
            host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
            password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
        )
        try:
            ncur = new.cursor()
            # LeakFile 无物理外键,但先清附件再清主表更符合直觉
            ncur.execute("TRUNCATE TABLE `LeakFile`")
            new.commit()
            write_table(ncur, "LeakRecord", LEAK_RECORD, records)
            write_table(ncur, "LeakFile", LEAK_FILE, files)
            new.commit()
            print("  数据写入完成")
        finally:
            new.close()

        if args.copy_files:
            copy_files(conn, Path(args.copy_files))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    print("完成")
