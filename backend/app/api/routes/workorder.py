"""工单领料管理(照旧 WorkOrderController + Views/WorkOrder/Index.cshtml 1:1 复刻)。

路由挂 /api/workorder。权限:
- workorder:view   模块入口 + 查询/提交领料/编辑/明细/导出/附件上传下载(旧系统仅菜单控制)
- workorder:manage 删除领料单(库存回滚的高风险操作)/删除他人附件;超管自动拥有

与旧系统的差异(按新系统统一约定):
- 部门可见范围用 dept_scope_ids 子树(旧系统严格本部门);新增记录 bmid 取登录人部门
- 「只看未领用」在 SQL 层过滤(旧系统分页后过滤,total 与每页行数不一致)
- 导出统计按部门子树收窄(旧系统 Sheet1/Sheet2 跨部门全库)
- 附件下载走短令牌 URL(<img>/window.open 带不了 Authorization),不把登录令牌放进 URL
- 外部工单详情接口地址/凭据配置在 .env,请求超时 3 秒,不可达时前端显示「暂无数据」
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.material import MaterialLibrary, MaterialRecord, WorkOrder
from app.models.user import Department, User
from app.models.workorder import WorkOrderAttachment
from app.services import workorder_external
from app.services.workorder_common import (
    EMPTY_SENTINEL, FILTER_ALL, LINGLIAO_TYPES, banzu_options, build_statistics_excel,
    by_no_rows, detail_rows, excel_disposition, order_query, order_rows, r1,
    scoped, stock_rows,
)

router = APIRouter()

ATT_SUBDIR = "WorkOrderAttachments"
ATT_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".doc", ".docx", ".xls", ".xlsx"}
ATT_MAX_SIZE = 50 * 1024 * 1024
ATT_TOKEN_MINUTES = 180

# 现场图片代理(与 jcxt/gongdan-image 同源的占位图与令牌类型)
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fccf00c30f0003050100f9e2fe6e0000000049454e44ae426082"
)
IMAGE_TOKEN_MINUTES = 180
WO_FLOW_TIMEOUT = 3  # 工单号失焦即触发,必须短超时避免卡录入


# ==================== 请求体 ====================
class SubmitItem(BaseModel):
    Id: int
    MaterialName: str = ""
    Spec: str = ""
    Qty: float
    Unit: str = ""


class SubmitIn(BaseModel):
    workOrderNo: str
    banzu: str
    lingliaotype: str
    beizhu: str = ""
    orderId: Optional[int] = None
    bmid: Optional[int] = None
    items: List[SubmitItem]


# ==================== 公共辅助 ====================
def _has_manage(current: User) -> bool:
    if current.is_superuser:
        return True
    owned = {p.code for role in current.roles for p in role.permissions}
    return "workorder:manage" in owned


def _default_bmid(db: Session, current: User, requested: Optional[int]) -> Optional[int]:
    """新增记录归属部门:多部门用户可在本人部门内自选,越界/未选兜底第一个,超管自由选。"""
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


def _external_work_order(no: str) -> dict:
    """工单号失焦取地址(与 jcxt 的 gongdan-info 同一上游服务,超时压到 3 秒)。

    返回 {success, msg, data(原始 PascalCase)},便于取 AddressStr。
    jcxt 走的是同一 `workorder_external.fetch_workorder`,只是响应字段做了规范化。
    """
    res = workorder_external.fetch_workorder(no, timeout=WO_FLOW_TIMEOUT)
    return {"success": res["success"], "msg": res["msg"], "data": res["data"]}


def _export_params(searchText: str, startDate: str, endDate: str, dakoujing: str,
                   lingliaotype: str) -> dict:
    return {
        "search_text": searchText or "", "start_date": startDate or "",
        "end_date": endDate or "", "dakoujing": dakoujing or "",
        "lingliaotype": lingliaotype or "",
    }


# ==================== 字典 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    scope = scoped(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    names = dept_name_map(db)
    return {
        "banzu": banzu_options(db, current),
        "lingliaotypes": LINGLIAO_TYPES,
        "filterTypes": [FILTER_ALL] + LINGLIAO_TYPES + ["（未分类）"],
        "emptySentinel": EMPTY_SENTINEL,
        "departments": [{"id": d.id, "bm": names.get(d.id, d.name)}
                        for d in dq.order_by(Department.id).all()],
        "perms": {"view": True, "manage": _has_manage(current)},
    }


# ==================== 选料库存 ====================
@router.get("/stocks")
def list_stocks(
    page: int = 1, size: int = 15, rows: int = 0, mohu: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    page_size = size if not rows else rows
    data, total = stock_rows(db, current, max(page, 1), max(page_size, 1), mohu)
    return {"total": total, "rows": list(data)}


# ==================== 工单列表 ====================
@router.get("/orders")
def list_orders(
    page: int = 1, size: int = 20, rows: int = 0,
    searchText: str = "", startDate: str = "", endDate: str = "",
    dakoujing: str = "", lingliaotype: str = "", unusedOnly: bool = False,
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    q = order_query(
        db, current, search_text=searchText, start_date=startDate, end_date=endDate,
        dakoujing=dakoujing, lingliaotype=lingliaotype, unused_only=unusedOnly, bmid=bmid,
    )
    total = q.count()
    page_size = size if not rows else rows
    data = (
        q.order_by(WorkOrder.create_time.desc(), WorkOrder.id.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1)).limit(max(page_size, 1)).all()
    )
    return {"total": total, "rows": order_rows(db, data)}


# ==================== 工单号查重/回显(静态路径先于动态) ====================
@router.get("/orders/by-no")
def order_by_no(
    workOrderNo: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    ext = _external_work_order(workOrderNo) if workOrderNo.strip().isdigit() else {"success": False}
    return {
        "address": (ext.get("data") or {}).get("AddressStr", "") if ext.get("success") else "",
        "details": by_no_rows(db, workOrderNo),
    }


@router.get("/orders/by-no2")
def order_by_no2(
    workOrderNo: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    return {"details": by_no_rows(db, workOrderNo)}


@router.get("/external/by-no")
def external_by_no(
    gongdanNo: str = "",
    current: User = Depends(require_permission("workorder:view")),
):
    """旧版原始字段接口(保留兼容)。工单详情抽屉请用 /external/info。"""
    return _external_work_order(gongdanNo)


@router.get("/external/info")
def external_info(
    gongdanNo: str = "",
    current: User = Depends(require_permission("workorder:view")),
):
    """工单详情抽屉 —— 与 /api/jcxt/gongdan-info 同上游、同返回结构。

    差别只在权限码用 workorder:view,让没有稽查权限的领料用户也能看工单详情。
    """
    if not gongdanNo:
        return {"success": False, "message": "工单号不能为空"}
    res = workorder_external.fetch_workorder(gongdanNo)
    if not res["success"]:
        return {"success": False, "message": res["msg"]}
    return {"success": True, "data": workorder_external.workorder_detail(res["data"] or {})}


@router.get("/external/images")
def external_images(
    flow_id: str = "", gongdanNo: str = "",
    current: User = Depends(require_permission("workorder:view")),
):
    """现场图片列表(照 jcxt/gongdan-images):固定 3 槽位 + 短令牌代理地址。"""
    res = workorder_external.fetch_workorder_images(flow_id or gongdanNo)
    if not res["success"]:
        return {"success": False, "message": res["msg"], "images": []}
    images = []
    for img in res["images"]:
        token = ""
        if img.get("url"):
            token = create_short_token(
                "workorder_wo_image", {"url": img["url"], "sub": str(current.id)},
                minutes=IMAGE_TOKEN_MINUTES,
            )
        images.append({
            "kind": img.get("kind"), "label": img.get("label"),
            "token_url": (f"/api/workorder/external/image?token={token}" if token else ""),
        })
    return {"success": True, "images": images}


@router.get("/external/image")
def external_image(token: str = ""):
    """现场图片代理,浏览器不直连内网图片服务器;仅白名单域名,缺图返回透明占位图。"""
    try:
        payload = decode_short_token(token, "workorder_wo_image")
    except Exception:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    try:
        data, content_type = workorder_external.fetch_image(payload.get("url", ""))
    except Exception:
        return Response(content=TRANSPARENT_PNG, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/orders/{order_id}/details")
def order_details(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    return detail_rows(db, order_id)


# ==================== 提交 / 删除领料单 ====================
@router.post("/orders/submit")
def submit_order(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    no = (data.workOrderNo or "").strip()
    if not no or not (data.banzu or "").strip():
        raise HTTPException(status_code=400, detail="工单号或班组不能为空")
    if not (data.lingliaotype or "").strip():
        raise HTTPException(status_code=400, detail="请选择领料类别")
    if not data.items:
        raise HTTPException(status_code=400, detail="请先选择材料")
    try:
        if data.orderId:
            order = db.get(WorkOrder, data.orderId)
            if order is None:
                raise ValueError("找不到要修改的工单")
            order.work_order_no = no
            order.banzu = data.banzu.strip()
            order.lingliaotype = data.lingliaotype.strip()
            order.beizhu = data.beizhu or ""
            order.edittime = datetime.now()
            order.editor = current.username
            # 旧明细回滚库存后删除
            for rec in db.query(MaterialRecord).filter(
                MaterialRecord.work_order_id == order.id
            ).all():
                mat = db.get(MaterialLibrary, rec.material_id)
                if mat is not None:
                    mat.num = r1(float(mat.num or 0) + float(rec.quantity or 0))
                db.delete(rec)
            db.flush()
        else:
            order = WorkOrder(
                work_order_no=no, banzu=data.banzu.strip(),
                lingliaotype=data.lingliaotype.strip(), beizhu=data.beizhu or "",
                create_time=datetime.now(), creator=current.username,
                bmid=_default_bmid(db, current, data.bmid), is_used=0,
            )
            db.add(order)
            db.flush()

        for item in data.items:
            mat = db.get(MaterialLibrary, item.Id)
            if mat is None:
                raise ValueError(f"材料 {item.MaterialName or item.Id} 未找到")
            qty = r1(item.Qty)
            if qty <= 0:
                raise ValueError("领料数量必须大于 0")
            db.add(MaterialRecord(
                work_order_id=order.id, material_id=item.Id,
                quantity=qty, create_time=datetime.now(),
            ))
            mat.num = r1(float(mat.num or 0) - qty)  # 旧系统不做库存充足校验,照旧允许负库存
        db.commit()
        return {"success": True, "id": order.id}
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
    current: User = Depends(require_permission("workorder:view")),
):
    if not _has_manage(current):
        raise HTTPException(status_code=403, detail="没有删除领料单的权限")
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    try:
        for rec in db.query(MaterialRecord).filter(
            MaterialRecord.work_order_id == order_id
        ).all():
            mat = db.get(MaterialLibrary, rec.material_id)
            if mat is not None:
                mat.num = r1(float(mat.num or 0) + float(rec.quantity or 0))
            db.delete(rec)
        # 附件记录一并清理(旧系统残留,新系统不留孤儿)
        for att in db.query(WorkOrderAttachment).filter(
            WorkOrderAttachment.workorderid == order_id
        ).all():
            try:
                _att_path(att.filepath).unlink(missing_ok=True)
            except HTTPException:
                pass
            db.delete(att)
        db.delete(order)
        db.commit()
        return {"success": True}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== 导出 3 Sheet ====================
@router.get("/export")
def export_statistics(
    searchText: str = "", startDate: str = "", endDate: str = "",
    dakoujing: str = "", lingliaotype: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    buf = build_statistics_excel(db, current, _export_params(
        searchText, startDate, endDate, dakoujing, lingliaotype))
    name = f"领料统计_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(name)},
    )


# ==================== 附件 ====================
@router.get("/attachments")
def list_attachments(
    workorderid: int, page: int = 1, size: int = 15, rows: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    q = db.query(WorkOrderAttachment).filter(
        WorkOrderAttachment.workorderid == workorderid)
    total = q.count()
    page_size = size if not rows else rows
    items = (
        q.order_by(WorkOrderAttachment.uploadtime.desc(), WorkOrderAttachment.id.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1)).limit(max(page_size, 1)).all()
    )
    result = []
    for att in items:
        can = (att.operator_name == current.username) or _has_manage(current)
        token = create_short_token(
            "workorder_attach", {"aid": att.id, "sub": str(current.id)},
            minutes=ATT_TOKEN_MINUTES,
        )
        result.append(att.to_dict(can_delete=can, token=token))
    return {"total": total, "rows": result}


@router.post("/attachments")
def upload_attachment(
    workorderid: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    if db.get(WorkOrder, workorderid) is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ATT_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型:{ext or '无扩展名'}")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > ATT_MAX_SIZE:
        raise HTTPException(status_code=400, detail="单个附件不能超过 50MB")
    now = datetime.now()
    rel_dir = Path(ATT_SUBDIR) / f"{now.year}{now.month:02d}"
    target = Path(settings.UPLOAD_DIR) / rel_dir
    target.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (target / stored).write_bytes(content)
    att = WorkOrderAttachment(
        workorderid=workorderid, filename=file.filename or stored,
        filepath=str(rel_dir / stored).replace("\\", "/"),
        filesize=len(content), uploadtime=now, operator_name=current.username,
    )
    db.add(att)
    db.commit()
    return {"success": True, "msg": "上传成功", "fileName": att.filename, "id": att.id}


@router.get("/attachments/download")
def download_attachment(token: str = "", db: Session = Depends(get_db)):
    """短令牌下载:window.open 无法带 Authorization,令牌 180 分钟有效。"""
    try:
        payload = decode_short_token(token, "workorder_attach")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    att = db.get(WorkOrderAttachment, int(payload.get("aid", 0)))
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _att_path(att.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失")
    return FileResponse(path, filename=att.filename or path.name)


@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("workorder:view")),
):
    att = db.get(WorkOrderAttachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    if att.operator_name != current.username and not _has_manage(current):
        raise HTTPException(status_code=403, detail="只能删除自己上传的附件")
    try:
        _att_path(att.filepath).unlink(missing_ok=True)
    except HTTPException:
        pass
    db.delete(att)
    db.commit()
    return {"success": True}
