"""合同登记(htdj)+ 合同归集(htgj)接口,业务照旧系统 htdjController / htgjController。

- 登记页:只看自己提交的合同,登记/编辑/删除/锁定/上传PDF/导出。
- 归集页:看本部门(含子部门)合同,归集/取消归集/编辑归集备注/按年度+提交人+金额筛选/导出。
- 附件按旧库 ht_tp 存路径,物理文件放 backend/uploads/htdjPDF/;下载走短时效令牌直链。
"""

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import jwt as pyjwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import (
    dept_name_map,
    dept_scope_ids,
    require_any_permission,
    require_permission,
)
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.contract import HtAdd, HtTp, HtZbSupplier
from app.models.user import Department, User
from app.services.contract_common import (
    check_text_len,
    contract_dict,
    dicts_payload,
    display_name,
    load_related,
)
from app.services.contract_excel import build_excel

router = APIRouter()

MAX_PDF_SIZE = 50 * 1024 * 1024
FILE_TOKEN_MINUTES = 30
MOHU_FIELDS = ("bz", "allbh", "biaodi", "duixiang", "nr", "lvxingqingkuang", "leibie", "name", "djuser_name", "zt")


class SupplierIn(BaseModel):
    gongyingshang: Optional[str] = ""
    toubiaojia: Optional[Decimal] = None
    zuizhongjia: Optional[Decimal] = None
    paixu: Optional[int] = None
    sfzb: Optional[bool] = None
    swfs: Optional[Decimal] = None
    jsfs: Optional[Decimal] = None
    jgfs: Optional[Decimal] = None
    zfs: Optional[Decimal] = None
    beizhu: Optional[str] = ""


class ContractIn(BaseModel):
    niandu: Optional[int] = None
    bumenid: Optional[int] = None
    lvxingqingkuang: Optional[str] = ""
    leibie: Optional[str] = ""
    name: Optional[str] = ""
    biaodi: Optional[str] = ""
    nr: Optional[str] = ""
    qddate: Optional[datetime] = None
    duixiang: Optional[str] = ""
    jine: Optional[Decimal] = None
    ssdate: Optional[datetime] = None
    zzdate: Optional[datetime] = None
    beizhu: Optional[str] = ""
    zhaobiaofangshi: Optional[str] = None
    kongzhijia: Optional[Decimal] = None
    sfwjdw: Optional[bool] = None
    suppliers: Optional[List[SupplierIn]] = None


class MemoIn(BaseModel):
    bz: Optional[str] = ""


def _display(user: User) -> str:
    return display_name(user)


