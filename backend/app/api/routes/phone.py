"""手机管理(照旧 shoujiController / shoujiService 复刻)。

功能:
- 列表:部门作用域 + 关键字/部门/年度/状态按钮组筛选,返回附件数量
- 台账:批量添加 PDA 编号、批量修改部门/状态/购置原因、批量删除、编辑领用信息、编辑备注
- 回收:批量确认报废、回收登记(抽屉内表单 + 列表)
- 附件:上传/下载/预览(短令牌)/删除(仅上传人)
- 字段变更日志:每次编辑写入 shouji_edit_log,历史弹窗按字段中文名展示
- 导出:照旧 19 列 Excel
- 查号:从 sim 表按号码模糊检索并展示手机卡信息(旧 GetPhones/GetDetailByNumber)

权限:
- phone:view    模块入口 + 日常操作(批量添加/编辑/批量改部门/状态/原因/回收登记/附件)
- phone:manage  旧系统 admin 侧:批量删除、确认报废、查看确认人/日期列
- phone:huishou 旧系统 otherqx「手机管理」:把状态批量改为「已回收」
"""

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.phone import Shouji, ShoujiAttachment, ShoujiEditLog, ShoujiHuishou
from app.models.simcard import SimCard
from app.models.user import Department, User
from app.services.phone_excel import build_export, excel_disposition

router = APIRouter()

STATUS_OPTIONS = ["正常使用", "待领用", "确认报废", "已回收"]
YONGTU_OPTIONS = [
    "抄表", "换表", "水费系统维护", "处理工单", "信访处理",
    "值班手机", "移动支撑", "稽查", "巡检", "其他",
]
LIYOU_OPTIONS = ["新增", "更新"]

ALLOWED_ATT_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"}
MAX_ATT_SIZE = 30 * 1024 * 1024
ATT_TOKEN_MINUTES = 30

FIELD_LABELS = {
    "bh": "编号",
    "pinpai": "品牌",
    "guige": "规格",
    "qiyongdate": "启用日期",
    "jiage": "价格",
    "bmid": "部门",
    "shiyongren": "使用人",
    "yongtu": "用途",
    "haoma": "号码",
    "huishoudate": "回收日期",
    "huishouuser": "回收人",
    "querendate": "确认日期",
    "querenuser": "确认人",
    "bz": "备注",
    "zt": "状态",
    "liyou": "购置原因",
    "caozuo": "编辑人",
    "caozuotime": "编辑日期",
    "djuser": "登记人",
    "djtime": "登记日期",
}


# ==================== 请求体 ====================
class BatchAddIn(BaseModel):
    start_num: int
    end_num: int
    qiyongdate: Optional[date] = None
    pinpai: str = ""
    guige: str = ""
    jiage: Optional[float] = None
    bmid: Optional[int] = None
    bz: str = ""


class BatchDeptIn(BaseModel):
    ids: List[int]
    new_dept_id: int


class BatchStatusIn(BaseModel):
    ids: List[int]
    status: str


class BatchLiyouIn(BaseModel):
    ids: List[int]
    liyou: str


class BatchIdsIn(BaseModel):
    ids: List[int]


class PhoneInfoIn(BaseModel):
    shiyongren: str = ""
    haoma: str = ""
    yongtu: str = ""
    bz: str = ""


class RemarkIn(BaseModel):
    remark: str = ""


class HuishouIn(BaseModel):
    huishoudate: date
    bmid: Optional[int] = None
    huishouren: str
    shuliang: int
    shuoming: str = ""


# ==================== 公共辅助 ====================
def _has_perm(user: User, code: str) -> bool:
    if user.is_superuser:
        return True
    return code in {p.code for role in user.roles for p in role.permissions}


def _get_or_404(db: Session, shouji_id: int) -> Shouji:
    record = db.get(Shouji, shouji_id)
    if record is None:
        raise HTTPException(status_code=404, detail="手机记录不存在")
    return record


def _check_visible(db: Session, record: Shouji, user: User):
    scope = dept_scope_ids(db, user)
    if scope is not None and record.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该手机记录的权限")


