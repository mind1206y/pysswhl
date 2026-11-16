"""从已有镜像 tar 离线重建镜像(完全不联网)。

场景:base image 的层已经在本地镜像 tar 里,只是依赖清单变了(如补 exceptiongroup),
此时不需要再从 registry 拉 base,直接复用旧 tar 的前 N-1 层,只重做最后一层。

用法:
    .venv/Scripts/python.exe deploy/tools/rebuild_image_local.py

输入: sswhl-api-image.tar(旧镜像), backend/ requirements, deploy/wheels, frontend/dist
输出: sswhl-api-image.tar(覆盖,同 tag)
"""

import gzip
import hashlib
import io
import json
import shutil
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_image_offline as B  # noqa: E402  复用 pip_install / copy_tree / make_layer

OLD = B.OUT
BAK = B.BUILD / "image-old.tar"


def stream_out(tar, member_name, dst):
    """把 tar 里的成员原样写到文件"""
    with tar.extractfile(member_name) as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)


def layer_sha256(path):
    """层文件的 sha256;若为 gzip 则先解压(兼容两种 docker save 布局)"""
    with open(path, "rb") as f:
        head = f.read(2)
    h = hashlib.sha256()
    if head == b"\x1f\x8b":
        with gzip.open(path, "rb") as g:
            for chunk in iter(lambda: g.read(1024 * 1024), b""):
                h.update(chunk)
    else:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def main():
    if not OLD.exists():
        raise SystemExit(f"找不到旧镜像 {OLD}")

    # ---------- 1 读旧镜像结构
    B.log(f"读取旧镜像 {OLD.name}")
    with tarfile.open(OLD) as t:
        man = json.loads(t.extractfile("manifest.json").read())[0]
        cfg = json.loads(t.extractfile(man["Config"]).read())
        old_layers = man["Layers"]
        n_base = len(old_layers) - 1
        B.log(f"  共 {len(old_layers)} 层,复用前 {n_base} 个 base 层")
        if n_base < 1:
            raise SystemExit("旧镜像层数异常,无法判断 base 层")

        base_dir = B.BUILD / "base-layers"
        base_dir.mkdir(parents=True, exist_ok=True)
        base_files = []
        for i, ln in enumerate(old_layers[:n_base]):
            dst = base_dir / f"base{i}.tar"
            if not dst.exists() or dst.stat().st_size == 0:
                stream_out(t, ln, dst)
            base_files.append(dst)
        B.log(f"  已就位 base 层 {len(base_files)} 个,合计 "
              f"{sum(p.stat().st_size for p in base_files)/1048576:.1f}MB")

    base_diffs = cfg["rootfs"]["diff_ids"][:n_base]
    if len(base_diffs) != n_base:
        raise SystemExit("config 的 diff_ids 与 base 层数不匹配")

    # ---------- 2 重建最后一层
    if B.STAGE.exists():
        old = B.STAGE.with_name(f"stage-old-{int(time.time())}")
        B.STAGE.rename(old)
        B.log(f"旧 stage 已改名留档: {old.name}")
    B.STAGE.mkdir(parents=True)

    B.pip_install(B.STAGE / B.SITE)
    B.log("复制后端代码与前端产物")
    B.copy_tree(B.ROOT / "backend", B.STAGE / "app" / "backend", B.EXCLUDE_DIRS, B.EXCLUDE_FILES)
    B.copy_tree(B.ROOT / "frontend" / "dist", B.STAGE / "app" / "frontend" / "dist",
                B.EXCLUDE_DIRS, set())
    (B.STAGE / "app" / "backend" / "uploads").mkdir(parents=True, exist_ok=True)

    layer_gz, diff_id = B.make_layer(B.STAGE)

    # ---------- 3 改写 config
    # history 的非空条目必须与 diff_ids 一一对应。base 的 history 里带着"被替换那一层"
    # 的记录,这里先按非空计数截到 n_base,再补新增层的记录,否则 docker load 会报
    # "too many non-empty layers in History section"。
    kept, nonempty = [], 0
    for h in cfg["history"]:
        if not h.get("empty_layer"):
            nonempty += 1
            if nonempty > n_base:
                continue
        kept.append(h)
    cfg["history"] = kept

    cfg["rootfs"]["diff_ids"] = base_diffs + [f"sha256:{diff_id}"]
    cfg["history"].append({
        "created": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
        "created_by": "sswhl offline rebuild: reuse base layers + new deps layer",
        "comment": "rebuilt without docker daemon, no network",
    })
    cfg_bytes = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
    cfg_hex = hashlib.sha256(cfg_bytes).hexdigest()
    B.log(f"  config {cfg_hex[:19]}  diff_ids {len(cfg['rootfs']['diff_ids'])} 个")

    # ---------- 4 拼装
    B.log("拼装 docker load 用 tar")
    all_files = base_files + [layer_gz]
    names = [hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in all_files]
    manifest = [{
        "Config": f"{cfg_hex}.json",
        "RepoTags": B.IMG_TAGS,
        "Layers": [f"{n}/layer.tar" for n in names],
    }]
    repositories = {}
    for tag in B.IMG_TAGS:
        repo, ver = tag.rsplit(":", 1)
        repositories.setdefault(repo, {})[ver] = cfg_hex

    # 先备份旧镜像(构建失败时还能回退)
    if BAK.exists():
        BAK.unlink()
    shutil.copy2(OLD, BAK)
    B.log(f"  旧镜像已备份到 {BAK.name}")

    tmp = B.OUT.with_suffix(".tar.part")
    with tarfile.open(tmp, "w", format=tarfile.GNU_FORMAT) as t:
        def addfile(name, data=None, path=None):
            info = tarfile.TarInfo(name)
            if path is not None:
                info.size = path.stat().st_size
                info.mtime = int(time.time())
                with open(path, "rb") as f:
                    t.addfile(info, f)
            else:
                info.size = len(data)
                info.mtime = int(time.time())
                t.addfile(info, io.BytesIO(data))

        addfile("manifest.json", json.dumps(manifest, indent=2).encode())
        addfile("repositories", json.dumps(repositories, indent=2).encode())
        addfile(f"{cfg_hex}.json", cfg_bytes)
        for n, p in zip(names, all_files):
            addfile(f"{n}/layer.tar", path=p)

    if B.OUT.exists():
        B.OUT.unlink()
    tmp.rename(B.OUT)
    B.log(f"输出 {B.OUT.name} ({B.OUT.stat().st_size/1048576:.1f}MB)")

    # ---------- 5 自检
    B.log("自检:逐层 sha256 与 diff_ids 对齐")
    with tarfile.open(B.OUT) as t:
        m = json.loads(t.extractfile("manifest.json").read())[0]
        cfg2 = json.loads(t.extractfile(m["Config"]).read())
        diffs = cfg2["rootfs"]["diff_ids"]
        if len(diffs) != len(m["Layers"]):
            raise SystemExit(f"层数 {len(m['Layers'])} 与 diff_ids {len(diffs)} 不一致")
        for i, ln in enumerate(m["Layers"]):
            member = t.extractfile(ln)
            h = hashlib.sha256()
            with gzip.GzipFile(fileobj=member) as gz:
                for chunk in iter(lambda: gz.read(1024 * 1024), b""):
                    h.update(chunk)
            got = "sha256:" + h.hexdigest()
            ok = got == diffs[i]
            B.log(f"  layer{i} {'OK' if ok else 'MISMATCH'}"
                  + ("" if ok else f" 期望 {diffs[i][:19]} 实得 {got[:19]}"))
            if not ok:
                raise SystemExit("层校验失败")

    # 确认 exceptiongroup 真的进了 site-packages
    last = m["Layers"][-1]
    with tarfile.open(B.OUT) as t:
        member = t.extractfile(last)
        found = False
        with gzip.GzipFile(fileobj=member) as gz, tarfile.open(fileobj=gz) as lt:
            for mem in lt:
                if "/site-packages/exceptiongroup/__init__.py" in mem.name:
                    found = True
                    break
    B.log(f"  exceptiongroup 在 site-packages 内: {'是' if found else '否'}")
    if not found:
        raise SystemExit("exceptiongroup 未打进镜像,请检查 wheels 与 requirements-linux.txt")
    B.log("完成。服务器上执行: sudo docker load -i sswhl-api-image.tar")


if __name__ == "__main__":
    main()
