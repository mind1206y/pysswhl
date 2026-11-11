"""测漏笔记(照旧系统 LeakController 复刻),挂 /api/leak。

功能:
- 列表:月份/队伍/维修日期/关键字筛选,分页
- 详情:记录 + 附件(图片/视频/文档),附件通过短令牌 URL 访问
- 新增/编辑/删除:仅记录人(或超管)可改删;新增/编辑可带附件
- 上传:本地存储,图片自动压缩,单文件 ≤ 200MB
- 导出:PDF(reportlab),含详情、公式、备注、相关影像

权限:
- leak:view  = 入口 + 查询/详情/附件查看/PDF
- leak:manage= 新增/编辑/删除/上传/清理孤儿文件
"""

import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlencode, urlparse

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import BASE_DIR, settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.leak import LeakFile, LeakRecord
from app.models.user import User
from app.services.leak_pdf import build_pdf, pdf_filename

router = APIRouter()

LEAK_SUBDIR = "Leak"
MAX_UPLOAD_SIZE = 200 * 1024 * 1024
FILE_TOKEN_MINUTES = 180

ALLOWED_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".mp4", ".mov", ".avi", ".wmv", ".flv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".txt", ".xml",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".wmv", ".flv"}

METHODS = {"coefficient", "bucket", "meter", "experience"}


