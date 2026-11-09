"""稽查奖励(照旧 JcJlController 1:1 复刻)。

- 月度奖励汇总表(jcjiangli):nd/yue 区间 + 部门过滤;附 wfp(未分配金额)、
  num(已分配人数);Operation:售水总(bmid=旧1 -> 新7)或已分完的行不给分配按钮
- 分配明细(jcjiangliFp):fenpeije/getfps/deletefp;Getzd 人员下拉(本人分配过
  的姓名去重,剔除该条已分配的);jssy 剩余额度

权限:jcjl:view 模块入口 + 分配/删除。
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.jcxt import Jcjiangli, JcjiangliFp
from app.models.user import Department, User
from app.services.jcxt_common import BM_TOTAL

router = APIRouter()


class FpIn(BaseModel):
    jlid: int
    fpname: str
    fpjine: Decimal


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


@router.get("")
def list_jcjl(
    page: int = 1,
    size: int = 30,
    rq: str = "",
    rqend: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    """照旧 jcjlService.LoadSearchEntities:nd/yue 与起止日期的年月比对。"""
    q = db.query(Jcjiangli)

    def _ym(v):
        try:
            return int(v[:4]), int(v[5:7])
        except (ValueError, TypeError, IndexError):
            return None

    if rq:
        ym = _ym(rq) or (datetime.now().year, 1)
        y, m = ym
        q = q.filter(Jcjiangli.nd >= y, Jcjiangli.yue >= m)
    if rqend:
        ym = _ym(rqend)
        if ym:
            y, m = ym
            q = q.filter(Jcjiangli.nd <= y, Jcjiangli.yue <= m)
    ids = _dept_filter(db, current, bmid)
    if ids is not None:
        q = q.filter(Jcjiangli.bmid.in_(ids))

    total = q.count()
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = (
        q.order_by(Jcjiangli.nd.desc(), Jcjiangli.yue.desc(), Jcjiangli.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    items = []
    for r in rows:
        fp_rows = db.query(JcjiangliFp).filter(JcjiangliFp.jlid == r.id).all()
        fp_sum = sum((f.fpjine or Decimal("0") for f in fp_rows), Decimal("0"))
        jiangli = r.jianglijine or Decimal("0")
        items.append({
            "ID": r.id,
            "bm": dept_names.get(r.bmid, ""),
            "zjshuifei": float(r.zjshuifei) if r.zjshuifei is not None else None,
            "jbjiangli": float(r.jbjiangli) if r.jbjiangli is not None else None,
            "zjbutie": float(r.zjbutie) if r.zjbutie is not None else None,
            "zjbutie_int": r.zjbutie_int,
            "jianglijine": float(jiangli),
            "usname": r.usname or "",
            "utime": r.utime.strftime("%Y-%m-%d %H:%M:%S") if r.utime else None,
            "nd": r.nd,
            "yue": r.yue,
            "wfp": float(jiangli - fp_sum),
            "num": len(fp_rows),
            # 照旧:售水总(新7)或已分完的行 Operation=0 -> 不显示分配按钮
            "operation": 0 if (r.bmid == BM_TOTAL or fp_sum >= jiangli) else r.id,
        })
    return {"total": total, "items": items}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    return {
        "departments": departments,
        "perms": {"view": True},
    }


@router.get("/names/{row_id}")
def get_names(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    """照旧 Getzd:本人分配过的姓名去重,剔除该条奖励已分配过的。"""
    mine = (
        db.query(JcjiangliFp.fpname)
        .filter(JcjiangliFp.uname == current.username)
        .distinct()
        .all()
    )
    exist = {
        f.fpname for f in db.query(JcjiangliFp)
        .filter(JcjiangliFp.jlid == row_id).all()
    }
    seen = set()
    out = []
    for (name,) in mine:
        if not name or name in exist or name in seen:
            continue
        seen.add(name)
        out.append({"fpname": name})
    return out


@router.get("/remain/{row_id}")
def remain(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    """照旧 jssy:剩余额度 = jianglijine - SUM(fpjine),整数返回。"""
    fp_sum = db.query(JcjiangliFp).filter(JcjiangliFp.jlid == row_id).all()
    s = db.get(Jcjiangli, row_id)
    if s is None:
        return {"remain": 0}
    n = int((s.jianglijine or Decimal("0"))) - \
        int(sum((f.fpjine or Decimal("0") for f in fp_sum), Decimal("0")))
    return {"remain": n}


@router.post("/assign")
def assign(
    data: FpIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    row = db.get(Jcjiangli, data.jlid)
    if row is None:
        raise HTTPException(status_code=404, detail="奖励记录不存在")
    db.add(JcjiangliFp(
        jlid=data.jlid, fpname=data.fpname, fpjine=data.fpjine,
        bmid=row.bmid, uname=current.username, utime=datetime.now(),
    ))
    db.commit()
    return {"ok": True}


@router.get("/{row_id}/fps")
def list_fps(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    rows = (
        db.query(JcjiangliFp)
        .filter(JcjiangliFp.jlid == row_id)
        .order_by(JcjiangliFp.id.desc())
        .all()
    )
    return {"total": len(rows), "items": [{
        "id": f.id,
        "fpname": f.fpname or "",
        "fpjine": float(f.fpjine) if f.fpjine is not None else None,
        "uname": f.uname or "",
        "utime": f.utime.strftime("%Y-%m-%d %H:%M:%S") if f.utime else None,
        "operation": f.id,
    } for f in rows]}


@router.delete("/fps/{fp_id}")
def delete_fp(
    fp_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcjl:view")),
):
    row = db.get(JcjiangliFp, fp_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no")
    db.delete(row)
    db.commit()
    return {"ok": True}