def _check_bmid_visible(db: Session, bmid: Optional[int], user: User):
    if bmid is None:
        return
    if db.get(Department, bmid) is None:
        raise HTTPException(status_code=400, detail="所选部门不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and bmid not in scope:
        raise HTTPException(status_code=403, detail="所选部门不在本人部门范围内")


def _log(db: Session, shouji_id: int, field_name: str, old, new, user: User):
    old_s = "" if old is None else str(old)
    new_s = "" if new is None else str(new)
    if old_s == new_s:
        return
    db.add(ShoujiEditLog(
        shouji_id=shouji_id,
        field_name=field_name,
        old_value=old_s,
        new_value=new_s,
        edit_user=user.username,
        edit_time=datetime.now(),
        edit_type="edit",
    ))


def _log_changes(db: Session, record: Shouji, changes: dict, user: User):
    for field_name, (old, new) in changes.items():
        _log(db, record.id, field_name, old, new, user)


def _row(db: Session, record: Shouji, dept_map: dict, att_count: int = 0) -> dict:
    item = record.to_dict()
    item["bm"] = dept_map.get(record.bmid, "")
    item["att_count"] = att_count
    return item


def _dept_name(db: Session, bmid: Optional[int]) -> str:
    if not bmid:
        return ""
    dept = db.get(Department, bmid)
    return dept.name if dept else ""


def _apply_filters(
    db: Session,
    user: User,
    keyword: str = "",
    bmid: Optional[int] = None,
    zts: str = "",
    rq: str = "",
    show_normal: bool = True,
    show_pending: bool = False,
):
    q = db.query(Shouji)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(Shouji.bmid.in_(scope))

    if bmid:
        q = q.filter(Shouji.bmid == bmid)

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            Shouji.shiyongren.like(like),
            Shouji.haoma.like(like),
            Shouji.bh.like(like),
            Shouji.yongtu.like(like),
            Shouji.guige.like(like),
            Shouji.pinpai.like(like),
            Shouji.zt.like(like),
            Shouji.bz.like(like),
            Shouji.liyou.like(like),
        ))

    zt_list = [s.strip() for s in (zts or "").split(",") if s.strip()]
    if zt_list:
        q = q.filter(Shouji.zt.in_(zt_list))
    elif show_pending:
        q = q.filter(Shouji.zt == "已回收")
    elif show_normal:
        q = q.filter(Shouji.zt.in_(["正常使用", "待领用"]))
    else:
        q = q.filter(~Shouji.zt.in_(["正常使用", "待领用"]))

    years = [int(y) for y in (rq or "").split(",") if y.strip().isdigit()]
    if years:
        q = q.filter(func.year(Shouji.qiyongdate).in_(years))

    return q.order_by(Shouji.qiyongdate.desc(), Shouji.bh.desc())


def _attachment_path(att: ShoujiAttachment) -> Path:
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


def _file_size_str(size: Optional[int]) -> str:
    if not size:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _attachment_row(db: Session, att: ShoujiAttachment, user: User) -> dict:
    item = att.to_dict()
    ext = Path(att.file_name or "").suffix.lower()
    item["file_size_str"] = _file_size_str(att.file_size)
    item["is_image"] = ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
    item["can_delete"] = (
        att.operator_name == user.username or _has_perm(user, "phone:manage")
    )
    return item


# ==================== 列表 / 字典 / 导出(静态路径在前) ====================
@router.get("")
def list_shouji(
    page: int = 1,
    size: int = 25,
    keyword: str = "",
    bmid: Optional[int] = None,
    zts: str = "",
    rq: str = "",
    showNormal: bool = True,
    showPending: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    q = _apply_filters(db, current, keyword=keyword, bmid=bmid, zts=zts, rq=rq,
                       show_normal=showNormal, show_pending=showPending)
    total = q.count()
    records = q.offset(max(page - 1, 0) * size).limit(size).all()
    ids = [r.id for r in records]
    att_counts = {}
    if ids:
        rows = (
            db.query(ShoujiAttachment.shouji_id, func.count(ShoujiAttachment.id))
            .filter(ShoujiAttachment.shouji_id.in_(ids))
            .group_by(ShoujiAttachment.shouji_id)
            .all()
        )
        att_counts = dict(rows)
    dept_map = {d.id: d.name for d in db.query(Department).all()}
    items = [_row(db, r, dept_map, att_counts.get(r.id, 0)) for r in records]
    return {"total": total, "items": items}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    return {
        "departments": departments,
        "status": STATUS_OPTIONS,
        "yongtu": YONGTU_OPTIONS,
        "liyou": LIYOU_OPTIONS,
        "perms": {
            "can_manage": _has_perm(current, "phone:manage"),
            "can_huishou": _has_perm(current, "phone:huishou"),
        },
    }


@router.get("/years")
def years(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    rows = (
        db.query(func.year(Shouji.qiyongdate))
        .filter(Shouji.qiyongdate.isnot(None))
        .distinct()
        .order_by(func.year(Shouji.qiyongdate).desc())
        .all()
    )
    return [r[0] for r in rows if r[0] is not None]


@router.get("/export")
def export_shouji(
    keyword: str = "",
    bmid: Optional[int] = None,
    zts: str = "",
    rq: str = "",
    showNormal: bool = True,
    showPending: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    q = _apply_filters(db, current, keyword=keyword, bmid=bmid, zts=zts, rq=rq,
                       show_normal=showNormal, show_pending=showPending)
    dept_map = {d.id: d.name for d in db.query(Department).all()}
    rows = [_row(db, record, dept_map) for record in q.yield_per(1000)]
    buf = build_export(rows)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition("基础信息导出.xlsx")},
    )


# ==================== 号码检索(旧 GetPhones / GetDetailByNumber) ====================
@router.get("/lookup")
def lookup_phones(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    query = db.query(SimCard)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            SimCard.kahao.like(like), SimCard.syren.like(like), SimCard.didian.like(like),
        ))
    rows = query.order_by(SimCard.kahao).limit(50).all()
    result = []
    for p in rows:
        suffix = ""
        if p.syren:
            suffix = f"（{p.syren}）"
        elif p.didian:
            suffix = f"（{p.didian}）"
        result.append({"value": p.kahao or "", "text": f"{p.kahao or ''}{suffix}"})
    return result


