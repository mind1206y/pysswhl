"""SIM 卡管理(照旧 simkaguanliController 全量复刻)。

权限:
- simcard:view  模块入口 + 列表/字典/子表/导出/模板下载
- simcard:manage 新增/编辑/删除/各类上传(对应旧系统「sim卡管理」权限)

上传功能:
- /import          上传 SIM 卡模板文件(卡号已存在则跳过)
- /status-import   上传批量状态更改(写字段修改日志)
- /fees/upload     上传月度话费清单(电信/移动,移动以分计)
- /reconcile       上传核对文件,回填卡信息 + 生成「剩余卡号」并直接返回结果
- /template/*      下载 SIM 卡模板 / 话费清单模板 / 批量状态更改模板
"""

from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.simcard import (
    Feiyong, SimCard, SimEditLog, SimTaocan, SimVpn, SimWangluo, SimZhuangtai,
)
from app.models.user import Department, User
from app.services.simcard_common import (
    ACCOUNT_OPTIONS, DELETED_STATUS, FIELD_DISPLAY, LOG_FIELDS, build_export,
    build_fee_template, build_rows, build_sim_template, build_status_template,
    ensure_taocan, history_value, import_fees, import_sim, import_status,
    list_query, monthly_fees, reconcile,
)

router = APIRouter()


class SimIn(BaseModel):
    bm: Optional[int] = None
    kahao: str
    xuliehao: str = ""
    imhao: str = ""
    ip: str = ""
    vpn: str = ""
    taocan: str = ""
    zt: str = ""
    yongtu: str = ""
    didian: str = ""
    wangluo: str = ""
    bz: str = ""
    glren: str = ""
    syren: str = ""
    zhanghu: str = ""


def _has_perm(user: User, code: str) -> bool:
    if user.is_superuser:
        return True
    return any(p.code == code for role in user.roles for p in role.permissions)


def _check_scope(db: Session, user: User, bmid: Optional[int]):
    scope = dept_scope_ids(db, user)
    if scope is not None and bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该部门的权限")


def _check_visible(db: Session, user: User, sim: SimCard):
    scope = dept_scope_ids(db, user)
    if scope is not None and sim.bm not in scope:
        raise HTTPException(status_code=403, detail="没有操作该卡号的权限")


def _sim_row(db: Session, sim: SimCard) -> dict:
    names = dept_name_map(db)
    return sim.to_dict(names.get(sim.bm) or "")


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="export.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


# ==================== 列表 / 字典 / 导出 / 模板 ====================
@router.get("")
def list_sims(
    page: int = 1,
    size: int = 30,
    year: Optional[int] = None,
    month: Optional[int] = None,
    bmid: str = "",
    zt: str = "",
    zhanghu: str = "",
    wangluo: str = "",
    djr: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:view")),
):
    q, y, m, _ = list_query(
        db, current, year=year, month=month, bmid=bmid, zt=zt,
        zhanghu=zhanghu, wangluo=wangluo, djr=djr, keyword=keyword,
    )
    total = q.count()
    sims = q.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "items": build_rows(db, sims, y, m),
        "year": y,
        "month": m,
    }


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [
        {"id": d.id, "name": d.name}
        for d in dq.order_by(Department.id).all()
    ]
    zts = [
        r[0] for r in db.query(SimZhuangtai.zhuangtai)
        .filter(SimZhuangtai.zhuangtai.isnot(None), SimZhuangtai.zhuangtai != "")
        .order_by(SimZhuangtai.id).all()
    ]
    if DELETED_STATUS not in zts:
        zts.append(DELETED_STATUS)
    wangluos = [
        r[0] for r in db.query(SimWangluo.wangluo)
        .filter(SimWangluo.wangluo.isnot(None), SimWangluo.wangluo != "")
        .order_by(SimWangluo.id).all()
    ]
    vpns = [
        r[0] for r in db.query(SimVpn.vpn)
        .filter(SimVpn.vpn.isnot(None), SimVpn.vpn != "")
        .order_by(SimVpn.id).all()
    ]
    taocans = [
        r[0] for r in db.query(SimTaocan.taocan)
        .filter(SimTaocan.taocan.isnot(None), SimTaocan.taocan != "")
        .order_by(SimTaocan.id).all()
    ]
    djrs = [
        r[0] for r in db.query(SimCard.dengjiren)
        .filter(SimCard.dengjiren.isnot(None), SimCard.dengjiren != "")
        .distinct().order_by(SimCard.dengjiren).all()
    ]
    today = date.today()
    return {
        "departments": departments,
        "zt": zts,
        "wangluo": wangluos,
        "vpn": vpns,
        "taocan": taocans,
        "djr": djrs,
        "zhanghu": ACCOUNT_OPTIONS,
        "default_bmid": current.departments[0].id if current.departments else None,
        "current_year": today.year,
        "current_month": today.month,
        "perms": {
            "view": True,
            "manage": _has_perm(current, "simcard:manage"),
        },
    }