def _file_type(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext == ".pdf":
        return "pdf"
    if ext in {".doc", ".docx"}:
        return "word"
    if ext in {".xls", ".xlsx"}:
        return "excel"
    return "other"


def _leak_root() -> Path:
    root = Path(settings.UPLOAD_DIR) / LEAK_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(url: str) -> Optional[Path]:
    """把旧/新两种文件地址归一成本地路径,并限制在上传根目录内。"""
    if not url:
        return None
    text = str(url).strip()
    if text.startswith("http://") or text.startswith("https://"):
        return None
    text = text.replace("\\", "/")
    for prefix in ("/Uploads/", "Uploads/", "/Upload/", "Upload/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.lstrip("/")
    if not text:
        return None
    root = Path(settings.UPLOAD_DIR).resolve()
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _leak_local_path(url: str) -> Optional[Path]:
    """仅允许访问/删除 Leak 子目录内的本地文件,避免跨模块误删。"""
    path = _local_path(url)
    if path is None:
        return None
    root = (Path(settings.UPLOAD_DIR) / LEAK_SUBDIR).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _is_remote(url: str) -> bool:
    return bool(url) and (url.startswith("http://") or url.startswith("https://"))


def _allowed_remote_hosts() -> set:
    hosts = {"172.16.80.115"}  # 旧系统 115 文件服务器
    for api in (settings.LEAK_REMOTE_UPLOAD_URL, settings.LEAK_REMOTE_DELETE_URL):
        try:
            host = urlparse(api or "").hostname
            if host:
                hosts.add(host)
        except ValueError:
            pass
    return hosts


def _is_allowed_remote(url: str) -> bool:
    """仅允许访问 115 或 .env 配置的远程文件服务器,避免代理接口被当作 SSRF。"""
    if not _is_remote(url):
        return False
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    return bool(host) and host in _allowed_remote_hosts()


def _delete_remote_file(url: str) -> None:
    """调用 115 Delete.ashx 删除远程文件;失败静默(照旧系统)。"""
    if not _is_allowed_remote(url):
        return
    api = (settings.LEAK_REMOTE_DELETE_URL or "").strip()
    if not api:
        return
    try:
        req = urllib.request.Request(
            f"{api}?{urlencode({'fileUrl': url})}",
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception:
        pass


def _delete_file(url: str) -> None:
    if _is_remote(url):
        _delete_remote_file(url)
        return
    path = _leak_local_path(url)
    if path is not None and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _read_file_bytes(url: str) -> Optional[bytes]:
    path = _leak_local_path(url)
    if path is not None and path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            return None
    if _is_allowed_remote(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read()
        except Exception:
            return None
    return None


def _find_ffmpeg() -> Optional[str]:
    candidates = [
        (settings.LEAK_FFMPEG_PATH or "").strip(),
        shutil.which("ffmpeg") or "",
        str(BASE_DIR.parent.parent / "sswhl" / "sswhl" / "Tools" / "ffmpeg" / "ffmpeg.exe"),
        str(BASE_DIR.parent.parent / "sswhl" / ".worktrees" / "dispatch" / "sswhl"
            / "Tools" / "ffmpeg" / "ffmpeg.exe"),
    ]
    for item in candidates:
        if item and Path(item).is_file():
            return item
    return None


def _maybe_compress_video(content: bytes, ext: str):
    """照旧系统用 ffmpeg 转 H.264(解决 H.265 浏览器不兼容),ffmpeg 缺失时原样返回。"""
    if ext not in VIDEO_EXTS:
        return content, ext
    exe = _find_ffmpeg()
    if not exe:
        return content, ext
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / f"input{ext}"
            target = Path(temp_dir) / "output.mp4"
            source.write_bytes(content)
            subprocess.run(
                [exe, "-i", str(source), "-vcodec", "libx264", "-crf", "28",
                 "-preset", "faster", "-y", str(target)],
                capture_output=True, timeout=300, check=False,
            )
            if target.is_file() and target.stat().st_size > 0:
                return target.read_bytes(), ".mp4"
    except Exception:
        pass
    return content, ext


def _remote_upload(content: bytes, filename: str) -> Optional[str]:
    """上传到 115 upload.ashx,成功返回远程 URL,不可达/失败返回 None。"""
    api = (settings.LEAK_REMOTE_UPLOAD_URL or "").strip()
    if not api:
        return None
    boundary = f"----Leak{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    safe_name = str(filename or "file").replace('"', "_")
    head = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + content + tail
    req = urllib.request.Request(
        api, data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.LEAK_REMOTE_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        url = (payload or {}).get("url")
        return url if _is_allowed_remote(url) else None
    except Exception:
        return None


def _maybe_compress_image(content: bytes, ext: str) -> bytes:
    if ext not in IMAGE_EXTS or ext == ".gif":
        return content
    try:
        with Image.open(io.BytesIO(content)) as im:
            im.load()
            if max(im.size) > 1920:
                im.thumbnail((1920, 1920), Image.LANCZOS)
            out = io.BytesIO()
            if ext in {".jpg", ".jpeg"}:
                im.convert("RGB").save(out, format="JPEG", quality=70, optimize=True)
            elif ext == ".png":
                im.save(out, format="PNG", optimize=True)
            elif ext == ".bmp":
                im.save(out, format="BMP")
            else:
                return content
            compressed = out.getvalue()
            return compressed if len(compressed) < len(content) else content
    except Exception:
        return content


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"日期格式不正确:{value}")


def _parse_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round2(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def _record_or_404(db: Session, leak_id: int) -> LeakRecord:
    record = db.get(LeakRecord, leak_id)
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


def _ensure_owner(record: LeakRecord, user: User) -> None:
    if not user.is_superuser and record.creator != user.username:
        raise HTTPException(status_code=403, detail="无权修改他人创建的记录")


def _file_infos(raw: str) -> List[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="附件信息格式不正确")
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="附件信息格式不正确")
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("Url") or "").strip()
        if not url:
            continue
        if url.startswith("http://") or url.startswith("https://"):
            if not _is_allowed_remote(url):
                raise HTTPException(status_code=400, detail="附件地址不合法")
        else:
            if _leak_local_path(url) is None:
                raise HTTPException(status_code=400, detail="附件地址不合法")
        name = str(item.get("fileName") or item.get("FileName") or Path(url).name)
        thumb = str(item.get("ThumbUrl") or item.get("thumbUrl") or "").strip()
        result.append({"url": url, "name": name, "thumb": thumb})
    return result


def _add_files(db: Session, leak_id: int, infos: List[dict]) -> None:
    now = datetime.now()
    for info in infos:
        url = info["url"]
        db.add(LeakFile(
            leak_id=leak_id,
            file_url=url,
            file_name=info["name"],
            thumb_url=info["thumb"],
            file_type=_file_type(Path(url).suffix),
            create_time=now,
        ))


def _remove_files(db: Session, files: List[LeakFile]) -> None:
    for item in files:
        _delete_file(item.file_url)
        if item.thumb_url and item.thumb_url != item.file_url:
            _delete_file(item.thumb_url)
        db.delete(item)


def _file_urls(file: LeakFile, user: User) -> dict:
    token = create_short_token(
        "leak_file", {"fid": file.id, "sub": str(user.id)}, minutes=FILE_TOKEN_MINUTES,
    )
    base = f"/api/leak/files/{file.id}?token={token}"
    return {
        "Id": file.id,
        "FileName": file.file_name or "附件",
        "FileType": file.file_type or "other",
        "FileUrl": base,
        "ThumbUrl": f"{base}&thumb=1" if file.thumb_url else base,
    }


class LeakIn:
    """新增/编辑表单(字段名沿用旧系统 PascalCase)。"""

    def __init__(
        self,
        Title: str = Form(...),
        Location: str = Form(""),
        DetectUser: str = Form(""),
        DetectCom: str = Form(""),
        PaichaType: str = Form("普查"),
        DetectTime: str = Form(""),
        QuantifyTime: str = Form(""),
        LeakMethod: str = Form("coefficient"),
        Pressure: Optional[float] = Form(None),
        Area: Optional[float] = Form(None),
        FlowRate: Optional[float] = Form(None),
        AreaExpression: str = Form(""),
        Remark: str = Form(""),
        Time1: Optional[float] = Form(None),
        Time2: Optional[float] = Form(None),
        Time3: Optional[float] = Form(None),
        AvgTime: Optional[float] = Form(None),
        BucketLiters: Optional[float] = Form(None),
        MeterTime: Optional[float] = Form(None),
        MeterVolume: Optional[float] = Form(None),
        ExperienceDesc: str = Form(""),
        ExperienceFlow: Optional[float] = Form(None),
        FlowMeta: str = Form(""),
        FileInfos: str = Form(""),
        DeletedFileIds: str = Form(""),
    ):
        self.title = (Title or "").strip()
        self.location = (Location or "").strip()
        self.detect_user = (DetectUser or "").strip()
        self.detect_com = (DetectCom or "").strip()
        self.paicha_type = (PaichaType or "").strip()
        self.detect_time = _parse_dt(DetectTime)
        self.quantify_time = (QuantifyTime or "").strip()
        self.leak_method = (LeakMethod or "").strip()
        self.pressure = _parse_float(Pressure)
        self.area = _parse_float(Area)
        self.flow_rate = _round2(_parse_float(FlowRate))
        self.area_expression = (AreaExpression or "").strip()
        self.remark = (Remark or "").strip()
        self.time1 = _parse_float(Time1)
        self.time2 = _parse_float(Time2)
        self.time3 = _parse_float(Time3)
        self.avg_time = _round2(_parse_float(AvgTime))
        self.bucket_liters = _parse_float(BucketLiters)
        self.meter_time = _parse_float(MeterTime)
        self.meter_volume = _parse_float(MeterVolume)
        self.experience_desc = (ExperienceDesc or "").strip()
        self.experience_flow = _round2(_parse_float(ExperienceFlow))
        self.flow_meta = (FlowMeta or "").strip()
        self.file_infos = _file_infos(FileInfos)
        self.deleted_file_ids = [
            int(x) for x in (DeletedFileIds or "").replace("，", ",").split(",") if x.strip().isdigit()
        ]

    def validate(self) -> None:
        if not self.title:
            raise HTTPException(status_code=400, detail="请填写标题")
        if not self.location:
            raise HTTPException(status_code=400, detail="请填写地点")
        if not self.detect_user:
            raise HTTPException(status_code=400, detail="请填写测漏人")
        if self.detect_time is None:
            raise HTTPException(status_code=400, detail="请选择维修日期")
        if self.leak_method not in METHODS:
            raise HTTPException(status_code=400, detail="计量方法不正确")
        if self.leak_method == "coefficient" and (self.area or 0) <= 0:
            raise HTTPException(status_code=400, detail="系数法请填写面积")
        if self.leak_method == "bucket":
            if min(self.time1 or 0, self.time2 or 0, self.time3 or 0, self.bucket_liters or 0) <= 0:
                raise HTTPException(status_code=400, detail="桶量法请完整填写三个时间和定量桶升数")
        if self.leak_method == "meter" and min(self.meter_time or 0, self.meter_volume or 0) <= 0:
            raise HTTPException(status_code=400, detail="水表读数法请填写计读时间和计读流量")
        if self.leak_method == "experience" and (self.flow_rate or 0) <= 0:
            raise HTTPException(status_code=400, detail="经验对比法请填写估量漏量")

    def apply(self, record: LeakRecord) -> None:
        record.title = self.title
        record.location = self.location
        record.detect_user = self.detect_user
        record.detect_com = self.detect_com
        record.paicha_type = self.paicha_type
        record.detect_time = self.detect_time
        record.quantify_time = self.quantify_time
        record.leak_method = self.leak_method
        record.pressure = self.pressure
        record.area = self.area
        record.flow_rate = self.flow_rate
        record.area_expression = self.area_expression
        record.remark = self.remark
        record.time1 = self.time1 if self.leak_method == "bucket" else None
        record.time2 = self.time2 if self.leak_method == "bucket" else None
        record.time3 = self.time3 if self.leak_method == "bucket" else None
        record.avg_time = self.avg_time if self.leak_method == "bucket" else None
        record.bucket_liters = self.bucket_liters if self.leak_method == "bucket" else None
        record.meter_time = self.meter_time if self.leak_method == "meter" else None
        record.meter_volume = self.meter_volume if self.leak_method == "meter" else None
        record.experience_desc = self.experience_desc if self.leak_method == "experience" else ""
        record.experience_flow = self.experience_flow if self.leak_method == "experience" else None
        record.flow_meta = self.flow_meta


# ==================== 字典 ====================
@router.get("/months")
def leak_months(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("leak:view")),
):
    values = (
        db.query(LeakRecord.detect_time)
        .filter(LeakRecord.detect_time.isnot(None))
        .all()
    )
    months = sorted({v[0].strftime("%Y-%m") for v in values if v[0]}, reverse=True)
    return [{"value": "all", "text": "全部月份"}] + [{"value": m, "text": m} for m in months]


@router.get("/detect-coms")
def leak_detect_coms(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("leak:view")),
):
    names = (
        db.query(LeakRecord.detect_com)
        .filter(LeakRecord.detect_com.isnot(None), LeakRecord.detect_com != "")
        .distinct()
        .order_by(LeakRecord.detect_com)
        .all()
    )
    return [{"value": "all", "text": "全部队伍"}] + [
        {"value": n[0], "text": n[0]} for n in names
    ]


@router.get("/form-coms")
def leak_form_coms(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("leak:manage")),
):
    names = (
        db.query(LeakRecord.detect_com)
        .filter(
            LeakRecord.detect_com.isnot(None),
            LeakRecord.detect_com != "",
            LeakRecord.creator == user.username,
        )
        .distinct()
        .order_by(LeakRecord.detect_com)
        .all()
    )
    return [n[0] for n in names]


