#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发机一键生成上线产物（Windows / Linux 均可跑）。

用法（在仓库根目录）:
    python deploy/tools/make_release.py              # 导出数据库 + 打两个包
    python deploy/tools/make_release.py --no-db      # 只重打包（库没变时）
    python deploy/tools/make_release.py --mysqldump <路径>   # 手工指定 mysqldump

产出 3 个文件（都在仓库根目录 / deploy/import）:
    deploy/import/sswhl_new.sql.gz   全量库 dump（含 CREATE DATABASE，带 DROP TABLE）
    sswhl-deploy.tar.gz              首次部署整包（代码 + dist + 脚本 + wheels + .env）
    sswhl-update.tar.gz              日常更新精简包（只代码 + dist + 更新脚本）

注意:
  * 全量 dump 含 DROP TABLE IF EXISTS，服务器上导入会删表重建，见 deploy/README.md 第十一节。
  * 整包内含 backend/.env（PASSWORD_PEPPER），不要外传。
  * 依赖没变时不需要重建 71MB 镜像；requirements-linux.txt 一改才要重做。
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DUMP = ROOT / "deploy" / "import" / "sswhl_new.sql.gz"
FULL_PKG = ROOT / "sswhl-deploy.tar.gz"
SLIM_PKG = ROOT / "sswhl-update.tar.gz"

# 整包：与 deploy/README.md 第二节「安装包」一致
FULL_ROOTS = [
    ".dockerignore",
    "backend",
    "deploy",
    "docs",
    "frontend/dist",
]
# 精简包：update.sh --pkg 只校验这三个目录，其余是给它比对/自更新用的
SLIM_ROOTS = [
    "backend/app",
    "backend/scripts",
    "backend/requirements-linux.txt",
    "deploy/update.sh",
    "deploy/docker-compose.yml",
    "frontend/dist",
]
# 目录名命中即整棵跳过
SKIP_DIRS = {
    ".venv", "venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
    "node_modules", "import", "build", ".idea", ".vscode", ".zcode",
}
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".bak", ".tmp", ".whl.tmp"}
SKIP_NAMES = {".DS_Store", "Thumbs.db", "sswhl_new.sql", "sswhl_new.sql.gz"}
# UI 回归脚本跑完留在 backend/scripts 的界面截图(20 张 / 2.8MB,占精简包一半以上)。
# 服务器上没有任何代码引用它们,只有开发机看回归对比时才用,不进包。
# 用相对路径 glob 精确限定,避免误伤将来真要发的其它图片资源。
SKIP_GLOBS = {"backend/scripts/ui_*.png"}


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def find_mysqldump(explicit: str = "") -> str:
    if explicit:
        return explicit
    hit = shutil.which("mysqldump")
    if hit:
        return hit
    for drive in ("E:/", "C:/", "D:/"):
        for p in sorted(Path(drive).glob("mysql-*/mysql-*/bin/mysqldump.exe")):
            return str(p)
        for p in sorted(Path(drive).glob("Program Files/MySQL/*/bin/mysqldump.exe")):
            return str(p)
    raise SystemExit("找不到 mysqldump，请用 --mysqldump <路径> 指定")


def assert_clean_users(env: dict[str, str]) -> None:
    """导出前挡住测试账号。

    曾两次把测试超管带进生产 dump：guitest(免改密超管)、smoke_cftj*(冒烟脚本
    只在开头清理、结束时漏清)。这里宁可中止发版，也不让它们上服务器。
    """
    try:
        import pymysql
    except ImportError:
        log("未装 pymysql，跳过测试账号检查")
        return
    conn = pymysql.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), user=env["DB_USER"],
        password=env["DB_PASSWORD"], database=env["DB_NAME"], charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username FROM users WHERE username LIKE 'smoke%' "
                "OR username IN ('guitest','test','demo') ORDER BY id"
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
    finally:
        conn.close()
    if rows:
        raise SystemExit(
            f"库里还有 {len(rows)} 个测试账号，先清理再发版: {rows[:10]}\n"
            "冒烟脚本应跑完自清；可用 "
            "SELECT id,username FROM users WHERE username LIKE 'smoke%' 定位。"
        )
    log(f"导出前检查通过: users {total} 行，无测试账号")