def _ensure_required(data: ContractIn):
    missing = []
    for field, label in (
        ("niandu", "合同年度"), ("name", "合同名称"), ("biaodi", "合同标的"),
        ("nr", "简要内容"), ("duixiang", "签订对象"), ("jine", "金额"),
        ("qddate", "签订时间"), ("ssdate", "实施时间"),
    ):
        value = getattr(data, field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(label)
    if missing:
        raise HTTPException(status_code=400, detail="请填写:" + "、".join(missing))
    if not (1900 <= int(data.niandu) <= 2100):
        raise HTTPException(status_code=400, detail="合同年度需在 1900~2100 之间")
    try:
        check_text_len(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _trim(value):
    return value.strip() if isinstance(value, str) else value


def _own_condition(user: User):
    """登记页只看自己提交的合同;历史数据 djuser 可能为空,用姓名快照兜底。"""
    name = _display(user)
    cond = HtAdd.djuser == user.id
    if name:
        cond = or_(cond, and_(HtAdd.djuser.is_(None), HtAdd.djuser_name == name))
    return cond


def _collect_scope(db: Session, user: User):
    """归集页数据范围:本部门+子部门;非超管且未挂部门直接拒绝。"""
    if user.is_superuser:
        return None
    if not user.departments:
        raise HTTPException(status_code=403, detail="当前账号未关联部门,无法使用合同归集")
    return dept_scope_ids(db, user)


def _can_view_contract(db: Session, user: User, row: HtAdd) -> bool:
    if user.is_superuser:
        return True
    if row.djuser == user.id:
        return True
    name = _display(user)
    if row.djuser is None and name and row.djuser_name == name:
        return True
    scope = _collect_scope(db, user) if user.departments else None
    return scope is not None and row.bumenid in scope


def _ensure_can_edit(db: Session, user: User, row: HtAdd):
    if user.is_superuser or row.djuser == user.id:
        return
    name = _display(user)
    if row.djuser is None and name and row.djuser_name == name:
        return
    raise HTTPException(status_code=403, detail="只能操作自己登记的合同")


def _get_row(db: Session, row_id: int) -> HtAdd:
    row = db.get(HtAdd, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return row


def _filter_contracts(
    query,
    mohu: str = "",
    nd: str = "",
    tjr: str = "",
    jinedayu: str = "",
):
    """列表/导出共用筛选(照旧 htgj GetList + LoadSearchEntities)。"""
    if nd.strip():
        years = [int(x) for x in nd.split(",") if x.strip().isdigit()]
        if years:
            query = query.filter(HtAdd.niandu.in_(years))
    if tjr.strip():
        query = query.filter(HtAdd.djuser_name == tjr.strip())
    if jinedayu.strip():
        try:
            value = Decimal(jinedayu.strip())
        except Exception:
            value = Decimal(0)
        if value > 0:
            query = query.filter(HtAdd.jine.isnot(None), HtAdd.jine >= value * 10000)
    keyword = mohu.strip()
    if keyword:
        numeric = None
        try:
            numeric = Decimal(keyword)
        except Exception:
            pass
        if numeric is not None and numeric != 0:
            query = query.filter(HtAdd.jine == numeric)
        else:
            like = f"%{keyword}%"
            query = query.filter(or_(*[getattr(HtAdd, f).like(like) for f in MOHU_FIELDS]))
    return query


def _attach_related(db: Session, rows: list) -> list:
    names = dept_name_map(db)
    related = load_related(db, [r.id for r in rows])
    out = []
    for r in rows:
        tps, suppliers = related.get(r.id, ([], []))
        out.append(contract_dict(r, names, tps, suppliers))
    return out


def _department_for_create(db: Session, user: User, bumenid: Optional[int]) -> Department:
    if user.is_superuser:
        if not bumenid:
            raise HTTPException(status_code=400, detail="请选择合同所属部门")
        dept = db.get(Department, bumenid)
        if dept is None:
            raise HTTPException(status_code=400, detail="部门不存在")
        return dept
    mine = list(user.departments)
    if not mine:
        raise HTTPException(status_code=400, detail="当前账号未关联部门,无法登记合同")
    ids = {d.id for d in mine}
    dept_id = bumenid if bumenid in ids else mine[0].id
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=400, detail="部门不存在")
    return dept


def _apply_supplier(row: HtAdd, suppliers: List[SupplierIn], db: Session):
    db.query(HtZbSupplier).filter(HtZbSupplier.htid == row.id).delete(synchronize_session=False)
    for s in suppliers:
        scores = [v for v in (s.swfs, s.jsfs, s.jgfs) if v is not None]
        zfs = sum(scores) if scores else s.zfs
        db.add(HtZbSupplier(
            htid=row.id,
            gongyingshang=_trim(s.gongyingshang) or "",
            toubiaojia=s.toubiaojia,
            zuizhongjia=s.zuizhongjia,
            paixu=s.paixu,
            sfzb=s.sfzb,
            swfs=s.swfs,
            jsfs=s.jsfs,
            jgfs=s.jgfs,
            zfs=zfs,
            beizhu=_trim(s.beizhu) or "",
        ))


def _apply_common(row: HtAdd, data: ContractIn):
    row.name = _trim(data.name)
    row.biaodi = _trim(data.biaodi)
    row.nr = _trim(data.nr)
    row.qddate = data.qddate
    row.duixiang = _trim(data.duixiang)
    row.jine = data.jine
    row.ssdate = data.ssdate
    row.zzdate = data.zzdate
    row.beizhu = _trim(data.beizhu)
    row.lvxingqingkuang = _trim(data.lvxingqingkuang)
    row.leibie = _trim(data.leibie)


def _apply_zb(row: HtAdd, data: ContractIn):
    row.zhaobiaofangshi = _trim(data.zhaobiaofangshi) or None
    row.kongzhijia = data.kongzhijia
    row.sfwjdw = data.sfwjdw


# ==================== 字典 / 下拉 ====================
@router.get("/dicts")
def get_dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_any_permission("contract:view", "contract:collect", "contract:manage")),
):
    data = dicts_payload()
    data["departments"] = [
        {"id": d.id, "name": d.name, "htdaihao": d.htdaihao or ""}
        for d in db.query(Department).order_by(Department.id).all()
    ]
    data["my_departments"] = [
        {"id": d.id, "name": d.name, "htdaihao": d.htdaihao or ""} for d in current.departments
    ]
    data["current_year"] = datetime.now().year
    return data