# ==================== 列表 ====================
@router.get("")
def list_leak(
    page: int = Query(1, ge=1),
    rows: int = Query(30, ge=1, le=500),
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    detectCom: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("leak:view")),
):
    query = db.query(LeakRecord)
    month_filtered = False

    if month and month not in ("all", ""):
        try:
            year, mon = [int(x) for x in month.split("-")]
            month_start = datetime(year, mon, 1)
            month_end = (month_start.replace(day=1) + timedelta(days=32)).replace(day=1)
            query = query.filter(
                LeakRecord.detect_time.isnot(None),
                LeakRecord.detect_time >= month_start,
                LeakRecord.detect_time < month_end,
            )
            month_filtered = True
        except (ValueError, TypeError):
            pass

    if not month_filtered:
        start = _parse_dt(startDate)
        end = _parse_dt(endDate)
        if start:
            end_exclusive = (end + timedelta(days=1)) if end else (start + timedelta(days=1))
            query = query.filter(
                LeakRecord.detect_time.isnot(None),
                LeakRecord.detect_time >= start,
                LeakRecord.detect_time < end_exclusive,
            )
        elif end:
            query = query.filter(
                LeakRecord.detect_time.isnot(None),
                LeakRecord.detect_time < end + timedelta(days=1),
            )

    if detectCom and detectCom != "all":
        query = query.filter(LeakRecord.detect_com == detectCom)

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(
            LeakRecord.title.like(like),
            LeakRecord.location.like(like),
            LeakRecord.paicha_type.like(like),
            LeakRecord.remark.like(like),
            LeakRecord.creator.like(like),
            LeakRecord.area_expression.like(like),
        ))

    total = query.count()
    data = (
        query.order_by(LeakRecord.detect_time.desc(), LeakRecord.id.desc())
        .offset((page - 1) * rows)
        .limit(rows)
        .all()
    )
    return {"total": total, "rows": [r.to_dict() for r in data]}