@router.get("/lookup-detail")
def lookup_detail(
    number: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    phone = db.query(SimCard).filter(SimCard.kahao == number).first()
    if phone is None:
        return None
    return {
        "yongtu": phone.yongtu or "",
        "didian": phone.didian or "",
        "shiyongren": phone.syren or "",
        "dengjiriqi": phone.zhriqi.strftime("%Y-%m-%d") if phone.zhriqi else "",
        "zt": phone.zt or "",
        "suoshubumen": _dept_name(db, phone.bm),
        "apn": phone.vpn or "",
        "yunyingshang": phone.wangluo or "",
        "taocan": phone.taocan or "",
        "guanliren": phone.glren or "",
    }


# ==================== 回收登记(静态路径) ====================
@router.get("/huishou")
def list_huishou(
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    # 照旧 GetHuishouList:回收登记列表不按部门过滤
    q = db.query(ShoujiHuishou)
    total = q.count()
    rows = (
        q.order_by(ShoujiHuishou.id.desc())
        .offset(max(page - 1, 0) * size).limit(size).all()
    )
    dept_map = {d.id: d.name for d in db.query(Department).all()}
    can_manage = _has_perm(current, "phone:manage")
    items = []
    for h in rows:
        item = h.to_dict()
        item["bm"] = dept_map.get(h.bmid, "")
        item["can_delete"] = can_manage or h.djuser == current.username
        items.append(item)
    return {"total": total, "items": items}


@router.post("/huishou")
def create_huishou(
    data: HuishouIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    if not (data.huishouren or "").strip():
        raise HTTPException(status_code=400, detail="请填写回收人")
    if not data.shuliang or data.shuliang <= 0:
        raise HTTPException(status_code=400, detail="请填写数量")
    _check_bmid_visible(db, data.bmid, current)
    h = ShoujiHuishou(
        huishoudate=datetime.combine(data.huishoudate, datetime.min.time()),
        bmid=data.bmid,
        huishouren=data.huishouren.strip(),
        shuliang=data.shuliang,
        shuoming=(data.shuoming or "").strip(),
        djuser=current.username,
        djtime=datetime.now(),
    )
    db.add(h)
    db.commit()
    return {"message": "回收记录已登记"}


@router.delete("/huishou/{huishou_id}")
def delete_huishou(
    huishou_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    h = db.get(ShoujiHuishou, huishou_id)
    if h is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if h.djuser != current.username and not _has_perm(current, "phone:manage"):
        raise HTTPException(status_code=403, detail="只能删除自己登记的记录")
    db.delete(h)
    db.commit()
    return {"message": "已删除"}


# ==================== 附件(静态路径) ====================
@router.post("/attachments/{att_id}/token")
def attachment_token(
    att_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    att = db.get(ShoujiAttachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    record = db.get(Shouji, att.shouji_id)
    if record is not None:
        _check_visible(db, record, current)
    token = create_short_token(
        "shouji_attach", {"aid": att_id, "sub": str(current.id)}, minutes=ATT_TOKEN_MINUTES
    )
    return {
        "token": token,
        "url": f"/api/phones/attachments/download?token={token}",
        "expires_minutes": ATT_TOKEN_MINUTES,
    }


@router.get("/attachments/download")
def attachment_download(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少下载令牌")
    try:
        payload = decode_short_token(token, "shouji_attach")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    att = db.get(ShoujiAttachment, int(payload.get("aid", 0)))
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _attachment_path(att)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失(旧系统物理文件未迁移)")
    return FileResponse(path, filename=att.file_name or path.name)


# ==================== 批量操作 ====================
@router.post("/batch-add")
def batch_add(
    data: BatchAddIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    _check_bmid_visible(db, data.bmid, current)
    start = min(data.start_num, data.end_num)
    end = max(data.start_num, data.end_num)
    count = 0
    for i in range(start, end + 1):
        bh = f"PDA{i}"
        if db.query(Shouji.id).filter(Shouji.bh == bh).first():
            continue
        db.add(Shouji(
            bh=bh,
            pinpai=(data.pinpai or "").strip(),
            guige=(data.guige or "").strip(),
            jiage=data.jiage,
            bmid=data.bmid,
            bz=(data.bz or "").strip(),
            qiyongdate=data.qiyongdate,
            djuser=current.username,
            djtime=datetime.now(),
            zt="待领用",
        ))
        count += 1
    db.commit()
    return {"count": count}


@router.post("/batch-dept")
def batch_dept(
    data: BatchDeptIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    _check_bmid_visible(db, data.new_dept_id, current)
    count = 0
    for sid in data.ids:
        record = db.query(Shouji).filter(Shouji.id == sid).first()
        if record is None:
            continue
        _check_visible(db, record, current)
        old = record.bmid
        if old == data.new_dept_id:
            continue
        record.bmid = data.new_dept_id
        _log(db, record.id, "bmid", old, data.new_dept_id, current)
        count += 1
    db.commit()
    return {"count": count}


@router.post("/batch-status")
def batch_status(
    data: BatchStatusIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    status = (data.status or "").strip()
    if status not in STATUS_OPTIONS:
        raise HTTPException(status_code=400, detail="状态不合法")
    if status == "已回收" and not _has_perm(current, "phone:huishou"):
        raise HTTPException(status_code=403, detail="无手机管理权限，不能设置为已回收状态")
    now = datetime.now()
    for sid in data.ids:
        record = db.query(Shouji).filter(Shouji.id == sid).first()
        if record is None:
            continue
        _check_visible(db, record, current)
        old_zt = record.zt
        old = {
            "yongtu": record.yongtu, "shiyongren": record.shiyongren,
            "haoma": record.haoma, "bz": record.bz,
        }
        record.zt = status
        record.caozuo = current.username
        record.caozuotime = now
        if status == "确认报废":
            record.querenuser = current.username
            record.querendate = now
        if status == "待领用":
            record.yongtu = None
            record.shiyongren = None
            record.haoma = None
            record.bz = None
        _log(db, record.id, "zt", old_zt, status, current)
        if status == "待领用":
            for field_name, old_value in old.items():
                _log(db, record.id, field_name, old_value, "", current)
    db.commit()
    return {"message": "状态更新成功"}


@router.post("/batch-liyou")
def batch_liyou(
    data: BatchLiyouIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    now = datetime.now()
    for sid in data.ids:
        record = db.query(Shouji).filter(Shouji.id == sid).first()
        if record is None:
            continue
        _check_visible(db, record, current)
        old = record.liyou
        record.liyou = data.liyou
        record.caozuo = current.username
        record.caozuotime = now
        _log(db, record.id, "liyou", old, data.liyou, current)
    db.commit()
    return {"message": "购置原因更新成功"}


@router.post("/batch-delete")
def batch_delete(
    data: BatchIdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:manage")),
):
    count = 0
    for sid in data.ids:
        record = db.query(Shouji).filter(Shouji.id == sid).first()
        if record is None:
            continue
        _check_visible(db, record, current)
        db.delete(record)
        count += 1
    db.commit()
    return {"count": count}


@router.post("/{shouji_id}/scrap-confirm")
def scrap_confirm(
    shouji_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:manage")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    old_zt = record.zt
    record.querenuser = current.username
    record.querendate = datetime.now()
    record.zt = "确认报废"
    _log(db, record.id, "zt", old_zt, "确认报废", current)
    db.commit()
    return {"message": "已确认报废"}


# ==================== 单条:详情 / 编辑 / 备注 / 历史 / 附件 / 打印 ====================
@router.get("/{shouji_id}")
def get_shouji(
    shouji_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    return _row(db, record, {d.id: d.name for d in db.query(Department).all()})


@router.put("/{shouji_id}/info")
def update_info(
    shouji_id: int,
    data: PhoneInfoIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    haoma = (data.haoma or "").strip()
    if haoma:
        dup = (
            db.query(Shouji.id)
            .filter(Shouji.haoma == haoma, Shouji.zt == "正常使用", Shouji.id != shouji_id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail="号码已存在")
    changes = {
        "shiyongren": (record.shiyongren, data.shiyongren),
        "haoma": (record.haoma, data.haoma),
        "yongtu": (record.yongtu, data.yongtu),
        "bz": (record.bz, data.bz),
        "zt": (record.zt, "正常使用"),
    }
    record.shiyongren = data.shiyongren
    record.haoma = data.haoma
    record.yongtu = data.yongtu
    record.bz = data.bz
    record.zt = "正常使用"
    record.caozuo = current.username
    record.caozuotime = datetime.now()
    _log_changes(db, record, changes, current)
    db.commit()
    return {"message": "更新成功"}


@router.put("/{shouji_id}/remark")
def save_remark(
    shouji_id: int,
    data: RemarkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    old = record.bz
    record.bz = data.remark
    record.caozuo = current.username
    record.caozuotime = datetime.now()
    _log(db, record.id, "bz", old, data.remark, current)
    db.commit()
    return {"message": "保存成功"}


@router.get("/{shouji_id}/history")
def edit_history(
    shouji_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    dept_map = {d.id: d.name for d in db.query(Department).all()}
    logs = (
        db.query(ShoujiEditLog)
        .filter(ShoujiEditLog.shouji_id == shouji_id)
        .order_by(ShoujiEditLog.edit_time.desc(), ShoujiEditLog.id.desc())
        .all()
    )
    items = []
    for log in logs:
        old_value = log.old_value or ""
        new_value = log.new_value or ""
        if log.field_name == "bmid":
            if old_value.isdigit():
                old_value = dept_map.get(int(old_value), old_value)
            if new_value.isdigit():
                new_value = dept_map.get(int(new_value), new_value)
        items.append({
            "id": log.id,
            "edit_time": log.edit_time.strftime("%Y-%m-%d %H:%M:%S") if log.edit_time else "",
            "edit_user": log.edit_user or "",
            "field_name": FIELD_LABELS.get(log.field_name, log.field_name),
            "raw_field": log.field_name,
            "old_value": old_value,
            "new_value": new_value,
            "edit_type": log.edit_type or "",
        })
    return items


@router.get("/{shouji_id}/attachments")
def list_attachments(
    shouji_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    rows = (
        db.query(ShoujiAttachment)
        .filter(ShoujiAttachment.shouji_id == shouji_id)
        .order_by(ShoujiAttachment.upload_time.desc(), ShoujiAttachment.id.desc())
        .all()
    )
    return {"items": [_attachment_row(db, a, current) for a in rows]}


@router.post("/{shouji_id}/attachments")
async def upload_attachment(
    shouji_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_ATT_EXTS:
        raise HTTPException(status_code=400, detail="只允许上传PDF和图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > MAX_ATT_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过30MB")

    now = datetime.now()
    subdir = Path("shouji") / str(shouji_id) / str(now.year) / str(now.month) / str(now.day)
    target = Path(settings.UPLOAD_DIR) / subdir
    target.mkdir(parents=True, exist_ok=True)
    raw_name = Path(file.filename or "file").name
    stem = Path(raw_name).stem
    stored = f"{stem}{ext}"
    counter = 1
    while (target / stored).exists():
        stored = f"{stem}_{counter}{ext}"
        counter += 1
    (target / stored).write_bytes(content)

    rel = "/Upload/" + subdir.as_posix() + "/" + stored
    att = ShoujiAttachment(
        shouji_id=shouji_id,
        file_name=raw_name,
        file_path=rel,
        file_size=len(content),
        upload_time=now,
        operator_name=current.username,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return _attachment_row(db, att, current)


@router.delete("/attachments/{att_id}")
def delete_attachment(
    att_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    att = db.get(ShoujiAttachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    if att.operator_name != current.username and not _has_perm(current, "phone:manage"):
        raise HTTPException(status_code=403, detail="只能删除自己上传的附件")
    try:
        path = _attachment_path(att)
        if path.exists():
            path.unlink()
    except HTTPException:
        pass
    db.delete(att)
    db.commit()
    return {"message": "已删除"}


@router.get("/{shouji_id}/print-data")
def print_data(
    shouji_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("phone:view")),
):
    record = _get_or_404(db, shouji_id)
    _check_visible(db, record, current)
    item = record.to_dict()
    item["bm"] = _dept_name(db, record.bmid)
    return item