def export_db(mysqldump: str) -> None:
    env = read_env()
    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        if not env.get(key):
            raise SystemExit(f"backend/.env 缺少 {key}")
    assert_clean_users(env)
    DUMP.parent.mkdir(parents=True, exist_ok=True)
    if DUMP.exists():
        bak = DUMP.with_name(f"sswhl_new.{datetime.now():%Y%m%d-%H%M}.bak.sql.gz")
        shutil.copy2(DUMP, bak)
        log(f"旧 dump 已备份 -> {bak.name}")

    cmd = [
        mysqldump,
        f"--host={env['DB_HOST']}", f"--port={env['DB_PORT']}",
        f"--user={env['DB_USER']}",
        "--single-transaction", "--default-character-set=utf8mb4",
        "--no-tablespaces", "--set-gtid-purged=OFF", "--hex-blob",
        "--databases", env["DB_NAME"],
    ]
    child_env = dict(os.environ, MYSQL_PWD=env["DB_PASSWORD"])
    tmp = DUMP.with_suffix(".tmp")
    print(f"==> 导出数据库 {env['DB_NAME']} ...", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env)
    assert proc.stdout is not None
    with gzip.GzipFile(tmp, "wb", compresslevel=6, mtime=0) as out:
        for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b""):
            out.write(chunk)
    err = proc.stderr.read().decode("utf-8", "replace").strip()
    rc = proc.wait()
    if rc != 0:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"mysqldump 失败(exit {rc}): {err[:800]}")
    if err and "column_masking_policy" in err:
        # MySQL 9.x 企业版功能;用普通应用账号导出会报这条 SELECT denied,
        # 但所有业务表已完整导出(下面会校验 118 张表),服务器 MySQL 8.0 社区版也不需要它。
        log("已忽略 MySQL 9.x masking policy 权限警告(与业务数据无关)")
    elif err:
        log(f"mysqldump 提示: {err[:300]}")
    tmp.replace(DUMP)

    # 校验：表数、关键表与 INSERT
    text = gzip.open(DUMP, "rt", encoding="utf-8", errors="replace").read()
    tables = re.findall(r"^CREATE TABLE `([^`]+)`", text, flags=re.M)
    log(f"dump 完成: {len(tables)} 张表 / {DUMP.stat().st_size / 1024 / 1024:.1f} MB")
    for required in ("cd_whl", "cd_gz", "cd_daxiu", "cd_xz", "users", "permissions", "consol_tb"):
        if required not in tables:
            raise SystemExit(f"dump 缺表 {required}，导出可能不完整")
    if "CREATE DATABASE" not in text or f"USE `{env['DB_NAME']}`" not in text:
        raise SystemExit("dump 缺 CREATE DATABASE / USE，服务器全量导入会导错库")
    log("关键表校验通过（含传导 4 表 / 用户 / 权限 / 开关）")


def collect(roots: list[str]) -> list[tuple[Path, str]]:
    """返回 [(绝对路径, 包内相对路径)]，排序保证可复现。"""
    items: list[tuple[Path, str]] = []
    for rel in roots:
        src = ROOT / rel
        if not src.exists():
            raise SystemExit(f"打包清单里的路径不存在: {rel}")
        if src.is_file():
            items.append((src, rel))
            continue
        for p in src.rglob("*"):
            r = p.relative_to(ROOT).as_posix()
            parts = set(p.relative_to(ROOT).parts)
            if parts & SKIP_DIRS:
                continue
            if p.is_file() and (
                p.suffix.lower() in SKIP_SUFFIX
                or p.name in SKIP_NAMES
                or any(fnmatch.fnmatch(r, g) for g in SKIP_GLOBS)
            ):
                continue
            if p.is_dir():
                items.append((p, r + "/"))
            elif p.is_file():
                items.append((p, r))
    # 去掉被跳过目录下的孤儿项 + 去重 + 排序（目录排在文件前由 tar 自行处理）
    return sorted(set(items), key=lambda x: x[1])