# ==================== 上传 / 清理 ====================
@router.post("/upload")
async def upload_leak_file(
    file: UploadFile = File(...),
    storage: str = Form("local"),
    _user: User = Depends(require_permission("leak:manage")),
):
    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="没有文件")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 200MB")
    if not content:
        raise HTTPException(status_code=400, detail="没有文件")

    content = _maybe_compress_image(content, ext)
    content, stored_ext = _maybe_compress_video(content, ext)
    file_type = _file_type(stored_ext)

    # 照旧系统:远程 115 失败自动降级本地存储
    if (storage or "").strip().lower() == "remote":
        remote_url = _remote_upload(content, file.filename)
        if remote_url:
            return {
                "url": remote_url,
                "fileName": file.filename,
                "fileType": file_type,
                "thumbUrl": "",
                "fallback": False,
                "warning": "",
            }

    target = _leak_root() / datetime.now().strftime("%Y%m")
    target.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{stored_ext}"
    (target / stored).write_bytes(content)
    rel = f"{LEAK_SUBDIR}/{target.name}/{stored}"
    fallback = (storage or "").strip().lower() == "remote"
    return {
        "url": rel,
        "fileName": file.filename,
        "fileType": file_type,
        "thumbUrl": "",
        "fallback": fallback,
        "warning": "115服务器不可用，已自动切换为本地存储" if fallback else "",
    }