@router.get("/export")
def export_sims(
    year: Optional[int] = None,
    month: Optional[int] = None,
    bmid: str = "",
    zt: str = "",
    zhanghu: str = "",
    wangluo: str = "",
    djr: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:view")),
):
    q, y, m, _ = list_query(
        db, current, year=year, month=month, bmid=bmid, zt=zt,
        zhanghu=zhanghu, wangluo=wangluo, djr=djr, keyword=keyword,
    )
    rows = build_rows(db, q.all(), y, m)
    return _xlsx_response(build_export(rows), "SIM卡列表.xlsx")


@router.get("/template/sim")
def template_sim(current: User = Depends(require_permission("simcard:view"))):
    return _xlsx_response(build_sim_template(), "SIM卡模板文件.xlsx")


@router.get("/template/fee")
def template_fee(current: User = Depends(require_permission("simcard:view"))):
    return _xlsx_response(build_fee_template(), "话费清单模板.xlsx")


@router.get("/template/status")
def template_status(current: User = Depends(require_permission("simcard:view"))):
    return _xlsx_response(build_status_template(), "批量状态更改模板.xlsx")


# ==================== 上传 ====================
@router.post("/import")
async def upload_sim(
    file: UploadFile = File(...),
    default_bmid: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    if default_bmid is not None:
        _check_scope(db, current, default_bmid)
    elif current.departments:
        default_bmid = current.departments[0].id
    data = await file.read()
    try:
        result = import_sim(db, current, data, file.filename or "", default_bmid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, **result}


@router.post("/status-import")
async def upload_status(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    data = await file.read()
    try:
        result = import_status(db, current, data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, **result}


@router.post("/fees/upload")
async def upload_fees(
    file: UploadFile = File(...),
    bmid: int = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    file_type: str = Form("telecom"),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    if not 2000 <= year <= 2100:
        raise HTTPException(status_code=400, detail="年度不合法")
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="月份不合法")
    if file_type not in ("telecom", "mobile"):
        raise HTTPException(status_code=400, detail="请选择电信或移动清单")
    if db.get(Department, bmid) is None:
        raise HTTPException(status_code=400, detail="请选择有效部门")
    _check_scope(db, current, bmid)
    data = await file.read()
    try:
        result = import_fees(db, current, data, file.filename or "", bmid, year, month, file_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, **result}


@router.post("/reconcile")
async def upload_reconcile(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    data = await file.read()
    try:
        content = reconcile(db, data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _xlsx_response(content, "sim卡核对结果文件.xlsx")


# ==================== 套餐字典 ====================
@router.delete("/taocan")
def delete_taocan(
    value: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    db.query(SimTaocan).filter(SimTaocan.taocan == value).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


# ==================== 历史 / 子表 ====================
@router.get("/{sim_id}/history")
def sim_history(
    sim_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:view")),
):
    sim = db.get(SimCard, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="卡号不存在")
    _check_visible(db, current, sim)
    dept_names = dept_name_map(db)
    logs = (
        db.query(SimEditLog).filter(SimEditLog.sim_id == sim_id)
        .order_by(SimEditLog.edit_time.desc(), SimEditLog.id.desc()).all()
    )
    items = []
    for log in logs:
        item = log.to_dict()
        item["field_name"] = FIELD_DISPLAY.get(log.field_name, log.field_name or "")
        item["old_value"] = history_value(log.field_name, log.old_value or "", dept_names)
        item["new_value"] = history_value(log.field_name, log.new_value or "", dept_names)
        items.append(item)
    return {"sim_id": sim_id, "kahao": sim.kahao, "items": items}


@router.get("/{sim_id}/fees")
def sim_fees(
    sim_id: int,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:view")),
):
    sim = db.get(SimCard, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="卡号不存在")
    _check_visible(db, current, sim)
    return monthly_fees(db, sim.kahao or "", year or date.today().year)


# ==================== 新增 / 编辑 / 删除 ====================
@router.post("")
def create_sim(
    data: SimIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    kahao = (data.kahao or "").strip()
    if not kahao:
        raise HTTPException(status_code=400, detail="请填写卡号")
    if not data.bm:
        raise HTTPException(status_code=400, detail="请选择部门")
    _check_scope(db, current, data.bm)
    if db.query(SimCard.id).filter(SimCard.kahao == kahao, SimCard.delf == 1).first():
        raise HTTPException(status_code=400, detail="该卡号已有记录")

    now = datetime.now()
    sim = SimCard(
        bm=data.bm, kahao=kahao, xuliehao=(data.xuliehao or "").strip(),
        imhao=(data.imhao or "").strip(), ip=(data.ip or "").strip(),
        vpn=(data.vpn or "").strip(), taocan=(data.taocan or "").strip(),
        zt=(data.zt or "").strip(), yongtu=(data.yongtu or "").strip(),
        didian=(data.didian or "").strip(), wangluo=(data.wangluo or "").strip(),
        bz=(data.bz or "").strip(), glren=(data.glren or "").strip(),
        syren=(data.syren or "").strip(), zhanghu=(data.zhanghu or "").strip(),
        dengjiren=current.username, bianjiren=current.username,
        djriqi=now, zhriqi=now, delf=1,
    )
    db.add(sim)
    ensure_taocan(db, sim.taocan)
    db.commit()
    db.refresh(sim)
    return {"ok": True, "sim": _sim_row(db, sim)}


@router.put("/{sim_id}")
def update_sim(
    sim_id: int,
    data: SimIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    sim = db.get(SimCard, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="卡号不存在")
    _check_visible(db, current, sim)
    kahao = (data.kahao or "").strip()
    if not kahao:
        raise HTTPException(status_code=400, detail="请填写卡号")
    if not data.bm:
        raise HTTPException(status_code=400, detail="请选择部门")
    _check_scope(db, current, data.bm)
    if db.query(SimCard.id).filter(
        SimCard.kahao == kahao, SimCard.id != sim_id
    ).first():
        raise HTTPException(status_code=400, detail="该卡号已有记录")

    old = {field: getattr(sim, field) for field in LOG_FIELDS}
    sim.kahao = kahao
    sim.xuliehao = (data.xuliehao or "").strip()
    sim.imhao = (data.imhao or "").strip()
    sim.ip = (data.ip or "").strip()
    sim.vpn = (data.vpn or "").strip()
    sim.taocan = (data.taocan or "").strip()
    sim.zt = (data.zt or "").strip()
    sim.yongtu = (data.yongtu or "").strip()
    sim.didian = (data.didian or "").strip()
    sim.wangluo = (data.wangluo or "").strip()
    sim.bz = (data.bz or "").strip()
    sim.glren = (data.glren or "").strip()
    sim.syren = (data.syren or "").strip()
    sim.zhanghu = (data.zhanghu or "").strip()
    sim.bm = data.bm
    sim.bianjiren = current.username
    sim.zhriqi = datetime.now()

    now = sim.zhriqi
    for field in LOG_FIELDS:
        old_value = "" if old.get(field) is None else str(old.get(field))
        new_value = "" if getattr(sim, field) is None else str(getattr(sim, field))
        if old_value != new_value:
            db.add(SimEditLog(
                sim_id=sim.id, field_name=field, old_value=old_value,
                new_value=new_value, edit_user=current.username,
                edit_time=now, edit_type="edit",
            ))
    ensure_taocan(db, sim.taocan)
    db.commit()
    db.refresh(sim)
    return {"ok": True, "sim": _sim_row(db, sim)}


@router.delete("/{sim_id}")
def delete_sim(
    sim_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("simcard:manage")),
):
    sim = db.get(SimCard, sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="卡号不存在")
    _check_visible(db, current, sim)
    if sim.delf != 1:
        raise HTTPException(status_code=400, detail="该卡号已删除")
    if not current.is_superuser and current.username not in (
        sim.dengjiren or "", sim.glren or ""
    ):
        raise HTTPException(status_code=403, detail="不能删除非自己建或管理的卡号")
    sim.delf = 0
    sim.kahao = f"{sim.kahao}_X"
    sim.zhriqi = datetime.now()
    sim.bianjiren = current.username
    db.commit()
    return {"ok": True}