@router.get("/years")
def get_register_years(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:view")),
):
    query = db.query(HtAdd.niandu).filter(HtAdd.niandu.isnot(None))
    if not current.is_superuser:
        query = query.filter(_own_condition(current))
    return sorted({r[0] for r in query.distinct().all()}, reverse=True)


@router.get("/duixiang-options")
def get_duixiang_options(
    query: str = "",
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("contract:view")),
):
    q = db.query(HtAdd.duixiang).filter(HtAdd.duixiang.isnot(None), HtAdd.duixiang != "")
    if query.strip():
        q = q.filter(HtAdd.duixiang.like(f"%{query.strip()}%"))
    return [r[0] for r in q.distinct().order_by(HtAdd.duixiang).limit(30).all()]


# ==================== 合同登记:列表 / 导出 ====================
@router.get("")
def list_contracts(
    page: int = 1,
    size: int = 30,
    mohu: str = "",
    nd: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:view")),
):
    query = db.query(HtAdd)
    if not current.is_superuser:
        query = query.filter(_own_condition(current))
    query = _filter_contracts(query, mohu=mohu, nd=nd)
    total = query.count()
    rows = query.order_by(HtAdd.djdate.desc(), HtAdd.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": _attach_related(db, rows)}


@router.get("/export")
def export_contracts(
    mohu: str = "",
    nd: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:view")),
):
    query = db.query(HtAdd)
    if not current.is_superuser:
        query = query.filter(_own_condition(current))
    query = _filter_contracts(query, mohu=mohu, nd=nd)
    rows = _attach_related(db, query.order_by(HtAdd.djdate.desc(), HtAdd.id.desc()).all())
    bm = current.departments[0].name if current.departments else "全部"
    return build_excel(rows, f"{bm}合同明细表", f"{bm}合同明细表({datetime.now():%Y%m%d%H%M%S}).xlsx")


# ==================== 合同归集:列表 / 下拉 / 导出 ====================
@router.get("/collect")
def list_collect(
    page: int = 1,
    size: int = 15,
    mohu: str = "",
    nd: str = "",
    tjr: str = "",
    jinedayu: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    scope = _collect_scope(db, current)
    query = db.query(HtAdd)
    if scope is not None:
        query = query.filter(HtAdd.bumenid.in_(scope))
    query = _filter_contracts(query, mohu=mohu, nd=nd, tjr=tjr, jinedayu=jinedayu)
    total = query.count()
    rows = query.order_by(HtAdd.djdate.desc(), HtAdd.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": _attach_related(db, rows)}


@router.get("/collect/years")
def collect_years(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    scope = _collect_scope(db, current)
    query = db.query(HtAdd.niandu).filter(HtAdd.niandu.isnot(None))
    if scope is not None:
        query = query.filter(HtAdd.bumenid.in_(scope))
    return sorted({r[0] for r in query.distinct().all()}, reverse=True)


@router.get("/collect/submitters")
def collect_submitters(
    nd: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    scope = _collect_scope(db, current)
    query = db.query(HtAdd.djuser_name).filter(HtAdd.djuser_name.isnot(None), HtAdd.djuser_name != "")
    if scope is not None:
        query = query.filter(HtAdd.bumenid.in_(scope))
    if nd.strip():
        years = [int(x) for x in nd.split(",") if x.strip().isdigit()]
        if years:
            query = query.filter(HtAdd.niandu.in_(years))
    names = sorted({r[0] for r in query.distinct().all()})
    return [{"value": n, "text": n} for n in names]


@router.get("/collect/export")
def export_collect(
    mohu: str = "",
    nd: str = "",
    tjr: str = "",
    jinedayu: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    scope = _collect_scope(db, current)
    query = db.query(HtAdd)
    if scope is not None:
        query = query.filter(HtAdd.bumenid.in_(scope))
    query = _filter_contracts(query, mohu=mohu, nd=nd, tjr=tjr, jinedayu=jinedayu)
    rows = _attach_related(db, query.order_by(HtAdd.djdate.desc(), HtAdd.id.desc()).all())
    bm = current.departments[0].name if current.departments else "全部"
    return build_excel(rows, f"{bm}合同归集移交明细", f"{bm}合同明细表({datetime.now():%Y%m%d%H%M%S}).xlsx")


@router.get("/file")
def download_attachment(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少附件令牌")
    try:
        payload = decode_short_token(token, "contract_file")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="附件令牌无效或已过期")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="签发账号不可用")
    item = db.get(HtTp, int(payload.get("aid", 0)))
    if item is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    path = _file_path(item.url)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件文件缺失(需从旧系统服务器拷贝 Upload 目录)")
    filename = item.oldname or path.name
    headers = {"Content-Disposition": f"inline; filename=\"attachment.pdf\"; filename*=UTF-8''{quote(filename)}"}
    return FileResponse(path, media_type="application/pdf", headers=headers)


# ==================== 合同登记:新增 / 详情 / 编辑 / 删除 / 锁定 ====================
@router.post("")
def create_contract(
    data: ContractIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    _ensure_required(data)
    dept = _department_for_create(db, current, data.bumenid)
    bh = (
        db.query(func.max(HtAdd.bh))
        .filter(HtAdd.niandu == data.niandu, HtAdd.bumenid == dept.id)
        .scalar()
        or 0
    ) + 1
    row = HtAdd(
        niandu=data.niandu,
        bh=bh,
        allbh=f"{dept.htdaihao or 'HT'}{data.niandu}{bh:03d}",
        bumenid=dept.id,
        djdate=datetime.now(),
        editdate=datetime.now(),
        djuser=current.id,
        djuser_name=_display(current),
        zt="待归集",
    )
    _apply_common(row, data)
    _apply_zb(row, data)
    db.add(row)
    db.flush()
    if data.suppliers:
        _apply_supplier(row, data.suppliers, db)
    db.commit()
    db.refresh(row)
    return contract_dict(row, dept_name_map(db))


@router.get("/{row_id}")
def get_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_any_permission("contract:view", "contract:collect", "contract:manage")),
):
    row = _get_row(db, row_id)
    if not _can_view_contract(db, current, row):
        raise HTTPException(status_code=403, detail="没有查看该合同的权限")
    names = dept_name_map(db)
    tps, suppliers = load_related(db, [row.id]).get(row.id, ([], []))
    return contract_dict(row, names, tps, suppliers)


@router.put("/{row_id}")
def update_contract(
    row_id: int,
    data: ContractIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    row = _get_row(db, row_id)
    _ensure_can_edit(db, current, row)
    try:
        check_text_len(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if row.zt == "已归集":
        # 照旧 Editgz:已归集后只允许改履行情况/签订时间/终止时间,招标信息不受限
        row.lvxingqingkuang = _trim(data.lvxingqingkuang)
        row.qddate = data.qddate
        row.zzdate = data.zzdate
    else:
        _ensure_required(data)
        _apply_common(row, data)
    _apply_zb(row, data)
    if data.suppliers is not None:
        _apply_supplier(row, data.suppliers, db)
    row.editdate = datetime.now()
    db.commit()
    db.refresh(row)
    names = dept_name_map(db)
    tps, suppliers = load_related(db, [row.id]).get(row.id, ([], []))
    return contract_dict(row, names, tps, suppliers)


@router.delete("/{row_id}")
def delete_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    row = _get_row(db, row_id)
    _ensure_can_edit(db, current, row)
    if row.zt != "待归集":
        raise HTTPException(status_code=400, detail="已归集或者已锁定,无法删除")
    for a in db.query(HtTp).filter(HtTp.htid == row.id).all():
        path = _file_path(a.url)
        if path.exists():
            path.unlink()
        db.delete(a)
    db.query(HtZbSupplier).filter(HtZbSupplier.htid == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.post("/{row_id}/lock")
def lock_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    row = _get_row(db, row_id)
    _ensure_can_edit(db, current, row)
    if row.zt != "已归集":
        raise HTTPException(status_code=400, detail="非已归集的合同,无法锁定")
    row.locked = row.id
    db.commit()
    return {"message": "锁定成功", "locked": row.locked}


@router.post("/{row_id}/unlock")
def unlock_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    row = _get_row(db, row_id)
    _ensure_can_edit(db, current, row)
    if row.zt != "已归集" or row.locked is None:
        raise HTTPException(status_code=400, detail="当前合同不是已锁定的已归集合同")
    row.locked = None
    db.commit()
    return {"message": "解锁成功", "locked": None}


# ==================== 合同归集:归集 / 取消归集 / 备注 ====================
@router.post("/{row_id}/collect")
def collect_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    row = _get_row(db, row_id)
    scope = _collect_scope(db, current)
    if scope is not None and row.bumenid not in scope:
        raise HTTPException(status_code=403, detail="只能操作本部门(含子部门)的合同")
    if row.locked is not None:
        raise HTTPException(status_code=400, detail="合同已锁定,无法操作")
    row.zt = "已归集"
    row.spdate = datetime.now()
    row.spuserid = current.id
    row.spuserid_name = _display(current)
    db.commit()
    return {"message": "归集成功"}


@router.post("/{row_id}/uncollect")
def uncollect_contract(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    row = _get_row(db, row_id)
    scope = _collect_scope(db, current)
    if scope is not None and row.bumenid not in scope:
        raise HTTPException(status_code=403, detail="只能操作本部门(含子部门)的合同")
    if row.locked is not None:
        raise HTTPException(status_code=400, detail="合同已锁定,无法操作")
    row.zt = "待归集"
    row.spdate = None
    row.spuserid = None
    row.spuserid_name = ""
    db.commit()
    return {"message": "已取消归集"}


@router.put("/{row_id}/memo")
def update_memo(
    row_id: int,
    data: MemoIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:collect")),
):
    row = _get_row(db, row_id)
    scope = _collect_scope(db, current)
    if scope is not None and row.bumenid not in scope:
        raise HTTPException(status_code=403, detail="只能操作本部门(含子部门)的合同")
    # 照旧 htgj Editxz:新备注 + "==>操作人编辑"
    row.bz = f"{data.bz or ''}==>{_display(current)}编辑"
    row.editdate = datetime.now()
    db.commit()
    return {"message": "已修改记录", "bz": row.bz}


# ==================== 附件 ====================
def _file_path(url: str) -> Path:
    raw = (url or "").replace("\\", "/").lstrip("/")
    if raw.lower().startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="附件路径不合法")
    return path


@router.post("/{row_id}/attachments")
async def upload_attachments(
    row_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    row = _get_row(db, row_id)
    _ensure_can_edit(db, current, row)
    now = datetime.now()
    target = Path(settings.UPLOAD_DIR) / "htdjPDF" / str(now.year) / str(now.month) / str(now.day)
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail=f"只允许上传 PDF 文件:{f.filename}")
        content = await f.read()
        if len(content) > MAX_PDF_SIZE:
            raise HTTPException(status_code=400, detail=f"文件超过 50MB:{f.filename}")
        stored = f"{uuid.uuid4().hex}.pdf"
        (target / stored).write_bytes(content)
        url = f"/Upload/htdjPDF/{now.year}/{now.month}/{now.day}/{stored}"
        item = HtTp(url=url, htid=row.id, oldname=f.filename or stored, fsize=len(content))
        db.add(item)
        db.flush()
        saved.append({"id": item.id, "url": url, "oldname": item.oldname})
    db.commit()
    return {"items": saved}


@router.post("/attachments/{attachment_id}/token")
def create_attachment_token(
    attachment_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_any_permission("contract:view", "contract:collect", "contract:manage")),
):
    item = db.get(HtTp, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    row = db.get(HtAdd, item.htid) if item.htid else None
    if row is None or not _can_view_contract(db, current, row):
        raise HTTPException(status_code=403, detail="没有查看该附件的权限")
    token = create_short_token(
        "contract_file", {"aid": item.id, "sub": str(current.id)}, minutes=FILE_TOKEN_MINUTES
    )
    return {
        "token": token,
        "url": f"/api/contracts/file?token={token}",
        "filename": item.oldname or "附件.pdf",
        "expires_minutes": FILE_TOKEN_MINUTES,
    }


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("contract:manage")),
):
    item = db.get(HtTp, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    row = db.get(HtAdd, item.htid) if item.htid else None
    if row is not None:
        _ensure_can_edit(db, current, row)
    path = _file_path(item.url)
    if path.exists():
        path.unlink()
    db.delete(item)
    db.commit()
    return {"message": "已删除"}