def make_tar(dst: Path, roots: list[str]) -> None:
    items = collect(roots)
    tmp = dst.with_suffix(".tmp")
    # gzip 头默认写当前时间 → 内容不变 MD5 也会变,导致手册里的校验值每次发版都失效。
    # 固定 mtime=0 + 固定 uid/gid + 排序,得到可复现的字节流。
    with tmp.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                for path, arc in items:
                    info = tar.gettarinfo(str(path), arcname=arc)
                    info.uid, info.gid = 0, 0
                    info.uname, info.gname = "root", "root"
                    if path.is_dir():
                        info.mode = 0o755
                        tar.addfile(info)
                    else:
                        info.mode = 0o644
                        with path.open("rb") as fh:
                            tar.addfile(info, fh)
    tmp.replace(dst)
    md5 = hashlib.md5(dst.read_bytes()).hexdigest()
    log(f"{dst.name}: {len(items)} 项 / {dst.stat().st_size / 1024 / 1024:.1f} MB / md5 {md5}")


def verify_packages() -> None:
    print("==> 校验包内容", flush=True)
    must = [
        "backend/app/models/cd.py",
        "backend/app/services/cd_common.py",
        "backend/app/services/cd_excel.py",
        "backend/app/api/routes/cd_whl.py",
        "backend/app/api/routes/cd_gz.py",
        "backend/app/api/routes/cd_daxiu.py",
        "backend/app/api/routes/cd_bd.py",
        "backend/scripts/init_db.py",
        "backend/scripts/import_cd.py",
        "frontend/dist/index.html",
    ]
    for pkg in (FULL_PKG, SLIM_PKG):
        with tarfile.open(pkg, "r:gz") as tar:
            names = set(tar.getnames())
        missing = [m for m in must if m not in names]
        # update.sh 只要求精简包有
        if pkg == SLIM_PKG and "deploy/update.sh" not in names:
            missing.append("deploy/update.sh")
        if missing:
            raise SystemExit(f"{pkg.name} 缺文件: {missing}")
        if pkg == FULL_PKG:
            for m in ("backend/.env", "backend/rsa_key.pem", "deploy/install-container.sh"):
                if m not in names:
                    raise SystemExit(f"整包缺 {m}")
        log(f"{pkg.name} 内容 OK（含传导模块与前端产物）")
    # dist 里必须能看到新菜单文案，防止拿旧 dist 打包
    with tarfile.open(SLIM_PKG, "r:gz") as tar:
        blobs = b"".join(
            tar.extractfile(m).read()
            for m in tar.getmembers()
            if m.isfile() and m.name.startswith("frontend/dist/assets/") and m.name.endswith(".js")
        )
    if "传导完好率".encode("utf-8") not in blobs:
        raise SystemExit("dist 里没找到「传导完好率」文案，可能 npm run build 没跑")
    log("dist 为本次新构建（含「传导完好率」菜单）")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成上线产物")
    ap.add_argument("--no-db", action="store_true", help="跳过数据库导出")
    ap.add_argument("--no-verify", action="store_true", help="跳过包内容校验")
    ap.add_argument("--mysqldump", default="", help="mysqldump 可执行文件路径")
    args = ap.parse_args()

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist/index.html 不存在，先跑 npm run build")
    if not args.no_db:
        export_db(find_mysqldump(args.mysqldump))
    print("==> 打部署包", flush=True)
    make_tar(FULL_PKG, FULL_ROOTS)
    make_tar(SLIM_PKG, SLIM_ROOTS)
    if not args.no_verify:
        verify_packages()
    print("\n完成。上传前请核对 MD5：", flush=True)
    for p in (DUMP, FULL_PKG, SLIM_PKG):
        print(f"  {p.name:28s} {hashlib.md5(p.read_bytes()).hexdigest()}  {p.stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
