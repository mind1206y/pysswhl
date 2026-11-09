"""领料结算(照旧 jiesuandanController + jiesuandanService 1:1 复刻)。

路由挂 /api/jiesuandan。权限:
- jiesuandan:view   模块入口 + 查询/新增/编辑本人单/删除本人单/结算明细/导出/打印/附件
- jiesuandan:manage 删除他人附件(旧系统无细分权限,这里按新系统统一约定补一个管理码)

与旧系统一致的关键行为:
- 结算单只能由创建人编辑/删除;删除结算单时回滚领料明细已结算数量并重算领料单状态。
- 结算明细只能选同一供应商、已审核/部分结算且仍有剩余可结算数量的领料明细。
- 新增/修改/删除明细会同步 lingliaodetail.jiesuannum/jiesuanzt、lingliao.shzt、
  material_library.lastdanjia,并重算结算单总额 zonge。
- 新增结算单总额置 0,由明细自动汇总;编辑结算单不改总额。
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.jiesuandan import CailiaoFujian, JiesuanCailiao, JiesuanDetail
from app.models.lingliao import LingLiao, LingLiaoDetail
from app.models.material import MaterialLibrary
from app.models.user import Department, User
from app.services.jiesuandan_common import (
    build_cg_excel,
    build_settlement_excel,
    candidate_page,
    cg_rows,
    detail_rows,
    excel_disposition,
    generate_danno,
    order_query,
    parse_date,
    r4,
    recalc_lingliao_status,
    recalc_order_total,
    sort_order_query,
    supplier_options,
    update_lingliao_detail_status,
)

router = APIRouter()

ATT_SUBDIR = "Jiesuan"
ATT_TOKEN_MINUTES = 180
ATT_MAX_SIZE = 30 * 1024 * 1024
BLOCKED_EXTS = {
    ".aspx", ".ascx", ".ashx", ".asmx", ".asax", ".config",
    ".asp", ".cer", ".asa", ".cdx",
    ".jsp", ".jspx", ".php", ".php3", ".php5",
    ".exe", ".dll", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".wsf", ".scr", ".msi",
    ".html", ".htm", ".xhtml", ".shtml", ".svg", ".js", ".swf",
}


# ==================== 请求体 ====================
class OrderIn(BaseModel):
    id: int = 0
    jiesuandanno: str = ""
    gongyingshang: str = ""
    jiesuanriqi: str = ""
    beizhu: str = ""


class DetailIn(BaseModel):
    LingliaoDetailId: int
    Num: Optional[float] = None
    Danjia: Optional[float] = None


class SaveDetailsIn(BaseModel):
    Details: List[DetailIn] = []


class DetailUpdateIn(BaseModel):
    num: Optional[float] = None
    danjia: Optional[float] = None


# ==================== 公共辅助 ====================
def _has_manage(current: User) -> bool:
    if current.is_superuser:
        return True
    owned = {p.code for role in current.roles for p in role.permissions}
    return "jiesuandan:manage" in owned


def _is_owner(order: JiesuanCailiao, current: User) -> bool:
    return bool(order.createuser) and order.createuser == current.username


def _can_edit(order: JiesuanCailiao, current: User) -> bool:
    return _is_owner(order, current) or current.is_superuser


def _default_bmid(db: Session, current: User, requested: Optional[int] = None):
    scope = dept_scope_ids(db, current)
    if scope is None:
        if requested:
            return requested
        return current.departments[0].id if current.departments else None
    if requested and requested in scope:
        return requested
    return min(scope)


def _user_bm_name(db: Session, current: User, fallback: str = "") -> str:
    names = dept_name_map(db)
    depts = current.departments
    if depts:
        return names.get(depts[0].id, depts[0].name)
    return fallback


def _order_or_404(db: Session, order_id: int) -> JiesuanCailiao:
    order = db.get(JiesuanCailiao, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="结算单不存在")
    return order


def _att_root() -> Path:
    base = Path(settings.UPLOAD_DIR).resolve()
    return base


def _att_path(rel: str) -> Path:
    raw = (rel or "").replace("\\", "/").lstrip("/")
    base = _att_root()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="附件路径不合法")
    return path


def _att_token(file_id: int, current: User) -> str:
    return create_short_token(
        "jiesuandan_attach", {"fid": file_id, "sub": str(current.id)},
        minutes=ATT_TOKEN_MINUTES,
    )


def _att_dict(row: CailiaoFujian, current: User) -> dict:
    return {
        "id": row.id,
        "filename": row.filename or "",
        "filesize": int(row.filesize or 0),
        "filesizeStr": _size_str(row.filesize),
        "uploaduser": row.uploaduser or "",
        "uploadtime": row.uploadtime.strftime("%Y-%m-%d %H:%M:%S") if row.uploadtime else "",
        "canDelete": (row.uploaduser == current.username) or _has_manage(current),
        "downloadUrl": f"/api/jiesuandan/attachments/download?token={_att_token(row.id, current)}",
    }


def _size_str(size) -> str:
    n = int(size or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _save_attachment(content: bytes, filename: str, current: User, order_id: int) -> CailiaoFujian:
    ext = Path(filename or "").suffix.lower()
    if ext in BLOCKED_EXTS:
        raise HTTPException(status_code=400, detail=f"不允许上传该类型文件:{ext}")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > ATT_MAX_SIZE:
        raise HTTPException(status_code=400, detail="单个附件不能超过 30MB")
    target_dir = _att_root() / ATT_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (target_dir / stored).write_bytes(content)
    rel = f"{ATT_SUBDIR}/{stored}"
    return CailiaoFujian(
        jiesuancailiao_id=order_id,
        filename=Path(filename or stored).name,
        filepath=rel,
        filesize=len(content),
        uploaduser=current.username,
        uploadtime=datetime.now(),
    )


def _delete_att_files(db: Session, order_id: int) -> None:
    for row in db.query(CailiaoFujian).filter(CailiaoFujian.jiesuancailiao_id == order_id).all():
        try:
            _att_path(row.filepath).unlink(missing_ok=True)
        except HTTPException:
            pass
        db.delete(row)


# ==================== 字典 / 初始化 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    scope = dept_scope_ids(db, current)
    names = dept_name_map(db)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    return {
        "suppliers": supplier_options(db, current),
        "departments": [{"id": d.id, "bm": names.get(d.id, d.name)}
                        for d in dq.order_by(Department.id).all()],
        "perms": {"view": True, "manage": _has_manage(current)},
        "userBm": _user_bm_name(db, current),
    }


@router.get("/create-init")
def create_init(current: User = Depends(require_permission("jiesuandan:view"))):
    return {"jiesuandanno": generate_danno(), "createuser": current.username}


# ==================== 结算单列表 / 回显 ====================
@router.get("/orders")
def list_orders(
    page: int = 1, size: int = 20, keyword: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    q = order_query(db, current, keyword=keyword, bmid=bmid)
    total = q.count()
    page_size = max(int(size or 20), 1)
    items = (
        sort_order_query(q)
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = {}
    if items:
        ids = [o.id for o in items]
        for order_id, cnt in (
            db.query(CailiaoFujian.jiesuancailiao_id, func.count(CailiaoFujian.id))
            .filter(CailiaoFujian.jiesuancailiao_id.in_(ids))
            .group_by(CailiaoFujian.jiesuancailiao_id)
            .all()
        ):
            counts[order_id] = int(cnt)
    return {
        "total": total,
        "rows": [o.to_dict(fujian_count=counts.get(o.id, 0)) for o in items],
    }


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    return order.to_dict()


@router.get("/orders/{order_id}/details")
def get_details(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    _order_or_404(db, order_id)
    return detail_rows(db, order_id)


# ==================== 保存 / 删除结算单 ====================
@router.post("/orders/save")
def save_order(
    data: OrderIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    jiesuanriqi = parse_date(data.jiesuanriqi)
    try:
        if data.id == 0:
            order = JiesuanCailiao(
                jiesuandanno=(data.jiesuandanno or generate_danno()).strip(),
                gongyingshang=(data.gongyingshang or "").strip(),
                jiesuanriqi=jiesuanriqi,
                zonge=0,
                shzt=0,
                shriqi=datetime.now(),
                createuser=current.username,
                bmid=_default_bmid(db, current),
                beizhu=data.beizhu or "",
            )
            db.add(order)
            db.flush()
        else:
            order = _order_or_404(db, data.id)
            if not _can_edit(order, current):
                raise HTTPException(status_code=403, detail="您不是创建人,不能编辑此结算单")
            order.gongyingshang = (data.gongyingshang or "").strip()
            order.jiesuanriqi = jiesuanriqi
            order.beizhu = data.beizhu or ""
            order.shriqi = datetime.now()
        db.commit()
        return {"success": True, "id": order.id, "msg": "保存成功"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/orders/{order_id}")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    if not _can_edit(order, current):
        raise HTTPException(status_code=403, detail="您不是创建人,不能删除此结算单")
    affected = set()
    for detail in (
        db.query(JiesuanDetail).filter(JiesuanDetail.jiesuanid == order.id).all()
    ):
        ling_detail = db.get(LingLiaoDetail, detail.lingliaodetailid) if detail.lingliaodetailid else None
        if ling_detail is not None:
            ling_detail.jiesuannum = float(ling_detail.jiesuannum or 0) - float(detail.num or 0)
            update_lingliao_detail_status(ling_detail)
            if ling_detail.lingliaoid:
                affected.add(ling_detail.lingliaoid)
        db.delete(detail)
    _delete_att_files(db, order.id)
    dan_no = order.jiesuandanno
    db.delete(order)
    db.flush()
    recalc_lingliao_status(db, affected)
    db.commit()
    return {"success": True, "msg": f"删除成功,单号：{dan_no}"}


# ==================== 可结算领料明细 ====================
@router.get("/candidates")
def list_candidates(
    page: int = 1, size: int = 20, keyword: str = "", gongyingshang: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    total, rows = candidate_page(db, keyword=keyword, gongyingshang=gongyingshang,
                                 page=page, size=size)
    return {"total": total, "rows": rows}


# ==================== 结算明细:新增 / 修改 / 删除 ====================
@router.post("/orders/{order_id}/details")
def add_details(
    order_id: int,
    data: SaveDetailsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    if not _can_edit(order, current):
        raise HTTPException(status_code=403, detail="您不是创建人,不能编辑明细")
    if not data.Details:
        raise HTTPException(status_code=400, detail="请选择明细")
    affected = set()
    try:
        for item in data.Details:
            ling_detail = db.get(LingLiaoDetail, item.LingliaoDetailId)
            if ling_detail is None:
                raise HTTPException(
                    status_code=400, detail=f"领料明细 {item.LingliaoDetailId} 不存在"
                )
            main = db.get(LingLiao, ling_detail.lingliaoid) if ling_detail.lingliaoid else None
            supplier = (main.gongyingshang or "") if main is not None else ""
            if supplier.strip().lower() != (order.gongyingshang or "").strip().lower():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"材料【{ling_detail.llname}】所属供应商【{supplier}】"
                        f"与结算单供应商【{order.gongyingshang}】不一致,不能结算!"
                    ),
                )
            num = r4(item.Num)
            if num <= 0:
                raise HTTPException(
                    status_code=400, detail=f"材料【{ling_detail.llname}】结算数量必须大于 0"
                )
            shengyu = float(ling_detail.renum or 0) - float(ling_detail.jiesuannum or 0)
            if num > shengyu:
                raise HTTPException(
                    status_code=400,
                    detail=f"结算数量超出剩余数量,材料：{ling_detail.llname}",
                )
            danjia = r4(item.Danjia)
            exist = (
                db.query(JiesuanDetail)
                .filter(
                    JiesuanDetail.jiesuanid == order.id,
                    JiesuanDetail.lingliaodetailid == item.LingliaoDetailId,
                )
                .first()
            )
            if exist is not None:
                exist.num = r4(float(exist.num or 0) + num)
                exist.danjia = danjia
                exist.jine = r4(float(exist.num) * danjia)
            else:
                db.add(JiesuanDetail(
                    jiesuanid=order.id,
                    lingliaodetailid=item.LingliaoDetailId,
                    num=num,
                    danjia=danjia,
                    jine=r4(num * danjia),
                ))
            ling_detail.jiesuannum = r4(float(ling_detail.jiesuannum or 0) + num)
            update_lingliao_detail_status(ling_detail)
            if ling_detail.lingliaoid:
                affected.add(ling_detail.lingliaoid)
            material = db.get(MaterialLibrary, ling_detail.material_id) if ling_detail.material_id else None
            if material is not None:
                material.lastdanjia = danjia
        db.flush()
        recalc_lingliao_status(db, affected)
        recalc_order_total(db, order.id)
        db.commit()
        return {"success": True, "msg": "结算明细保存成功"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/details/{detail_id}")
def update_detail(
    detail_id: int,
    data: DetailUpdateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    detail = db.get(JiesuanDetail, detail_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="明细不存在")
    order = _order_or_404(db, detail.jiesuanid)
    if not _can_edit(order, current):
        raise HTTPException(status_code=403, detail="您不是创建人,不能编辑明细")
    ling_detail = db.get(LingLiaoDetail, detail.lingliaodetailid) if detail.lingliaodetailid else None
    if ling_detail is None:
        raise HTTPException(status_code=400, detail="关联的领料明细不存在")
    num = r4(data.num)
    danjia = r4(data.danjia)
    if num <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于 0")
    if danjia <= 0:
        raise HTTPException(status_code=400, detail="单价必须大于 0")
    old_num = float(detail.num or 0)
    diff = num - old_num
    if diff > (float(ling_detail.renum or 0) - float(ling_detail.jiesuannum or 0)):
        raise HTTPException(status_code=400, detail="超过可结算数量")
    if float(ling_detail.jiesuannum or 0) + diff < 0:
        raise HTTPException(status_code=400, detail="已结算数量不能为负数")
    try:
        detail.num = num
        detail.danjia = danjia
        detail.jine = r4(num * danjia)
        ling_detail.jiesuannum = r4(float(ling_detail.jiesuannum or 0) + diff)
        update_lingliao_detail_status(ling_detail)
        db.flush()
        recalc_lingliao_status(
            db, [ling_detail.lingliaoid] if ling_detail.lingliaoid else []
        )
        recalc_order_total(db, order.id)
        db.commit()
        return {"success": True, "msg": "明细已更新"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/details/{detail_id}")
def delete_detail(
    detail_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    detail = db.get(JiesuanDetail, detail_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="明细不存在")
    order = _order_or_404(db, detail.jiesuanid)
    if not _can_edit(order, current):
        raise HTTPException(status_code=403, detail="您不是创建人,不能删除明细")
    ling_detail = db.get(LingLiaoDetail, detail.lingliaodetailid) if detail.lingliaodetailid else None
    try:
        if ling_detail is not None:
            ling_detail.jiesuannum = r4(float(ling_detail.jiesuannum or 0) - float(detail.num or 0))
            update_lingliao_detail_status(ling_detail)
        db.delete(detail)
        db.flush()
        if ling_detail is not None:
            recalc_lingliao_status(
                db, [ling_detail.lingliaoid] if ling_detail.lingliaoid else []
            )
        # 旧系统此处漏算总额,新系统补齐,避免列表总额与明细不一致
        recalc_order_total(db, order.id)
        db.commit()
        return {"success": True, "msg": "明细已删除"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== 导出 / 采购单据 / 打印数据 ====================
@router.get("/orders/{order_id}/export")
def export_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    buf = build_settlement_excel(db, order)
    filename = f"销售结算表_{order.jiesuandanno or order.id}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


@router.get("/orders/{order_id}/cg-excel")
def cg_excel(
    order_id: int,
    type: int = 1,
    sgbm: str = "",
    sgyy: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    if type not in (1, 2):
        raise HTTPException(status_code=400, detail="type 只能是 1(申请单)或 2(验收单)")
    buf = build_cg_excel(
        db, order, type, sgbm=sgbm, sgyy=sgyy,
        user_bm=_user_bm_name(db, current),
    )
    prefix = "物资采购验收单" if type == 2 else "物资采购申请单"
    filename = f"{prefix}（{order.jiesuandanno or order.id}）.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


@router.get("/orders/{order_id}/print-data")
def print_data(
    order_id: int,
    sgbm: str = "",
    sgyy: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    order = _order_or_404(db, order_id)
    return {
        "main": order.to_dict(),
        "rows": cg_rows(db, order.id),
        "sgbm": sgbm or "",
        "sgyy": sgyy or "",
        "userBm": _user_bm_name(db, current),
    }


# ==================== 附件 ====================
@router.get("/orders/{order_id}/attachments")
def list_attachments(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    _order_or_404(db, order_id)
    rows = (
        db.query(CailiaoFujian)
        .filter(CailiaoFujian.jiesuancailiao_id == order_id)
        .order_by(CailiaoFujian.id)
        .all()
    )
    return [_att_dict(r, current) for r in rows]


@router.post("/orders/{order_id}/attachments")
def upload_attachments(
    order_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    _order_or_404(db, order_id)
    saved = []
    try:
        for file in files:
            content = file.file.read()
            row = _save_attachment(content, file.filename or "", current, order_id)
            db.add(row)
            saved.append(row)
        db.commit()
        for row in saved:
            db.refresh(row)
        return {"success": True, "msg": "上传成功"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/attachments/download")
def download_attachment(token: str = "", db: Session = Depends(get_db)):
    try:
        payload = decode_short_token(token, "jiesuandan_attach")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    row = db.get(CailiaoFujian, int(payload.get("fid", 0)))
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _att_path(row.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失")
    return FileResponse(path, filename=row.filename or path.name)


@router.delete("/attachments/{file_id}")
def delete_attachment(
    file_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuandan:view")),
):
    row = db.get(CailiaoFujian, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    if row.uploaduser != current.username and not _has_manage(current):
        raise HTTPException(status_code=403, detail="只能删除自己上传的附件")
    try:
        _att_path(row.filepath).unlink(missing_ok=True)
    except HTTPException:
        pass
    db.delete(row)
    db.commit()
    return {"success": True, "msg": "已删除"}
