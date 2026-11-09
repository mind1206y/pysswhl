"""领料申请(照旧 LingLiaoController + Views/LingLiao/Index.cshtml/Edit.cshtml 1:1 复刻)。

路由挂 /api/lingliao。权限:
- lingliao:view   模块入口 + 查询/新增/编辑本人草稿/提交/作废/删除本人作废单/明细/导出/附件
- lingliao:audit  审核/反审核/驳回(旧系统 pdqx「领料单审核」),超管自动拥有

与旧系统的差异(按新系统统一约定):
- 部门可见范围用 dept_scope_ids 子树(旧系统 cj 前缀语义)
- 新增/修改 bmid 取登录人部门子树内可选,越界兜底
- 附件下载走短令牌 URL,不把登录令牌放到 window.open 的 URL 里
- 新增附件先传临时目录,保存时转存 ~/uploads/LingLiao;列表页也支持直接上传
- 审核/反审核/驳回/作废等后端独立校验,不依赖前端按钮显隐
"""

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.lingliao import LingLiao, LingLiaoDetail, LingLiaoFile
from app.models.material import InStockRecord, MaterialLibrary
from app.models.user import Department, User
from app.services.lingliao_common import (
    CANCELLABLE_STATUS, EDITABLE_STATUS, STATUS_LABELS, SUBMITTABLE_STATUS,
    build_form_excel, detail_rows, excel_disposition, generate_danno, list_query,
    material_options, parse_date, r1, r2, supplier_options,
)

router = APIRouter()

TEMP_SUBDIR = "LingLiaoTemp"
FINAL_SUBDIR = "LingLiao"
FILE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".zip", ".rar", ".7z",
}
FILE_MAX_SIZE = 30 * 1024 * 1024
FILE_TOKEN_MINUTES = 180


# ==================== 请求体 ====================
class DetailIn(BaseModel):
    id: int = 0
    MaterialId: Optional[int] = None
    materialname: str = ""
    model: str = ""
    spec: str = ""
    unit: str = ""
    num: Optional[float] = None
    beizhu: str = ""
    shuoming: str = ""


class FileIn(BaseModel):
    Id: int = 0
    filename: str = ""
    filepath: str = ""
    filesize: int = 0


class SaveIn(BaseModel):
    id: int = 0
    sqriqi: str = ""
    gongyingshang: str = ""
    shuoming: str = ""
    bmid: Optional[int] = None
    Details: List[DetailIn] = Field(default_factory=list)
    files: List[FileIn] = Field(default_factory=list)


class RenumIn(BaseModel):
    renum: float


# ==================== 公共辅助 ====================
def _has_audit(current: User) -> bool:
    if current.is_superuser:
        return True
    owned = {p.code for role in current.roles for p in role.permissions}
    return "lingliao:audit" in owned


def _is_owner(order: LingLiao, current: User) -> bool:
    return bool(order.sqren) and order.sqren == current.username


def _default_bmid(db: Session, current: User, requested: Optional[int]) -> Optional[int]:
    """新增/修改归属部门:多部门用户可在本人部门子树内自选,越界/未选兜底第一个。"""
    scope = dept_scope_ids(db, current)
    if scope is None:
        if requested:
            return requested
        return current.departments[0].id if current.departments else None
    if requested and requested in scope:
        return requested
    return min(scope)


def _att_path(rel: str) -> Path:
    raw = (rel or "").replace("\\", "/").lstrip("/")
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="附件路径不合法")
    return path


def _temp_path(rel: str) -> Path:
    raw = (rel or "").replace("\\", "/").lstrip("/")
    if not raw.startswith(TEMP_SUBDIR + "/") or ".." in raw:
        raise HTTPException(status_code=400, detail="非法临时文件路径")
    return _att_path(raw)


def _file_url(file_id: int, current: User) -> str:
    token = create_short_token(
        "lingliao_file", {"fid": file_id, "sub": str(current.id)},
        minutes=FILE_TOKEN_MINUTES,
    )
    return f"/api/lingliao/files/download?token={token}"


def _can_delete_file(row: LingLiaoFile, current: User) -> bool:
    return row.operator_name == current.username or _has_audit(current)


def _file_dict(row: LingLiaoFile, current: User) -> dict:
    return row.to_dict(
        can_delete=_can_delete_file(row, current),
        download_url=_file_url(row.id, current),
    )


