"""工单材料库(照旧 MaterialLibraryController 1:1 复刻)。

权限:
- material:view   模块入口 + 列表/入库/库存调整/盘点/预警/导出/图片(照旧人人可用)
- material:manage 添加材料/删除材料/删除入库记录/双击编辑材料
  (对应旧系统 pdqx(user, "工单管理") || admin)

口径:
- 库存数/数量一律 1 位小数(照旧 Math.Round(x,1))
- 新增材料归属当前登录人部门;bmid 筛选自动收窄到本人部门子树
- 入库记录仅限本人编辑/删除(照旧);删除材料需无任何出入库记录
- 图片走短令牌 GET /api/materials/image?token=...,<img> 不带 Authorization
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image as PILImage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.material import InStockRecord, MaterialImage, MaterialLibrary, WorkOrder
from app.models.user import User
from app.services.material_common import (
    build_in_out_excel,
    build_stock_check_excel,
    build_stock_rows,
    excel_disposition,
    images_for_materials,
    in_out_records,
    split_keywords,
    stock_query,
)

router = APIRouter()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
IMAGE_TOKEN_MINUTES = 180
IMAGE_SUBDIR = "MaterialImages"


# ==================== 请求体 ====================
class MaterialIn(BaseModel):
    id: int = 0
    MaterialName: str
    biaoji: str = ""
    Alias1: str = ""
    Alias2: str = ""
    Alias3: str = ""
    Model: str = ""
    Spec: str = ""
    Unit: str = ""
    dakoujing: Optional[str] = None
    yujing: Optional[float] = None
    Remark: str = ""


class InStockIn(BaseModel):
    id: int = 0
    MaterialId: int
    Quantity: float
    Remark: str = ""
    InStockTime: Optional[str] = None


class AdjustIn(BaseModel):
    materialId: int
    adjustQuantity: float
    reason: str


class StockCheckItem(BaseModel):
    MaterialId: int
    CheckNum: float


class StockCheckIn(BaseModel):
    list: List[StockCheckItem]


# ==================== 公共辅助 ====================
def _get_material_or_404(db: Session, mid: int) -> MaterialLibrary:
    row = db.get(MaterialLibrary, mid)
    if row is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    return row


def _default_bmid(db: Session, user: User) -> Optional[int]:
    """新增材料归属部门:本人第一个部门(照旧 bumen.id),超管无部门时置 NULL。"""
    if user.departments:
        return min(d.id for d in user.departments)
    return None


def _image_path(rel: str) -> Path:
    raw = (rel or "").replace("\\", "/").lstrip("/")
    if raw.lower().startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="图片路径不合法")
    return path


def _r1(v):
    return round(float(v), 1)


# ==================== 字典 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    from app.api.deps import dept_name_map
    from app.models.user import Department

    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    names = dept_name_map(db)
    departments = [{"id": d.id, "bm": names.get(d.id, d.name)} for d in dq.order_by(Department.id).all()]

    categories = [
        {"value": r[0], "text": r[0]}
        for r in db.query(MaterialLibrary.model).distinct()
        .filter(MaterialLibrary.model.isnot(None), MaterialLibrary.model != "")
        .order_by(MaterialLibrary.model).all()
    ]
    specs = [
        {"value": r[0], "text": r[0]}
        for r in db.query(MaterialLibrary.spec).distinct()
        .filter(MaterialLibrary.spec.isnot(None), MaterialLibrary.spec != "")
        .order_by(MaterialLibrary.spec).all()
    ]
    specs.append({"value": "其他", "text": "其他"})

    # 入库/调整下拉材料(照旧 GetMaterialsForInStock DisplayText)
    materials = []
    mq = db.query(MaterialLibrary)
    if scope is not None:
        mq = mq.filter(MaterialLibrary.bmid.in_(scope))
    for m in (
        mq.order_by(MaterialLibrary.material_name, MaterialLibrary.model, MaterialLibrary.spec).all()
    ):
        text = f"{m.material_name}({m.model})({m.spec})"
        if m.alias1:
            text += f" [{m.alias1}]"
        if m.alias2:
            text += f" [{m.alias2}]"
        materials.append({
            "Id": m.id,
            "MaterialName": m.material_name,
            "Model": m.model,
            "Spec": m.spec,
            "Unit": m.unit,
            "DisplayText": text,
        })

    return {
        "departments": departments,
        "categories": categories,
        "specs": specs,
        "materials": materials,
        "perms": {"view": True, "manage": _is_manage(current)},
    }


def _is_manage(current: User) -> bool:
    if current.is_superuser:
        return True
    owned = {p.code for role in current.roles for p in role.permissions}
    return "material:manage" in owned


# ==================== 材料库存列表 ====================
@router.get("")
def list_stocks(
    page: int = 1,
    size: int = 30,
    mohu: str = "",
    dakoujing: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    q = stock_query(db, current, dakoujing=dakoujing, bmid=bmid, keywords=split_keywords(mohu))
    total = q.count()
    rows = (
        q.order_by(MaterialLibrary.material_name, MaterialLibrary.model, MaterialLibrary.spec)
        .offset((page - 1) * size).limit(size).all()
    )
    return {"rows": build_stock_rows(db, rows, user_id=current.id), "total": total}


# ==================== 库存预警 ====================
@router.get("/warning")
def stock_warning(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    """照旧 GetStockWarning:不限部门,库存 < 预警值的材料按库存升序。"""
    rows = (
        db.query(MaterialLibrary)
        .filter(
            MaterialLibrary.yujing.isnot(None),
            MaterialLibrary.num < MaterialLibrary.yujing,
        )
        .order_by(MaterialLibrary.num)
        .all()
    )
    return [
        {
            "Id": m.id,
            "MaterialName": m.material_name or "",
            "Model": m.model or "",
            "Spec": m.spec or "",
            "StockQuantity": round(float(m.num or 0), 1),
            "yujing": round(float(m.yujing), 1) if m.yujing is not None else 0.0,
            "Unit": m.unit or "",
            "Remark": m.remark or "",
        }
        for m in rows
    ]


# ==================== 材料 CRUD ====================
@router.post("")
def save_material(
    data: MaterialIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    name = (data.MaterialName or "").strip()
    model = (data.Model or "").strip()
    spec = (data.Spec or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="材料名称不能为空")

    exists = (
        db.query(MaterialLibrary.id)
        .filter(
            MaterialLibrary.material_name == name,
            MaterialLibrary.model == model,
            MaterialLibrary.spec == spec,
            MaterialLibrary.id != data.id,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该材料名称和规格已存在，请勿重复录入")

    if data.id == 0:
        m = MaterialLibrary(
            material_name=name, model=model, spec=spec,
            unit=(data.Unit or "").strip(), remark=(data.Remark or "").strip(),
            biaoji=(data.biaoji or "").strip(),
            alias1=(data.Alias1 or "").strip(), alias2=(data.Alias2 or "").strip(),
            alias3=(data.Alias3 or "").strip(),
            dakoujing="on" if data.dakoujing else None,
            yujing=_r1(data.yujing) if data.yujing is not None else None,
            bmid=_default_bmid(db, current),
            num=0,
        )
        db.add(m)
        db.commit()
        return {"ok": True, "id": m.id}

    m = _get_material_or_404(db, data.id)
    m.material_name = name
    m.model = model
    m.spec = spec
    m.unit = (data.Unit or "").strip()
    m.remark = (data.Remark or "").strip()
    m.biaoji = (data.biaoji or "").strip()
    m.alias1 = (data.Alias1 or "").strip()
    m.alias2 = (data.Alias2 or "").strip()
    m.alias3 = (data.Alias3 or "").strip()
    m.dakoujing = "on" if data.dakoujing else None
    m.yujing = _r1(data.yujing) if data.yujing is not None else None
    db.commit()
    return {"ok": True, "id": m.id}


# ==================== 入库 ====================
@router.post("/in-stock")
def save_in_stock(
    data: InStockIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    qty = _r1(data.Quantity)
    if data.id == 0:
        _get_material_or_404(db, data.MaterialId)
        rec = InStockRecord(
            material_id=data.MaterialId,
            quantity=qty,
            operator=current.username,
            in_stock_time=datetime.now(),
            remark=(data.Remark or "").strip(),
            lei="入库",
        )
        db.add(rec)
        m = db.get(MaterialLibrary, data.MaterialId)
        m.num = _r1(float(m.num or 0) + qty)
        db.commit()
        return {"ok": True, "id": rec.id}

    rec = db.get(InStockRecord, data.id)
    if rec is None:
        raise HTTPException(status_code=404, detail="入库记录不存在")
    if (rec.operator or "") != (current.username or "") and not current.is_superuser:
        raise HTTPException(status_code=403, detail="不能编辑非自己创建的记录")
    old_mat = db.get(MaterialLibrary, rec.material_id)
    if old_mat is not None:
        old_mat.num = _r1(float(old_mat.num or 0) - float(rec.quantity or 0))
    new_mat = db.get(MaterialLibrary, data.MaterialId)
    if new_mat is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    rec.material_id = data.MaterialId
    rec.quantity = qty
    rec.remark = (data.Remark or "").strip()
    if data.InStockTime:
        try:
            rec.in_stock_time = datetime.strptime(data.InStockTime, "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    rec.operator = current.username
    new_mat.num = _r1(float(new_mat.num or 0) + qty)
    db.commit()
    return {"ok": True}


@router.get("/in-stock/{rid}")
def get_in_stock(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    rec = db.get(InStockRecord, rid)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    d = rec.to_dict()
    mat = db.get(MaterialLibrary, rec.material_id)
    d["MaterialName"] = mat.material_name if mat else ""
    d["Spec"] = mat.spec if mat else ""
    d["Unit"] = mat.unit if mat else ""
    d["InStockTime"] = rec.in_stock_time.strftime("%Y-%m-%d %H:%M") if rec.in_stock_time else None
    return d


@router.delete("/in-stock/{rid}")
def delete_in_stock(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:manage")),
):
    rec = db.get(InStockRecord, rid)
    if rec is None:
        raise HTTPException(status_code=404, detail="入库记录不存在")
    if (rec.operator or "") != (current.username or "") and not current.is_superuser:
        raise HTTPException(status_code=403, detail="不能删除非自己创建的记录")
    m = db.get(MaterialLibrary, rec.material_id)
    if m is not None:
        m.num = _r1(float(m.num or 0) - float(rec.quantity or 0))
    db.delete(rec)
    db.commit()
    return {"ok": True}


# ==================== 库存调整 ====================
@router.post("/adjust")
def adjust_stock(
    data: AdjustIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    m = _get_material_or_404(db, data.materialId)
    old = round(float(m.num or 0), 1)
    adj = _r1(data.adjustQuantity)
    m.num = _r1(old + adj)
    db.add(InStockRecord(
        material_id=m.id,
        quantity=adj,
        operator=current.username,
        in_stock_time=datetime.now(),
        lei="调整库存",
        remark=f"库存调整：{(data.reason or '').strip()}（原库存：{old}，调整：{adj}，新库存：{round(float(m.num), 1)}）",
    ))
    db.commit()
    return {"ok": True}


# ==================== 盘点 ====================
@router.post("/stock-check")
def submit_stock_check(
    data: StockCheckIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    if not data.list:
        raise HTTPException(status_code=400, detail="没有需要盘点的数据")
    for item in data.list:
        m = db.get(MaterialLibrary, item.MaterialId)
        if m is None:
            raise HTTPException(status_code=404, detail=f"材料不存在，ID：{item.MaterialId}")
        old = round(float(m.num or 0), 1)
        check = _r1(item.CheckNum)
        diff = round(check - old, 1)
        if diff == 0:
            continue
        m.num = check
        db.add(InStockRecord(
            material_id=m.id,
            quantity=diff,
            operator=current.username,
            in_stock_time=datetime.now(),
            lei="盘点调整",
            remark=f"盘点调整（原库存:{old}，盘点:{check}，差异:{diff}）",
        ))
    db.commit()
    return {"ok": True}


# ==================== 进出库记录 ====================
@router.get("/in-out")
def list_in_out(
    page: int = 1,
    size: int = 30,
    bmid: Optional[int] = None,
    direction: str = "",
    StartDate: str = "",
    EndDate: str = "",
    mohu: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    rows, total = in_out_records(
        db, current, page, size, bmid=bmid, direction=direction,
        start_date=StartDate, end_date=EndDate, mohu=mohu,
    )
    return {"rows": rows, "total": total}


# ==================== 导出 ====================
@router.get("/export-stock-check")
def export_stock_check(
    dakoujing: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    q = db.query(MaterialLibrary)
    if dakoujing:
        q = q.filter(MaterialLibrary.dakoujing.isnot(None), MaterialLibrary.dakoujing != "")
    buf = build_stock_check_excel(q.all())
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition("材料盘点表.xlsx")},
    )


@router.get("/export-in-out")
def export_in_out(
    bmid: Optional[int] = None,
    StartDate: str = "",
    EndDate: str = "",
    mohu: str = "",
    direction: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    """照旧 ExportInOutRecords:导出全部符合条件的合并记录(不分页)。"""
    page_size = 1 << 30
    rows, _total = in_out_records(
        db, current, 1, page_size, bmid=bmid, direction=direction,
        start_date=StartDate, end_date=EndDate, mohu=mohu,
    )
    buf = build_in_out_excel(rows)
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition("进出库记录.xlsx")},
    )


# ==================== 图片 ====================
@router.post("/images")
def upload_images(
    materialId: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    _get_material_or_404(db, materialId)
    now = datetime.now()
    target = Path(settings.UPLOAD_DIR) / IMAGE_SUBDIR / str(now.year) / f"{now.month:02d}"
    target.mkdir(parents=True, exist_ok=True)

    saved = 0
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in IMAGE_EXTS:
            raise HTTPException(status_code=400, detail=f"只允许上传图片,不支持 {ext or '无扩展名'}")
        content = f.file.read()
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"图片超过 10MB:{f.filename}")
        stored = f"{uuid.uuid4().hex}{ext}"
        full = target / stored
        # 主图压缩(照旧 60% 质量,非 JPEG 保持原格式)
        try:
            import io

            img = PILImage.open(io.BytesIO(content))
            if ext in (".jpg", ".jpeg"):
                img = img.convert("RGB")
                img.save(full, "JPEG", quality=60)
            else:
                full.write_bytes(content)
        except Exception:
            full.write_bytes(content)
        # 缩略图 120x120(照旧 MakeThumbnail)
        thumb_name = f"thumb_{uuid.uuid4().hex}.jpg"
        thumb_full = target / thumb_name
        try:
            img = PILImage.open(full)
            img.thumbnail((120, 120))
            img.convert("RGB").save(thumb_full, "JPEG", quality=70)
        except Exception:
            thumb_full = full

        rel = f"/Upload/{IMAGE_SUBDIR}/{now.year}/{now.month:02d}/"
        db.add(MaterialImage(
            material_id=materialId,
            file_name=f.filename or stored,
            file_path=f"{rel}{stored}",
            thumb_path=f"{rel}{thumb_name}",
            file_size=len(content),
            create_time=now,
        ))
        saved += 1
    db.commit()
    return {"ok": True, "count": saved}


@router.get("/images")
def get_images(
    id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    """返回缩略图/原图短令牌 URL(照旧 GetImages,改为令牌取图)。"""
    imgs = (
        db.query(MaterialImage)
        .filter(MaterialImage.material_id == id)
        .order_by(MaterialImage.id).all()
    )
    out = []
    for img in imgs:
        t1 = create_short_token("material_image", {"iid": img.id, "sub": str(current.id)},
                                minutes=IMAGE_TOKEN_MINUTES)
        t2 = create_short_token("material_image", {"iid": img.id, "sub": str(current.id), "thumb": 1},
                                minutes=IMAGE_TOKEN_MINUTES)
        out.append({
            "Id": img.id,
            "id": img.id,
            "FileName": img.file_name or "",
            "FilePath": f"/api/materials/image?token={t1}",
            "ThumbPath": f"/api/materials/image?token={t2}",
        })
    return out


@router.get("/image")
def image_file(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "material_image")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    img = db.get(MaterialImage, int(payload.get("iid", 0)))
    if img is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    rel = img.thumb_path if payload.get("thumb") else img.file_path
    path = _image_path(rel)
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件缺失(旧系统生产服务器 Upload/MaterialImages 未拷入)")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/images/{img_id}")
def delete_image(
    img_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    img = db.get(MaterialImage, img_id)
    if img is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    for rel in (img.file_path, img.thumb_path):
        try:
            p = _image_path(rel)
            if p.exists():
                p.unlink()
        except Exception:
            pass
    db.delete(img)
    db.commit()
    return {"ok": True}


# ==================== 材料 CRUD(动态路由放最后,避免吞掉 /in-out 等静态路径) ====================
@router.get("/{mid}")
def get_material(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:view")),
):
    m = _get_material_or_404(db, mid)
    d = m.to_dict()
    d["StockQuantity"] = round(float(m.num or 0), 1)
    return d


@router.delete("/{mid}")
def delete_material(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("material:manage")),
):
    m = _get_material_or_404(db, mid)
    from app.models.material import MaterialRecord

    in_count = db.query(InStockRecord.id).filter(InStockRecord.material_id == mid).count()
    out_count = db.query(MaterialRecord.id).filter(MaterialRecord.material_id == mid).count()
    if in_count > 0 or out_count > 0:
        raise HTTPException(status_code=400, detail="该材料已有入库或领料记录，无法删除！")
    for img in db.query(MaterialImage).filter(MaterialImage.material_id == mid).all():
        try:
            p = _image_path(img.file_path)
            if p.exists():
                p.unlink()
            pt = _image_path(img.thumb_path)
            if pt.exists() and pt != p:
                pt.unlink()
        except Exception:
            pass
        db.delete(img)
    db.delete(m)
    db.commit()
    return {"ok": True}
