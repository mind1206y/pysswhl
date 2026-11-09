"""准备测漏热力图底图瓦片(把旧系统的高德离线瓦片接入新系统)。

旧系统瓦片目录: E:/sswhl/sswhl/Content/Tiles/{z}/{x}/{y}.png (z10~17, GCJ-02)
新系统读取顺序: .env 的 CELOU_TILE_DIR → backend/assets/tiles → 旧系统目录(仅开发机回退)

部署到独立机器时必须把瓦片放进 backend/assets/tiles,否则底图为空(热力层仍可用)。

用法(在 backend 目录下执行):
    python -m scripts.prepare_heatmap_tiles --link     # 开发机:建目录联接,瞬时、不占额外磁盘
    python -m scripts.prepare_heatmap_tiles --copy     # 部署机:完整复制约 330MB / 6.5 万文件
    python -m scripts.prepare_heatmap_tiles --source D:/Tiles --copy
    python -m scripts.prepare_heatmap_tiles --copy --force   # 目标已存在时改名备份再建

本脚本只新增/改名,不删除任何瓦片。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEST = BASE / "assets" / "tiles"
DEFAULT_SOURCE = r"E:\sswhl\sswhl\Content\Tiles"


def main():
    ap = argparse.ArgumentParser(description="接入测漏热力图离线瓦片")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="旧系统 Content/Tiles 目录")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--copy", action="store_true", help="完整复制(部署机推荐)")
    mode.add_argument("--link", action="store_true", help="Windows 目录联接(开发机推荐)")
    ap.add_argument("--force", action="store_true", help="目标已存在时改名备份,不删除")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_dir():
        sys.exit(f"源目录不存在: {src}")
    count = sum(1 for _ in src.rglob("*.png"))
    if count == 0:
        sys.exit(f"源目录里没有 PNG 瓦片: {src}")
    print(f"源目录: {src}\n瓦片数: {count}")

    if DEST.exists() or DEST.is_symlink():
        if not args.force:
            sys.exit(f"目标已存在: {DEST}\n如需重建请先自行移走,或加 --force(仅改名备份)")
        backup = DEST.with_name(f"tiles.bak.{time.strftime('%Y%m%d%H%M%S')}")
        DEST.rename(backup)
        print(f"已备份原目录 → {backup}")

    DEST.parent.mkdir(parents=True, exist_ok=True)
    use_link = args.link or (not args.copy and os.name == "nt")
    if use_link and os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(DEST), str(src)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"创建目录联接失败: {r.stdout}{r.stderr}")
        print(f"已创建目录联接: {DEST} → {src}")
    else:
        shutil.copytree(src, DEST)
        print(f"已复制瓦片到: {DEST}")

    print("完成。后端无需重启即可读取;如另设目录,在 backend/.env 写 CELOU_TILE_DIR=<绝对路径>。")


if __name__ == "__main__":
    main()