class CleanupIn(BaseModel):
    urls: List[str] = []


@router.post("/cleanup")
def cleanup_uploaded(
    data: CleanupIn,
    _user: User = Depends(require_permission("leak:manage")),
):
    for url in data.urls:
        _delete_file(url)
    return {"success": True}


# ==================== 新增 / 编辑 / 删除 ====================
@router.post("")
def create_leak(
    data: LeakIn = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("leak:manage")),
):
    data.validate()
    record = LeakRecord(creator=user.username, create_time=datetime.now())
    data.apply(record)
    db.add(record)
    db.flush()
    _add_files(db, record.id, data.file_infos)
    db.commit()
    return {"success": True, "id": record.id}


@router.put("/{leak_id}")
def update_leak(
    leak_id: int,
    data: LeakIn = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("leak:manage")),
):
    record = _record_or_404(db, leak_id)
    _ensure_owner(record, user)
    data.validate()
    data.apply(record)

    if data.deleted_file_ids:
        files = (
            db.query(LeakFile)
            .filter(LeakFile.leak_id == leak_id, LeakFile.id.in_(data.deleted_file_ids))
            .all()
        )
        _remove_files(db, files)

    _add_files(db, leak_id, data.file_infos)
    db.commit()
    return {"success": True}


@router.delete("/{leak_id}")
def delete_leak(
    leak_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("leak:manage")),
):
    record = _record_or_404(db, leak_id)
    _ensure_owner(record, user)
    files = db.query(LeakFile).filter(LeakFile.leak_id == leak_id).all()
    _remove_files(db, files)
    db.delete(record)
    db.commit()
    return {"success": True}