def _save_file(content: bytes, filename: str, subdir: str = FINAL_SUBDIR) -> tuple:
    ext = Path(filename or "").suffix.lower()
    if ext not in FILE_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型:{ext or '无扩展名'}")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > FILE_MAX_SIZE:
        raise HTTPException(status_code=400, detail="单个附件不能超过 30MB")
    now = datetime.now()
    rel_dir = Path(subdir) / f"{now.year}{now.month:02d}" if subdir == FINAL_SUBDIR else Path(subdir)
    target = Path(settings.UPLOAD_DIR) / rel_dir
    target.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (target / stored).write_bytes(content)
    return str(rel_dir / stored).replace("\\", "/"), Path(filename or stored).name, len(content)


def _move_temp_to_final(rel: str) -> tuple:
    """临时文件转存正式目录,返回 (新相对路径, 原始文件名后缀)。"""
    src = _temp_path(rel)
    if not src.exists():
        raise HTTPException(status_code=400, detail="临时文件不存在,请重新上传")
    ext = src.suffix.lower()
    if ext not in FILE_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型:{ext}")
    now = datetime.now()
    rel_dir = Path(FINAL_SUBDIR) / f"{now.year}{now.month:02d}"
    target_dir = Path(settings.UPLOAD_DIR) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    return str(rel_dir / stored).replace("\\", "/"), src, target_dir / stored


def _order_or_404(db: Session, order_id: int) -> LingLiao:
    order = db.get(LingLiao, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="领料单不存在")
    return order


def _detail_llname(materialname: str) -> str:
    return (materialname or "").split("/")[0].strip()


# ==================== 字典 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    names = dept_name_map(db)
    return {
        "suppliers": supplier_options(db),
        "departments": [{"id": d.id, "bm": names.get(d.id, d.name)}
                        for d in dq.order_by(Department.id).all()],
        "statuses": [{"value": k, "label": v} for k, v in STATUS_LABELS.items()],
        "perms": {"view": True, "audit": _has_audit(current)},
    }


@router.get("/materials")
def materials(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    return material_options(db)


# ==================== 列表 / 明细 / 编辑回显 ====================
@router.get("/orders")
def list_orders(
    page: int = 1, size: int = 20, rows: int = 0,
    keyword: str = "", shzt: Optional[int] = None,
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    q = list_query(db, current, keyword=keyword, shzt=shzt, bmid=bmid)
    total = q.count()
    page_size = size if not rows else rows
    items = (
        q.order_by(LingLiao.id.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1))
        .limit(max(page_size, 1))
        .all()
    )
    counts = {}
    if items:
        ids = [o.id for o in items]
        for order_id, cnt in (
            db.query(LingLiaoFile.lingliaoid, func.count(LingLiaoFile.id))
            .filter(LingLiaoFile.lingliaoid.in_(ids))
            .group_by(LingLiaoFile.lingliaoid)
            .all()
        ):
            counts[order_id] = int(cnt)
    return {"total": total, "rows": [o.to_dict(file_count=counts.get(o.id, 0)) for o in items]}


@router.get("/orders/{order_id}/details")
def order_details(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    _order_or_404(db, order_id)
    return detail_rows(db, order_id)


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    files = (
        db.query(LingLiaoFile)
        .filter(LingLiaoFile.lingliaoid == order_id)
        .order_by(LingLiaoFile.id)
        .all()
    )
    return {
        "id": order.id,
        "danno": order.danno or "",
        "bm": order.bm or "",
        "bmid": order.bmid,
        "sqren": order.sqren or "",
        "shzt": order.shzt if order.shzt is not None else 0,
        "sqriqi": order.sqriqi.strftime("%Y-%m-%d") if order.sqriqi else "",
        "gongyingshang": order.gongyingshang or "",
        "shuoming": order.shuoming or "",
        "Details": detail_rows(db, order_id),
        "files": [_file_dict(f, current) for f in files],
    }


# ==================== 保存(新增/修改) ====================
@router.post("/orders/save")
def save_order(
    data: SaveIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    sqriqi = parse_date(data.sqriqi)
    if sqriqi is None:
        raise HTTPException(status_code=400, detail="请选择申请日期")
    if not data.Details:
        raise HTTPException(status_code=400, detail="请至少添加一条领料明细")
    for idx, item in enumerate(data.Details, start=1):
        if not item.MaterialId:
            raise HTTPException(status_code=400, detail=f"第 {idx} 行材料不能为空")
        if item.num is None or float(item.num) <= 0:
            raise HTTPException(status_code=400, detail=f"第 {idx} 行申请数量必须大于 0")
        if db.get(MaterialLibrary, item.MaterialId) is None:
            raise HTTPException(status_code=400, detail=f"第 {idx} 行材料不存在")

    names = dept_name_map(db)
    moves = []
    deletes = []
    try:
        if data.id == 0:
            bmid = _default_bmid(db, current, data.bmid)
            order = LingLiao(
                danno=generate_danno(db),
                bm=names.get(bmid, ""),
                bmid=bmid,
                sqren=current.username,
                sqriqi=sqriqi,
                shzt=0,
                gongyingshang=(data.gongyingshang or "").strip(),
                shuoming=data.shuoming or "",
                modriqi=datetime.now(),
                modren=current.username,
            )
            db.add(order)
            db.flush()
        else:
            order = _order_or_404(db, data.id)
            if not _is_owner(order, current):
                raise HTTPException(status_code=403, detail="非自己创建的单据不能修改")
            if (order.shzt or 0) not in EDITABLE_STATUS:
                raise HTTPException(status_code=400, detail="当前状态不允许编辑,仅草稿和驳回状态可修改")
            order.sqriqi = sqriqi
            order.gongyingshang = (data.gongyingshang or "").strip()
            order.shuoming = data.shuoming or ""
            if data.bmid:
                new_bmid = _default_bmid(db, current, data.bmid)
                order.bmid = new_bmid
                order.bm = names.get(new_bmid, "")
            order.modriqi = datetime.now()
            order.modren = current.username

            submitted_ids = {item.id for item in data.Details if item.id > 0}
            old_details = (
                db.query(LingLiaoDetail)
                .filter(LingLiaoDetail.lingliaoid == order.id)
                .all()
            )
            for detail in old_details:
                if detail.id in submitted_ids:
                    continue
                if float(detail.renum or 0) > 0:
                    material = db.get(MaterialLibrary, detail.material_id)
                    record = (
                        db.query(InStockRecord)
                        .filter(InStockRecord.lingliao_detail_id == detail.id)
                        .first()
                    )
                    if material is not None:
                        rollback_qty = (
                            float(record.quantity or 0) if record is not None
                            else float(detail.renum or 0)
                        )
                        material.num = r1(float(material.num or 0) - rollback_qty)
                    if record is not None:
                        db.delete(record)
                db.delete(detail)
            db.flush()

        for item in data.Details:
            if item.id > 0:
                detail = db.get(LingLiaoDetail, item.id)
                if detail is None or detail.lingliaoid != order.id:
                    raise HTTPException(status_code=400, detail="领料明细不属于当前单据")
                detail.material_id = item.MaterialId
                detail.materialname = item.materialname or ""
                detail.llname = _detail_llname(item.materialname)
                detail.model = item.model or ""
                detail.spec = item.spec or ""
                detail.unit = item.unit or ""
                detail.num = item.num
                detail.beizhu = item.beizhu or ""
                detail.shuoming = item.shuoming or ""
            else:
                db.add(LingLiaoDetail(
                    sqriqi=sqriqi,
                    llname=_detail_llname(item.materialname),
                    shuoming=item.shuoming or "",
                    materialname=item.materialname or "",
                    model=item.model or "",
                    spec=item.spec or "",
                    unit=item.unit or "",
                    num=item.num,
                    renum=0,
                    material_id=item.MaterialId,
                    jiesuannum=0,
                    lingliaoid=order.id,
                    jiesuanzt=0,
                    beizhu=item.beizhu or "",
                ))
        db.flush()

        # ==================== 附件 ====================
        existing_files = (
            db.query(LingLiaoFile)
            .filter(LingLiaoFile.lingliaoid == order.id)
            .all()
        )
        submitted_file_ids = {f.Id for f in data.files if f.Id > 0}
        for file in existing_files:
            if file.id in submitted_file_ids:
                continue
            deletes.append(_att_path(file.filepath))
            db.delete(file)
        for file in data.files:
            if file.Id > 0:
                continue
            new_rel, src, dest = _move_temp_to_final(file.filepath)
            moves.append((src, dest))
            db.add(LingLiaoFile(
                lingliaoid=order.id,
                filename=file.filename or dest.name,
                filepath=new_rel,
                filesize=int(file.filesize or 0),
                uploadtime=datetime.now(),
                operator_name=current.username,
            ))

        db.commit()
        for src, dest in moves:
            try:
                shutil.move(str(src), str(dest))
            except OSError:
                pass
        for path in deletes:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return {"success": True, "id": order.id, "msg": "保存成功"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== 提交 / 审核 / 反审核 / 驳回 / 作废 / 删除 ====================
@router.post("/orders/{order_id}/submit")
def submit_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    if not _is_owner(order, current):
        raise HTTPException(status_code=403, detail="只有申请人本人才能提交")
    if (order.shzt or 0) not in SUBMITTABLE_STATUS:
        raise HTTPException(status_code=400, detail="只有草稿和驳回单据才能提交")
    if not db.query(LingLiaoDetail).filter(LingLiaoDetail.lingliaoid == order.id).first():
        raise HTTPException(status_code=400, detail="请先添加领料明细")
    order.shzt = 1
    db.commit()
    return {"success": True, "msg": "提交成功"}


@router.post("/orders/{order_id}/audit")
def audit_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:audit")),
):
    order = _order_or_404(db, order_id)
    if (order.shzt or 0) != 1:
        raise HTTPException(status_code=400, detail="只有已提交的单据才能审核")
    if not db.query(LingLiaoDetail).filter(LingLiaoDetail.lingliaoid == order.id).first():
        raise HTTPException(status_code=400, detail="请先添加领料明细")
    order.shzt = 2
    order.shren = current.username
    order.shriqi = datetime.now()
    db.commit()
    return {"success": True, "msg": "审核成功"}


@router.post("/orders/{order_id}/reverse-audit")
def reverse_audit_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:audit")),
):
    order = _order_or_404(db, order_id)
    if not current.is_superuser and order.shren != current.username:
        raise HTTPException(status_code=403, detail="只有审核人才能反审核")
    if (order.shzt or 0) != 2:
        raise HTTPException(status_code=400, detail="只有已审核单据才能反审核")
    has_renum = (
        db.query(LingLiaoDetail)
        .filter(LingLiaoDetail.lingliaoid == order.id, LingLiaoDetail.renum > 0)
        .first()
    )
    if has_renum:
        raise HTTPException(status_code=400, detail="已有实发数量,不能反审核")
    order.shzt = 1
    order.shriqi = None
    order.shren = ""
    db.commit()
    return {"success": True, "msg": "反审核成功"}


@router.post("/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:audit")),
):
    order = _order_or_404(db, order_id)
    if (order.shzt or 0) == 3:
        raise HTTPException(status_code=400, detail="该记录已经被驳回")
    if (order.shzt or 0) == 4:
        raise HTTPException(status_code=400, detail="已作废单据不能驳回")
    order.shzt = 3
    order.shren = current.username
    order.shriqi = datetime.now()
    db.commit()
    return {"success": True, "msg": "驳回成功"}


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    if not _is_owner(order, current):
        raise HTTPException(status_code=403, detail="无法作废非自己创建的单据")
    if (order.shzt or 0) not in CANCELLABLE_STATUS:
        raise HTTPException(status_code=400, detail="只有草稿和驳回单据才能作废")
    order.shzt = 4
    order.shriqi = datetime.now()
    order.shren = current.username
    db.commit()
    return {"success": True, "msg": "作废成功"}


