"""稽查单(照旧 jcdanController 1:1 复刻)。

- 列表:发生时间区间 + 部门子树 + 模糊;colo 标记是否已关联稽查明细(行染绿)
- 添加/编辑:编号(bianhao)唯一;编辑/删除仅本人(超管例外);bmid 取登记人部门
- 子表格 getpz:jcdanid 关联的 jc_jcxx 明细
- getListForJcxx:稽查信息模块选稽查单用(未关联或已关联到当前记录)

权限:jcdan:view 模块入口 + 全部功能。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.jcxt import JcJcxx, Jcdan
from app.models.user import Department, User

router = APIRouter()


class JcdanIn(BaseModel):
    gongdanhao: Optional[str] = None
    weizhangdanwei: Optional[str] = None
    bianhao: Optional[str] = None
    jbren: Optional[str] = None
    fstime: Optional[str] = None
    didian: Optional[str] = None
    nr: Optional[str] = None
    wzren: Optional[str] = None
    bz: Optional[str] = None
    jbleibie: Optional[str] = None
    kpren: Optional[str] = None
    weizhangdianhua: Optional[str] = None
    usname: Optional[str] = None  # 编辑时透传(本人校验)


def _parse_dt(v):
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            continue
    return None


def _dept_filter(db: Session, user: User, bmid: Optional[int]) -> Optional[set]:
    scope = dept_scope_ids(db, user)
    if bmid:
        ids = {bmid}
        while True:
            children = (
                db.query(Department.id)
                .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids))
                .all()
            )
            if not children:
                break
            ids |= {c[0] for c in children}
        if scope is not None:
            ids &= scope
        return ids
    return scope


def _row(db, r: Jcdan, dept_names: dict) -> dict:
    linked = db.query(JcJcxx.id).filter(JcJcxx.jcdanid == r.id).count()
    return {
        **r.to_dict(),
        "bm": dept_names.get(r.bmid, ""),
        "colo": r.id if linked > 0 else "0",
    }


@router.get("")
def list_jcdan(
    page: int = 1,
    size: int = 30,
    rq: str = "",
    rqend: str = "",
    bmid: Optional[int] = None,
    sousou: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    q = db.query(Jcdan)
    if rq:
        d = _parse_dt(rq)
        if d:
            q = q.filter(Jcdan.fstime >= d)
    if rqend:
        d = _parse_dt(rqend)
        if d:
            q = q.filter(Jcdan.fstime <= d.replace(hour=23, minute=59, second=59))
    ids = _dept_filter(db, current, bmid)
    if ids is not None:
        q = q.filter(Jcdan.bmid.in_(ids))
    if sousou:
        like = f"%{sousou}%"
        q = q.filter(or_(
            Jcdan.bianhao.contains(sousou), Jcdan.gongdanhao.contains(sousou),
            Jcdan.didian.contains(sousou), Jcdan.nr.contains(sousou),
            Jcdan.wzren.contains(sousou), Jcdan.weizhangdanwei.contains(sousou),
            Jcdan.weizhangdianhua.contains(sousou), Jcdan.bz.contains(sousou),
            Jcdan.kpren.contains(sousou),
        ))
    total = q.count()
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = q.order_by(Jcdan.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [_row(db, r, dept_names) for r in rows]}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    return {
        "jbleibie": ["内部员工", "外协人员", "用户举报", "肇事举报",
                     "稽查人员", "其他"],
        "perms": {"view": True},
    }


@router.get("/for-jcxx")
def list_for_jcxx(
    page: int = 1,
    size: int = 10,
    jcxxdanid: int = 0,
    sousou: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    """稽查信息编辑弹窗里的「关联稽查单」列表(照旧 getListForJcxx)。"""
    q = db.query(Jcdan).filter(
        or_(Jcdan.jcxxid.is_(None), Jcdan.jcxxid == jcxxdanid))
    if sousou:
        like = f"%{sousou}%"
        q = q.filter(or_(
            Jcdan.bianhao.contains(sousou), Jcdan.gongdanhao.contains(sousou),
            Jcdan.didian.contains(sousou), Jcdan.nr.contains(sousou),
            Jcdan.wzren.contains(sousou), Jcdan.weizhangdanwei.contains(sousou),
            Jcdan.weizhangdianhua.contains(sousou), Jcdan.bz.contains(sousou),
            Jcdan.kpren.contains(sousou),
        ))
    total = q.count()
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = q.order_by(Jcdan.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [_row(db, r, dept_names) for r in rows]}


@router.get("/{row_id}/pz")
def get_pz(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    rows = db.query(JcJcxx).filter(JcJcxx.jcdanid == row_id).all()
    items = [{
        "id": r.id,
        "weizhangriqi": r.weizhangriqi.strftime("%Y-%m-%d") if r.weizhangriqi else None,
        "weizhangren": r.weizhangren or "",
        "weizhangdizhi": r.weizhangdizhi or "",
        "weizhangneirong": r.weizhangneirong or "",
        "weizhangdianhua": r.weizhangdianhua or "",
        "chuliriqi": r.chuliriqi.strftime("%Y-%m-%d") if r.chuliriqi else None,
        "zhuijiaoshuiliang": r.zhuijiaoshuiliang,
        "zhuijiaoshuifei": float(r.zhuijiaoshuifei) if r.zhuijiaoshuifei is not None else None,
        "zhuijiaogongliaofei": float(r.zhuijiaogongliaofei) if r.zhuijiaogongliaofei is not None else None,
    } for r in rows]
    return {"total": len(items), "items": items}


@router.post("")
def add_jcdan(
    data: JcdanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    bianhao = (data.bianhao or "").strip()
    if bianhao and db.query(Jcdan.id).filter(Jcdan.bianhao == bianhao).first():
        raise HTTPException(status_code=400, detail="已有该稽查单编号,无法添加")
    bmid = current.departments[0].id if current.departments else None
    row = Jcdan(
        gongdanhao=(data.gongdanhao or "").strip() or None,
        weizhangdanwei=data.weizhangdanwei,
        bianhao=bianhao or None,
        jbren=data.jbren,
        fstime=_parse_dt(data.fstime),
        didian=data.didian,
        nr=data.nr,
        wzren=data.wzren,
        bz=data.bz,
        jbleibie=data.jbleibie,
        kpren=data.kpren,
        weizhangdianhua=data.weizhangdianhua,
        addtime=datetime.now(),
        edtime=datetime.now(),
        usname=current.username,
        bmid=bmid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@router.put("/{row_id}")
def edit_jcdan(
    row_id: int,
    data: JcdanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    row = db.get(Jcdan, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    bianhao = (data.bianhao or "").strip()
    dup = db.query(Jcdan.id).filter(Jcdan.bianhao == bianhao, Jcdan.id != row_id).first()
    if bianhao and dup:
        raise HTTPException(status_code=400, detail="编号重复无法更新")
    owner = data.usname or row.usname
    if not current.is_superuser and (owner or "") != (current.username or ""):
        raise HTTPException(status_code=403, detail="非自己录入的信息无法更改")
    row.gongdanhao = (data.gongdanhao or "").strip() or None
    row.weizhangdanwei = data.weizhangdanwei
    row.bianhao = bianhao or None
    row.jbren = data.jbren
    row.fstime = _parse_dt(data.fstime)
    row.didian = data.didian
    row.nr = data.nr
    row.wzren = data.wzren
    row.bz = data.bz
    row.jbleibie = data.jbleibie
    row.kpren = data.kpren
    row.weizhangdianhua = data.weizhangdianhua
    row.edtime = datetime.now()
    db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/{row_id}")
def delete_jcdan(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcdan:view")),
):
    row = db.get(Jcdan, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no")
    if not current.is_superuser and (row.usname or "") != (current.username or ""):
        raise HTTPException(status_code=403, detail="不能删除非自己建的单")
    # 解除稽查信息上的关联
    for r in db.query(JcJcxx).filter(JcJcxx.jcdanid == row_id).all():
        r.jcdanid = None
    db.delete(row)
    db.commit()
    return {"ok": True}