# ==================== 详情 ====================
@router.get("/{leak_id}")
def get_leak(
    leak_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("leak:view")),
):
    record = _record_or_404(db, leak_id)
    files = (
        db.query(LeakFile)
        .filter(LeakFile.leak_id == leak_id)
        .order_by(LeakFile.id.asc())
        .all()
    )
    return {
        "success": True,
        "data": record.to_dict(),
        "files": [_file_urls(f, user) for f in files],
    }


# ==================== 附件访问(短令牌,<img>/<video> 可直接用) ====================
@router.get("/files/{file_id}")
def get_leak_file(
    file_id: int,
    request: Request,
    token: str = Query(""),
    thumb: int = Query(0),
    db: Session = Depends(get_db),
):
    if not token:
        raise HTTPException(status_code=401, detail="缺少文件访问令牌")
    try:
        payload = decode_short_token(token, "leak_file")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="文件访问令牌无效或已过期")
    if int(payload.get("fid", -1)) != file_id:
        raise HTTPException(status_code=403, detail="令牌与文件不匹配")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="签发账号不存在或已停用")

    item = db.get(LeakFile, file_id)
    if item is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    url = item.thumb_url if (thumb and item.thumb_url) else item.file_url
    if not url:
        raise HTTPException(status_code=404, detail="附件地址为空")

    if _is_remote(url):
        if not _is_allowed_remote(url):
            raise HTTPException(status_code=403, detail="远程附件地址不在允许范围")
        headers = {"User-Agent": "Mozilla/5.0"}
        range_header = request.headers.get("range")
        if range_header:
            headers["Range"] = range_header
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
                media_type = resp.headers.get_content_type()
                status_code = resp.status
                resp_headers = {
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "private, max-age=300",
                }
                content_range = resp.headers.get("Content-Range")
                if content_range:
                    resp_headers["Content-Range"] = content_range
        except urllib.error.HTTPError as exc:
            if exc.code == 416:
                return Response(
                    status_code=416,
                    headers={"Content-Range": exc.headers.get("Content-Range", "")},
                )
            raise HTTPException(status_code=502, detail="远程附件读取失败")
        except Exception:
            raise HTTPException(status_code=502, detail="远程附件读取失败")
        return Response(content=content, media_type=media_type,
                        status_code=status_code, headers=resp_headers)

    path = _leak_local_path(url)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


# ==================== PDF 导出 ====================
@router.get("/{leak_id}/pdf")
def export_leak_pdf(
    leak_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("leak:view")),
):
    record = _record_or_404(db, leak_id)
    files = db.query(LeakFile).filter(
        LeakFile.leak_id == leak_id, LeakFile.file_type == "image",
    ).order_by(LeakFile.id.asc()).all()
    images = []
    for item in files:
        content = _read_file_bytes(item.file_url)
        if content:
            images.append((item.file_name or "附件", content))
    try:
        payload = build_pdf(record, images)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF生成失败:{exc}")
    filename = pdf_filename(record)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )
