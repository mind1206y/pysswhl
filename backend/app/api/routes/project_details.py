"""工程管理子资源:进度记录 / 问题监管 / 附件,照旧系统 GongchengguanliController 逻辑复刻。

- 进度:添加时联动主表状态;删除仅创建者,删后用剩余最新一条回滚主表状态
- 问题:增删改 + 标记解决;删除仅创建者
- 附件:上传(黑名单+50MB 限制)/下载/删除;删除仅上传者,先删物理文件再删记录
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.project import STATUS_MAP, Gongchenggl, GongchengglFujian, GongchengglJianguan, GongchengglJindu
from app.models.user import User

router = APIRouter()

# 单文件大小限制 50MB
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
FUJIAN_SUBDIR = "GongChengGuanliFujian"
# 下载令牌有效期(分钟):短时效,避免长期登录令牌出现在 URL/访问日志里
DOWNLOAD_TOKEN_MINUTES = 10

# 允许上传的类型白名单(白名单比黑名单稳:新出现的危险扩展名默认拒绝)
ALLOWED_EXTS = {
    # 图片
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    # 文档
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".md",
    # 压缩包
    ".zip", ".rar", ".7z",
    # 工程图纸
    ".dwg", ".dxf",
}


def _get_project_or_404(gcglid: int, db: Session) -> Gongchenggl:
    p = db.get(Gongchenggl, gcglid)
    if p is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    return p


# ==================== 进度 gongchenggl_jindu ====================

class JinduIn(BaseModel):
    jindu: str
    jinduzhuangtai: int = 0


class JinduUpdateIn(BaseModel):
    jindu: str


@router.get("/{gcglid}/jindu")
def list_jindu(
    gcglid: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_project_or_404(gcglid, db)
    rows = (
        db.query(GongchengglJindu)
        .filter(GongchengglJindu.gcglid == gcglid)
        .order_by(GongchengglJindu.riqi.desc(), GongchengglJindu.id.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


@router.post("/{gcglid}/jindu")
def add_jindu(
    gcglid: int,
    data: JinduIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    """添加进度并联动主表状态(修复旧系统 jinduzhuangtai 硬编码 0 的隐患:直接以所选状态入库)。"""
    p = _get_project_or_404(gcglid, db)
    text = data.jindu.strip()
    if not text:
        raise HTTPException(status_code=400, detail="进度描述不能为空")
    if data.jinduzhuangtai not in STATUS_MAP:
        raise HTTPException(status_code=400, detail="状态值不合法")
    now = datetime.now()
    row = GongchengglJindu(
        gcglid=gcglid,
        jindu=text,
        riqi=now,
        jinduzhuangtai=data.jinduzhuangtai,
        CreateUser=current.username,
        UpdateUser=current.username,
        UpdateTime=now,
    )
    db.add(row)
    # 联动主表:状态 + 状态备注;移交/归档置位并补日期(旧系统不回滚这些标志)
    p.Status = data.jinduzhuangtai
    p.StatusRemark = text
    if data.jinduzhuangtai == 6:
        if p.yijiaoriqi is None:
            p.yijiaoriqi = now
        p.isyijiao = True
    elif data.jinduzhuangtai == 7:
        if p.guidangriqi is None:
            p.guidangriqi = now
        p.isguidang = True
    p.LastUpdateTime = now
    p.updateUser = current.username
    db.commit()
    return row.to_dict()


@router.put("/{gcglid}/jindu/{row_id}")
def update_jindu(
    gcglid: int,
    row_id: int,
    data: JinduUpdateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    """编辑进度只改文本,不改状态(照旧系统 UpdateJD)。"""
    row = db.get(GongchengglJindu, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="进度记录不存在")
    text = data.jindu.strip()
    if not text:
        raise HTTPException(status_code=400, detail="进度描述不能为空")
    row.jindu = text
    row.UpdateUser = current.username
    row.UpdateTime = datetime.now()
    db.commit()
    return row.to_dict()


@router.delete("/{gcglid}/jindu/{row_id}")
def delete_jindu(
    gcglid: int,
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    """删除进度(仅创建者),删后用剩余最新一条回滚主表状态;移交/归档标志不回滚。"""
    row = db.get(GongchengglJindu, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="进度记录不存在")
    if row.CreateUser != current.username:
        raise HTTPException(status_code=403, detail="只有创建人可以删除该进度")
    p = _get_project_or_404(gcglid, db)
    db.delete(row)
    db.flush()
    latest = (
        db.query(GongchengglJindu)
        .filter(GongchengglJindu.gcglid == gcglid)
        .order_by(GongchengglJindu.id.desc())
        .first()
    )
    if latest:
        p.Status = latest.jinduzhuangtai or 0
        p.StatusRemark = latest.jindu or ""
    else:
        p.Status = None
        p.StatusRemark = ""
    p.LastUpdateTime = datetime.now()
    p.updateUser = current.username
    db.commit()
    return {"message": "已删除"}


# ==================== 问题监管 gongchenggl_jianguan ====================

class JianguanIn(BaseModel):
    qingkuangshuoming: str


class ResolveIn(BaseModel):
    isjiejue: bool


@router.get("/{gcglid}/jianguan")
def list_jianguan(
    gcglid: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_project_or_404(gcglid, db)
    rows = (
        db.query(GongchengglJianguan)
        .filter(GongchengglJianguan.gcglid == gcglid)
        .order_by(GongchengglJianguan.riqi.desc(), GongchengglJianguan.id.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


@router.post("/{gcglid}/jianguan")
def add_jianguan(
    gcglid: int,
    data: JianguanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    text = data.qingkuangshuoming.strip()
    if not text:
        raise HTTPException(status_code=400, detail="情况说明不能为空")
    now = datetime.now()
    row = GongchengglJianguan(
        gcglid=gcglid,
        qingkuangshuoming=text,
        riqi=now,
        isjiejue=False,
        CreateUser=current.username,
        UpdateUser=current.username,
        UpdateTime=now,
    )
    db.add(row)
    db.commit()
    return row.to_dict()


@router.put("/{gcglid}/jianguan/{row_id}")
def update_jianguan(
    gcglid: int,
    row_id: int,
    data: JianguanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    row = db.get(GongchengglJianguan, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    text = data.qingkuangshuoming.strip()
    if not text:
        raise HTTPException(status_code=400, detail="情况说明不能为空")
    row.qingkuangshuoming = text
    row.UpdateUser = current.username
    row.UpdateTime = datetime.now()
    db.commit()
    return row.to_dict()


@router.put("/{gcglid}/jianguan/{row_id}/resolve")
def resolve_jianguan(
    gcglid: int,
    row_id: int,
    data: ResolveIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    row = db.get(GongchengglJianguan, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    row.isjiejue = data.isjiejue
    row.UpdateUser = current.username
    row.UpdateTime = datetime.now()
    db.commit()
    return row.to_dict()


@router.delete("/{gcglid}/jianguan/{row_id}")
def delete_jianguan(
    gcglid: int,
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    row = db.get(GongchengglJianguan, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    if row.CreateUser != current.username:
        raise HTTPException(status_code=403, detail="只有创建人可以删除该问题")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


# ==================== 附件 gongchenggl_fujian ====================

def fujian_dir() -> Path:
    d = Path(settings.UPLOAD_DIR) / FUJIAN_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/{gcglid}/fujian")
def list_fujian(
    gcglid: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    _get_project_or_404(gcglid, db)
    rows = (
        db.query(GongchengglFujian)
        .filter(GongchengglFujian.gcglid == gcglid)
        .order_by(GongchengglFujian.CreateTime.asc(), GongchengglFujian.id.asc())
        .all()
    )
    return [r.to_dict() for r in rows]


@router.post("/{gcglid}/fujian")
def upload_fujian(
    gcglid: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    _get_project_or_404(gcglid, db)
    target = fujian_dir()
    saved = []
    now = datetime.now()
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail=f"不允许上传 {ext or '无扩展名'} 类型文件:{f.filename}")
        content = f.file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件超过 50MB 限制:{f.filename}")
        stored = f"{uuid.uuid4().hex}{ext}"
        (target / stored).write_bytes(content)
        row = GongchengglFujian(
            gcglid=gcglid,
            url=stored,
            wjname=f.filename or stored,
            size=len(content),
            CreateTime=now,
            CreateUser=current.username,
        )
        db.add(row)
        saved.append(row)
    db.commit()
    return [r.to_dict() for r in saved]


@router.post("/{gcglid}/fujian/{row_id}/download-token")
def create_download_token(
    gcglid: int,
    row_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """签发短时效下载令牌:前端先拿令牌,再拼直链下载,长期登录令牌不出现在 URL/日志里。"""
    row = db.get(GongchengglFujian, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="附件不存在")
    token = create_short_token(
        "fujian_download", {"fid": row_id, "sub": str(_user.id)}, minutes=DOWNLOAD_TOKEN_MINUTES
    )
    return {
        "token": token,
        "url": f"/api/projects/attachments/{row_id}/download?token={token}",
        "expires_minutes": DOWNLOAD_TOKEN_MINUTES,
    }


@router.get("/attachments/{row_id}/download")
def download_fujian(
    row_id: int,
    token: str = "",
    db: Session = Depends(get_db),
):
    """浏览器直链下载(无 Authorization 头):只认短时效下载令牌,不认登录令牌。

    令牌本身即授权:作用域限 fujian_download、绑定附件 id、10 分钟过期;
    另核对签发账号仍存在且启用,停用账号的已签发令牌一并失效。
    """
    if not token:
        raise HTTPException(status_code=401, detail="缺少下载令牌,请先获取下载链接")
    try:
        payload = decode_short_token(token, "fujian_download")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期,请刷新后重新下载")
    if int(payload.get("fid", -1)) != row_id:
        raise HTTPException(status_code=403, detail="下载令牌与附件不匹配")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="签发账号不可用")
    row = db.get(GongchengglFujian, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = Path(settings.UPLOAD_DIR) / FUJIAN_SUBDIR / Path(row.url).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(path, filename=row.wjname)


@router.delete("/{gcglid}/fujian/{row_id}")
def delete_fujian(
    gcglid: int,
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:manage")),
):
    row = db.get(GongchengglFujian, row_id)
    if row is None or row.gcglid != gcglid:
        raise HTTPException(status_code=404, detail="附件不存在")
    if row.CreateUser != current.username:
        raise HTTPException(status_code=403, detail="只有上传人可以删除该附件")
    path = Path(settings.UPLOAD_DIR) / FUJIAN_SUBDIR / Path(row.url).name
    if path.exists():
        os.remove(path)
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
