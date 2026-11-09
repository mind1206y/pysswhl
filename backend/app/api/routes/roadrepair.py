"""路面修复管理(照旧 RoadRepairController 1:1 复刻)。

- 主列表:关键字(地址/原因/备注)+状态+单位+开挖日期范围,排序仅 total/id,默认倒序
- 新增:默认状态「新建」,同时插入第一条进度历史;编辑不改状态(照旧)
- 进度:单条更新 + 勾选批量更新,均写进度历史
- 价格管理:路面类型价格字典 CRUD;公路局只取专属价,其它单位含通用价(照旧)
- 附件:10MB 上限 + 脚本类扩展名黑名单(照旧 UploadGuard);下载走短令牌
- 导出:双 Sheet(维修记录 + 进度记录),筛选与列表一致

权限:
- roadrepair:view  模块入口 + 全部读写(旧系统仅菜单控制访问,无细分权限)
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import create_short_token, decode_short_token
from app.core.config import settings
from app.api.deps import require_permission
from app.db.session import get_db
from app.models.road_repair import (
    Qiangxiurenyuan,
    RoadPrice,
    RoadRepair,
    RoadRepairAttachment,
    RoadRepairProgress,
)
from app.models.user import User
from app.services.roadrepair_common import (
    COMPANIES,
    PROGRESS_COLORS,
    PROGRESS_OPTIONS,
    banzu_options,
    match_price,
    price_options,
    repair_query,
    sort_repair_query,
)
from app.services.roadrepair_excel import build_export, excel_disposition

router = APIRouter()

ATT_TOKEN_MINUTES = 30
MAX_ATT_SIZE = 10 * 1024 * 1024  # 照旧 10MB
BLOCKED_EXTS = {
    ".aspx", ".ascx", ".ashx", ".asmx", ".asax", ".config",
    ".asp", ".cer", ".asa", ".cdx",
    ".jsp", ".jspx", ".php", ".php3", ".php5",
    ".exe", ".dll", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".wsf", ".scr", ".msi",
    ".html", ".htm", ".xhtml", ".shtml", ".svg", ".js", ".swf",
}


# ==================== 入参模型 ====================
class RepairIn(BaseModel):
    id: Optional[int] = None
    address: Optional[str] = None
    dig_date: Optional[str] = None
    road_type: Optional[str] = None
    reason: Optional[str] = None
    remark: Optional[str] = None
    area: Optional[float] = None
    final_area: Optional[float] = None
    price: Optional[float] = None
    total: Optional[float] = None
    company: Optional[str] = None
    banzu: Optional[str] = None


class ProgressIn(BaseModel):
    progress: str


class BatchProgressIn(BaseModel):
    ids: List[int]
    progress: str


class PriceIn(BaseModel):
    id: Optional[int] = None
    company: Optional[str] = None
    road_type: str
    price: Optional[float] = None


# ==================== 工具 ====================
def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _get_or_404(db: Session, rid: int) -> RoadRepair:
    row = db.get(RoadRepair, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return row


def _attachment_path(att: RoadRepairAttachment) -> Path:
    raw = (att.file_path or "").replace("\\", "/")
    if raw.startswith("~/"):
        raw = raw[2:]
    raw = raw.lstrip("/")
    low = raw.lower()
    if low.startswith("uploads/"):
        raw = raw[len("uploads/"):]
    elif low.startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="附件路径不合法")
    return path


def _row_dict(db: Session, row: RoadRepair) -> dict:
    item = row.to_dict()
    item["attachment_count"] = (
        db.query(func.count(RoadRepairAttachment.id))
        .filter(RoadRepairAttachment.repair_id == row.id)
        .scalar()
    )
    return item


# ==================== 列表 / 字典 ====================
@router.get("")
def list_repairs(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    progress: str = "",
    company: str = "",
    start: str = "",
    end: str = "",
    sort: str = "id",
    order: str = "desc",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    q = sort_repair_query(repair_query(db, keyword, progress, company, start, end), sort, order)
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [_row_dict(db, r) for r in rows]}


@router.get("/dicts")
def get_dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    return {
        "companies": COMPANIES,
        "progress_options": PROGRESS_OPTIONS,
        "progress_colors": PROGRESS_COLORS,
        "banzu": banzu_options(db),
    }


# ==================== 价格管理 ====================
@router.get("/price-options")
def get_price_options(
    company: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    return price_options(db, company)


@router.get("/match-price")
def get_match_price(
    company: str = "",
    road_type: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    return {"price": match_price(db, company, road_type)}


@router.get("/prices")
def list_prices(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    company: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    q = db.query(RoadPrice)
    if company:
        q = q.filter((RoadPrice.company == company) | (RoadPrice.company.is_(None)))
    if keyword:
        q = q.filter(RoadPrice.road_type.contains(keyword))
    total = q.count()
    rows = (
        q.order_by(RoadPrice.road_type.asc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {"total": total, "items": [r.to_dict() for r in rows]}


@router.post("/prices")
def save_price(
    data: PriceIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    if not (data.road_type or "").strip():
        raise HTTPException(status_code=400, detail="请填写路面类型")
    company = (data.company or "").strip() or None
    if data.id and data.id > 0:
        row = db.get(RoadPrice, data.id)
        if row is None:
            raise HTTPException(status_code=404, detail="价格记录不存在")
        row.company = company
        row.road_type = data.road_type.strip()
        row.price = data.price
        row.operator_name = current.username
        row.operate_time = datetime.now()
    else:
        row = RoadPrice(
            company=company,
            road_type=data.road_type.strip(),
            price=data.price,
            operator_name=current.username,
            operate_time=datetime.now(),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "id": row.id}


@router.delete("/prices/{price_id}")
def delete_price(
    price_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    row = db.get(RoadPrice, price_id)
    if row is None:
        raise HTTPException(status_code=404, detail="价格记录不存在")
    db.delete(row)
    db.commit()
    return {"success": True}


# ==================== 导出 ====================
@router.get("/export")
def export_repairs(
    keyword: str = "",
    progress: str = "",
    company: str = "",
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    rows = repair_query(db, keyword, progress, company, start, end).order_by(
        RoadRepair.id.desc()
    ).all()
    items = [_row_dict(db, r) for r in rows]
    ids = [r.id for r in rows]
    progress_rows = []
    if ids:
        plist = (
            db.query(RoadRepairProgress)
            .filter(RoadRepairProgress.repair_id.in_(ids))
            .order_by(RoadRepairProgress.repair_id.asc(), RoadRepairProgress.progress_date.asc())
            .all()
        )
        progress_rows = [p.to_dict() for p in plist]
    buf = build_export(items, progress_rows)
    filename = f"道路维修记录_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


# ==================== 主表 CRUD ====================
@router.post("")
def create_repair(
    data: RepairIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    if not (data.address or "").strip():
        raise HTTPException(status_code=400, detail="请填写地址")
    now = datetime.now()
    row = RoadRepair(
        address=data.address.strip(),
        dig_date=_parse_date(data.dig_date),
        road_type=data.road_type,
        reason=data.reason,
        remark=data.remark,
        area=data.area,
        final_area=data.final_area,
        price=data.price,
        total=data.total,
        company=data.company,
        current_progress="新建",  # 照旧:未手动设置时给默认值
        operator_name=current.username,
        operate_time=now,
        banzu=data.banzu,
    )
    db.add(row)
    db.flush()
    db.add(
        RoadRepairProgress(
            repair_id=row.id,
            progress=row.current_progress,
            progress_date=now,
            operator_name=row.operator_name,
        )
    )
    db.commit()
    db.refresh(row)
    return {"success": True, "id": row.id}


@router.put("/{rid}")
def update_repair(
    rid: int,
    data: RepairIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    row = _get_or_404(db, rid)
    # 照旧 Update:只更新允许的字段,不改 current_progress(状态走进度接口)
    row.address = data.address.strip() if data.address else row.address
    row.dig_date = _parse_date(data.dig_date)
    row.road_type = data.road_type
    row.reason = data.reason
    row.remark = data.remark
    row.area = data.area
    row.final_area = data.final_area
    row.price = data.price
    row.total = data.total
    row.company = data.company
    row.operator_name = current.username
    row.operate_time = datetime.now()
    row.banzu = data.banzu
    db.commit()
    return {"success": True}


@router.delete("/{rid}")
def delete_repair(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    row = _get_or_404(db, rid)
    # 照旧:先删进度再删主表;附件记录与文件一并清理(旧代码遗留孤儿附件,这里顺手修正)
    for p in db.query(RoadRepairProgress).filter(RoadRepairProgress.repair_id == rid).all():
        db.delete(p)
    for att in db.query(RoadRepairAttachment).filter(RoadRepairAttachment.repair_id == rid).all():
        try:
            path = _attachment_path(att)
            if path.exists():
                path.unlink()
        except HTTPException:
            pass
        db.delete(att)
    db.delete(row)
    db.commit()
    return {"success": True}


@router.get("/{rid}")
def get_repair(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    return _get_or_404(db, rid).to_dict()


# ==================== 进度 ====================
@router.get("/{rid}/progress")
def list_progress(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    rows = (
        db.query(RoadRepairProgress)
        .filter(RoadRepairProgress.repair_id == rid)
        # id 兜底排序:同一秒内的两条历史也能稳定按新旧倒序(照旧按日期倒序)
        .order_by(
            RoadRepairProgress.progress_date.desc(), RoadRepairProgress.id.desc()
        )
        .all()
    )
    return [p.to_dict() for p in rows]


def _apply_progress(db: Session, row: RoadRepair, progress: str, now: datetime):
    row.current_progress = progress
    row.operate_time = now
    db.add(
        RoadRepairProgress(
            repair_id=row.id,
            progress=progress,
            progress_date=now,
            operator_name=row.operator_name,
        )
    )


@router.post("/{rid}/progress")
def update_progress(
    rid: int,
    data: ProgressIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    row = _get_or_404(db, rid)
    now = datetime.now()
    row.operator_name = current.username
    _apply_progress(db, row, data.progress, now)
    db.commit()
    return {"success": True}


@router.post("/progress-batch")
def batch_update_progress(
    data: BatchProgressIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="未选择数据")
    rows = db.query(RoadRepair).filter(RoadRepair.id.in_(data.ids)).all()
    now = datetime.now()
    for row in rows:
        row.operator_name = current.username
        _apply_progress(db, row, data.progress, now)
    db.commit()
    return {"success": True, "updated": len(rows)}


# ==================== 附件 ====================
@router.get("/{rid}/attachments")
def list_attachments(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    rows = (
        db.query(RoadRepairAttachment)
        .filter(RoadRepairAttachment.repair_id == rid)
        .order_by(RoadRepairAttachment.upload_time.desc())
        .all()
    )
    return [a.to_dict() for a in rows]


@router.post("/{rid}/attachments")
async def upload_attachment(
    rid: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    _get_or_404(db, rid)
    raw_name = Path(file.filename or "file").name
    ext = Path(raw_name).suffix.lower()
    if ext in BLOCKED_EXTS:
        raise HTTPException(
            status_code=400, detail=f"不允许上传 {ext} 类型的文件(可执行/脚本类)"
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="请选择文件")
    if len(content) > MAX_ATT_SIZE:
        raise HTTPException(status_code=400, detail="文件不能超过10MB")

    now = datetime.now()
    subdir = Path("roadrepair") / str(rid)
    target = Path(settings.UPLOAD_DIR) / subdir
    target.mkdir(parents=True, exist_ok=True)
    stored = f"{now.strftime('%Y%m%d%H%M%S')}_{Path(raw_name).stem}{ext}"
    (target / stored).write_bytes(content)

    att = RoadRepairAttachment(
        repair_id=rid,
        file_name=raw_name,
        file_path="/Upload/" + subdir.as_posix() + "/" + stored,
        file_size=len(content),
        upload_time=now,
        operator_name=current.username,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return {"success": True, "id": att.id}


@router.post("/attachments/{att_id}/token")
def attachment_token(
    att_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    att = db.get(RoadRepairAttachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    token = create_short_token(
        "roadrepair_attach", {"aid": att_id, "sub": str(current.id)}, minutes=ATT_TOKEN_MINUTES
    )
    return {
        "token": token,
        "url": f"/api/roadrepair/attachments/download?token={token}",
        "expires_minutes": ATT_TOKEN_MINUTES,
    }


@router.get("/attachments/download")
def attachment_download(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少下载令牌")
    try:
        payload = decode_short_token(token, "roadrepair_attach")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    att = db.get(RoadRepairAttachment, int(payload.get("aid", 0)))
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _attachment_path(att)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失(旧系统物理文件未迁移)")
    return FileResponse(path, filename=att.file_name or path.name)


@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("roadrepair:view")),
):
    att = db.get(RoadRepairAttachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    try:
        path = _attachment_path(att)
        if path.exists():
            path.unlink()
    except HTTPException:
        pass
    db.delete(att)
    db.commit()
    return {"success": True}