@router.delete("/orders/{order_id}")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    if not _is_owner(order, current):
        raise HTTPException(status_code=403, detail="无法删除非自己创建的单据")
    if (order.shzt or 0) != 4:
        raise HTTPException(status_code=400, detail="只有作废的单据才能删除")
    paths = []
    for file in db.query(LingLiaoFile).filter(LingLiaoFile.lingliaoid == order.id).all():
        paths.append(_att_path(file.filepath))
        db.delete(file)
    for detail in db.query(LingLiaoDetail).filter(LingLiaoDetail.lingliaoid == order.id).all():
        db.delete(detail)
    db.delete(order)
    db.commit()
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return {"success": True, "msg": "删除成功"}


# ==================== 修改实发数量 ====================
@router.post("/orders/{order_id}/details/{detail_id}/renum")
def update_renum(
    order_id: int,
    detail_id: int,
    data: RenumIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    if (order.shzt or 0) != 2:
        raise HTTPException(status_code=400, detail="只有审核后才能修改实发数量")
    if not _is_owner(order, current):
        raise HTTPException(status_code=403, detail="只有申请人本人才能修改实发数量")
    detail = db.get(LingLiaoDetail, detail_id)
    if detail is None or detail.lingliaoid != order.id:
        raise HTTPException(status_code=404, detail="领料明细不存在")

    renum = r2(data.renum)
    if renum < 0:
        raise HTTPException(status_code=400, detail="实发数量不能为负数")
    if renum > float(detail.num or 0):
        raise HTTPException(status_code=400, detail="实发数量不能大于申请数量")
    if renum < float(detail.jiesuannum or 0):
        raise HTTPException(status_code=400, detail="实发数量不能小于已结算数量")

    material = db.get(MaterialLibrary, detail.material_id)
    if material is None:
        raise HTTPException(status_code=400, detail="材料不存在")

    old_renum = float(detail.renum or 0)
    record = (
        db.query(InStockRecord)
        .filter(InStockRecord.lingliao_detail_id == detail.id)
        .first()
    )
    old_stock = float(record.quantity or 0) if record is not None else old_renum
    new_stock = r1(renum)
    if renum == 0:
        if old_stock > 0:
            material.num = r1(float(material.num or 0) - old_stock)
        if record is not None:
            db.delete(record)
        detail.renum = 0
    else:
        material.num = r1(float(material.num or 0) + new_stock - old_stock)
        if record is None:
            db.add(InStockRecord(
                material_id=detail.material_id,
                quantity=new_stock,
                operator=current.username,
                in_stock_time=datetime.now(),
                remark="修改实发数量入库",
                lei="领料入库",
                lingliao_detail_id=detail.id,
            ))
        else:
            record.quantity = new_stock
            record.operator = current.username
            record.in_stock_time = datetime.now()
        detail.renum = renum
    db.commit()
    return {"success": True, "msg": "实发数量已更新", "renum": renum}


# ==================== 导出材料需求单 ====================
@router.get("/orders/{order_id}/export")
def export_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    order = _order_or_404(db, order_id)
    buf = build_form_excel(db, order)
    filename = f"材料需求单_{order.danno}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


# ==================== 附件:列表 / 上传 / 下载 / 删除 ====================
@router.get("/orders/{order_id}/files")
def list_files(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    _order_or_404(db, order_id)
    rows = (
        db.query(LingLiaoFile)
        .filter(LingLiaoFile.lingliaoid == order_id)
        .order_by(LingLiaoFile.uploadtime.desc(), LingLiaoFile.id.desc())
        .all()
    )
    return [_file_dict(f, current) for f in rows]


@router.post("/orders/{order_id}/files")
def upload_file(
    order_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    _order_or_404(db, order_id)
    content = file.file.read()
    rel, name, size = _save_file(content, file.filename or "")
    row = LingLiaoFile(
        lingliaoid=order_id,
        filename=name,
        filepath=rel,
        filesize=size,
        uploadtime=datetime.now(),
        operator_name=current.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "msg": "上传成功", "file": _file_dict(row, current)}


@router.post("/files/temp")
def upload_temp_file(
    file: UploadFile = File(...),
    current: User = Depends(require_permission("lingliao:view")),
):
    content = file.file.read()
    rel, name, size = _save_file(content, file.filename or "", subdir=TEMP_SUBDIR)
    token = create_short_token(
        "lingliao_temp", {"path": rel, "sub": str(current.id)},
        minutes=FILE_TOKEN_MINUTES,
    )
    return {
        "success": True,
        "filename": name,
        "filepath": rel,
        "filesize": size,
        "tempId": Path(rel).name,
        "downloadUrl": f"/api/lingliao/files/temp/download?token={token}",
    }


@router.get("/files/temp/download")
def download_temp_file(token: str = ""):
    try:
        payload = decode_short_token(token, "lingliao_temp")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    path = _temp_path(payload.get("path", ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="临时文件不存在")
    return FileResponse(path, filename=path.name)


@router.get("/files/download")
def download_file(token: str = "", db: Session = Depends(get_db)):
    try:
        payload = decode_short_token(token, "lingliao_file")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    row = db.get(LingLiaoFile, int(payload.get("fid", 0)))
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _att_path(row.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失")
    return FileResponse(path, filename=row.filename or path.name)


@router.delete("/files/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("lingliao:view")),
):
    row = db.get(LingLiaoFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    if not _can_delete_file(row, current):
        raise HTTPException(status_code=403, detail="只能删除自己上传的附件")
    try:
        _att_path(row.filepath).unlink(missing_ok=True)
    except HTTPException:
        pass
    db.delete(row)
    db.commit()
    return {"success": True, "msg": "已删除"}
