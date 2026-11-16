"""在无 Docker 的机器上离线组装 docker load 可用的镜像 tar。

原理：base image 的各层(sha256 校验后)原样复用，只自建最上面一层
(依赖 + 代码 + 前端产物)，再重写 config.json 的 rootfs.diff_ids / env / cmd，
最后按 docker save 的布局拼成 tar：
    manifest.json / repositories / <config>.json / <layer>/layer.tar

用法： .venv/Scripts/python.exe deploy/tools/build_image_offline.py
"""

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"E:/pysswhl")
BUILD = ROOT / "build"
BLOBS = BUILD / "blobs"
STAGE = BUILD / "stage"
OUT = ROOT / "sswhl-api-image.tar"

REG = "https://docker.1panel.live/v2/library/python"
MANIFEST_DIGEST = "sha256:7b6bd969dda3ecfca0655524e338b57a8b8cd692a9362e3d55b5a3ef49b07256"
# 只保留自己的 tag。早前这里还带 "python:3.10-slim",load 到目标机后会把服务器上
# 已有的同名镜像 tag 顶到我们的镜像上,污染别人基于该 tag 的构建,故去掉。
IMG_TAGS = ["sswhl-api:1.0"]
SITE = "usr/local/lib/python3.10/site-packages"
EXCLUDE_DIRS = {".venv", "__pycache__", "uploads", ".pytest_cache", ".mypy_cache"}
EXCLUDE_FILES = {".env", "rsa_key.pem"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http_get(url, dst=None):
    req = urllib.request.Request(url, headers={"User-Agent": "docker/24.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        if dst is None:
            return r.read()
        with open(dst, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 512)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_manifest():
    acc = ",".join([
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ])
    req = urllib.request.Request(
        f"{REG}/manifests/{MANIFEST_DIGEST}",
        headers={"Accept": acc, "User-Agent": "docker/24.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_blob(digest, size):
    dst = BLOBS / digest.replace("sha256:", "")
    if dst.exists() and dst.stat().st_size == size:
        got = sha256_file(dst)
        if got == digest.replace("sha256:", ""):
            log(f"  复用缓存 {dst.name[:12]} ({size/1048576:.1f}MB)")
            return dst
    log(f"  下载 {digest[:19]} ({size/1048576:.1f}MB)")
    http_get(f"{REG}/blobs/{digest}", dst)
    got = sha256_file(dst)
    if got != digest.replace("sha256:", ""):
        raise SystemExit(f"校验失败 {dst.name}: {got}")
    return dst


def check_base_layout(layer_files):
    """确认 base image 的 Python 装在 /usr/local(官方 python 镜像的约定)"""
    want = [f"{SITE}/", "usr/local/bin/python3.10"]
    found = {w: False for w in want}
    for lf in layer_files:
        with tarfile.open(lf, "r:*") as t:
            for m in t:
                for w in want:
                    if m.name.lstrip("./").startswith(w):
                        found[w] = True
        if all(found.values()):
            return True, found
    return all(found.values()), found


def pip_install(target):
    req = ROOT / "backend" / "requirements-linux.txt"
    wheels = ROOT / "deploy" / "wheels"
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-index", f"--find-links={wheels}",
        "-r", str(req), "--target", str(target),
        "--platform", "manylinux2014_x86_64",
        "--python-version", "3.10",
        "--implementation", "cp",
        "--abi", "cp310",
        "--only-binary=:all:",
        "--no-compile", "--no-warn-script-location", "--quiet",
    ]
    log("安装 Linux 版依赖到镜像内 site-packages(离线)")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("pip 安装失败")
    n = len([p for p in target.iterdir() if p.is_dir()])
    log(f"  已安装 {n} 个包目录")


def copy_tree(src, dst, exclude_dirs, exclude_files):
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in exclude_dirs for part in rel.parts):
            continue
        if p.name in exclude_files:
            continue
        if p.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        elif p.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)


def make_layer(stage):
    """返回 (layer.tar.gz 路径, diff_id 十六进制)"""
    raw = BUILD / "layer-raw.tar"
    log("打包新增层")
    with tarfile.open(raw, "w", format=tarfile.GNU_FORMAT) as t:
        for p in sorted(stage.rglob("*"), key=lambda x: x.relative_to(stage).as_posix()):
            arc = p.relative_to(stage).as_posix()
            if p.is_symlink():
                continue
            info = t.gettarinfo(str(p), arcname=arc)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            if p.is_dir():
                t.addfile(info)
            elif p.is_file():
                with open(p, "rb") as f:
                    t.addfile(info, f)
    diff_id = sha256_file(raw)
    gz = BUILD / "layer.tar.gz"
    with open(raw, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo, 1024 * 1024)
    log(f"  层大小 {gz.stat().st_size/1048576:.1f}MB (未压缩 {raw.stat().st_size/1048576:.1f}MB)")
    return gz, diff_id


def main():
    BLOBS.mkdir(parents=True, exist_ok=True)
    if STAGE.exists():
        # 不直接 rmtree(上千个文件会触发安全策略拦批量删除),改为改名留档;
        # 磁盘紧张时手工清理 build/stage-old-* 即可
        old = STAGE.with_name(f"stage-old-{int(time.time())}")
        STAGE.rename(old)
        log(f"旧 stage 已改名留档: {old.name}")
    STAGE.mkdir(parents=True)

    log("读取 base image 清单")
    man = fetch_manifest()
    layers = man["layers"]
    log(f"  {len(layers)} 个层, 合计 {sum(l['size'] for l in layers)/1048576:.1f}MB")

    log("下载并校验 base 层")
    cfg_blob = fetch_blob(man["config"]["digest"], man["config"]["size"])
    layer_files = [fetch_blob(l["digest"], l["size"]) for l in layers]

    log("确认 base 镜像的 Python 安装在 /usr/local")
    ok, found = check_base_layout(layer_files)
    if not ok:
        raise SystemExit(f"base 镜像布局不符合预期: {found}")

    cfg = json.loads(cfg_blob.read_bytes())
    base_diffs = cfg["rootfs"]["diff_ids"]
    if len(base_diffs) != len(layers):
        raise SystemExit("config 里 diff_ids 数量与层数不一致")

    pip_install(STAGE / SITE)

    log("复制后端代码与前端产物")
    copy_tree(ROOT / "backend", STAGE / "app" / "backend", EXCLUDE_DIRS, EXCLUDE_FILES)
    copy_tree(ROOT / "frontend" / "dist", STAGE / "app" / "frontend" / "dist", EXCLUDE_DIRS, set())
    (STAGE / "app" / "backend" / "uploads").mkdir(parents=True, exist_ok=True)

    layer_gz, diff_id = make_layer(STAGE)

    log("改写 image config")
    env = cfg["config"].get("Env", [])

    def setenv(k, v):
        env[:] = [e for e in env if not e.startswith(k + "=")]
        env.append(f"{k}={v}")

    setenv("PYTHONUNBUFFERED", "1")
    setenv("PYTHONDONTWRITEBYTECODE", "1")
    setenv("PIP_NO_INDEX", "1")
    setenv("TZ", "Asia/Shanghai")
    cfg["config"]["Env"] = env
    cfg["config"]["Cmd"] = [
        "/usr/local/bin/python3.10", "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", "18080",
        "--proxy-headers", "--forwarded-allow-ips", "*",
    ]
    cfg["config"]["Entrypoint"] = None
    cfg["config"]["WorkingDir"] = "/app/backend"
    cfg["config"]["ExposedPorts"] = {"18080/tcp": {}}
    cfg["rootfs"]["diff_ids"] = base_diffs + [f"sha256:{diff_id}"]
    cfg["history"].append({
        "created": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
        "created_by": "sswhl offline assembly: pip install --no-index + COPY backend/frontend/dist",
        "comment": "built without docker daemon",
    })
    cfg_bytes = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
    cfg_hex = hashlib.sha256(cfg_bytes).hexdigest()
    (BUILD / f"{cfg_hex}.json").write_bytes(cfg_bytes)
    log(f"  config id {cfg_hex[:19]}  diff_ids {len(cfg['rootfs']['diff_ids'])} 个")

    log("拼装 docker load 用 tar")
    names = []
    for i, lf in enumerate(layer_files):
        names.append(hashlib.sha256(lf.read_bytes()).hexdigest()[:16])
    names.append(hashlib.sha256(layer_gz.read_bytes()).hexdigest()[:16])
    all_files = layer_files + [layer_gz]

    manifest = [{
        "Config": f"{cfg_hex}.json",
        "RepoTags": IMG_TAGS,
        "Layers": [f"{n}/layer.tar" for n in names],
    }]
    repositories = {}
    for tag in IMG_TAGS:
        repo, ver = tag.rsplit(":", 1)
        repositories.setdefault(repo, {})[ver] = cfg_hex

    tmp = OUT.with_suffix(".tar.part")
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
                t.addfile(info, __import__("io").BytesIO(data))

        addfile("manifest.json", json.dumps(manifest, indent=2).encode())
        addfile("repositories", json.dumps(repositories, indent=2).encode())
        addfile(f"{cfg_hex}.json", cfg_bytes)
        for n, p in zip(names, all_files):
            addfile(f"{n}/layer.tar", path=p)
    if OUT.exists():
        OUT.unlink()
    tmp.rename(OUT)
    log(f"输出 {OUT} ({OUT.stat().st_size/1048576:.1f}MB)")

    log("自检:重新读取 tar,校验每层 sha256 与 diff_ids 是否一致")
    with tarfile.open(OUT) as t:
        m = json.loads(t.extractfile("manifest.json").read())
        cfg2 = json.loads(t.extractfile(m[0]["Config"]).read())
        diffs = cfg2["rootfs"]["diff_ids"]
        for i, ln in enumerate(m[0]["Layers"]):
            member = t.extractfile(ln)
            h = hashlib.sha256()
            with gzip.GzipFile(fileobj=member) as gz:
                for chunk in iter(lambda: gz.read(1024 * 1024), b""):
                    h.update(chunk)
            got = "sha256:" + h.hexdigest()
            flag = "OK" if got == diffs[i] else "MISMATCH"
            log(f"  layer{i} {flag}")
            if flag != "OK":
                raise SystemExit("层校验失败")
    log("完成。服务器上执行: sudo docker load -i sswhl-api-image.tar")


if __name__ == "__main__":
    main()
