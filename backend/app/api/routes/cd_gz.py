"""传导故障明细(照旧 CDguzhangController 1:1 复刻)。

- 列表:报表日期(每月25日) + 部门子树 + 部门下拉 + 关键字(设备名称/地点/原因)
- 增删改:锁定时禁止;编辑/删除限本人录入;删除限本月数据
- ShowEditInfo 对应 GET /{id}(旧接口带锁定检查)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.cd import CDGz
from app.models.user import User
from app.services.cd_common import (
    bt_title, default_bmid, dept_names, display_name, ensure_current_month,
    ensure_not_locked, ensure_owner, gz_row, parse_date, report_date, scoped_query,
)

router = APIRouter()


class GzIn(BaseModel):
    bbdate: Optional[str] = None
    sbname: Optional[str] = None
    guancai: Optional[str] = None
    guanjing: Optional[str] = None
    didian: Optional[str] = None
    ksdate: Optional[str] = None
    jsdate: Optional[str] = None
    yy: Optional[str] = None
    dects: Optional[float] = None
    bz: Optional[str] = None


def _get_or_404(db: Session, rid: int) -> CDGz:
    row = db.get(CDGz, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="故障记录不存在")
    return row


def _validate(data: GzIn):
    if not (data.sbname or "").strip():
        raise HTTPException(status_code=400, detail="请输入设备名称")
    if not (data.didian or "").strip():
        raise HTTPException(status_code=400, detail="请输入故障地点")
    ks, js = parse_date(data.ksdate), parse_date(data.jsdate)
    if ks is None or js is None:
        raise HTTPException(status_code=400, detail="请选择故障起止日期")
    if js < ks:
        raise HTTPException(status_code=400, detail="结束日期应大于等于开始日期")
    if data.dects is not None and float(data.dects) < 0:
        raise HTTPException(status_code=400, detail="故障时数不能为负数")
    return ks, js


def _apply(row: CDGz, data: GzIn, ks, js):
    row.bbdate = parse_date(data.bbdate) or report_date()
    row.sbname = (data.sbname or "").strip()
    row.guancai = data.guancai or ""
    row.guanjing = data.guanjing or ""
    row.didian = (data.didian or "").strip()
    row.ksdate, row.jsdate = ks, js
    row.yy = data.yy or ""
    row.dects = data.dects
    row.bz = data.bz or ""


@router.get("")
def list_gz(
    page: int = 1, size: int = 30, rq: str = "", bmid: str = "", keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdgz:view")),
):
    q = scoped_query(db, current, CDGz, rq, bmid, keyword,
                     (CDGz.sbname, CDGz.didian, CDGz.yy))
    total = q.count()
    rows = (
        q.order_by(CDGz.id.desc())
        .offset((max(page, 1) - 1) * size).limit(size).all()
    )
    names = dept_names(db)
    return {"items": [gz_row(r, names) for r in rows], "total": total, "bt": bt_title(rq)}


@router.post("")
def add_gz(
    data: GzIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdgz:view")),
):
    ensure_not_locked(db)
    ks, js = _validate(data)
    now = datetime.now()
    row = CDGz(
        bmid=default_bmid(current), username=display_name(current),
        adddate=now, finadate=now,
    )
    _apply(row, data, ks, js)
    db.add(row)
    db.commit()
    db.refresh(row)
    return gz_row(row, dept_names(db))


@router.put("/{rid}")
def update_gz(
    rid: int, data: GzIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdgz:view")),
):
    ensure_not_locked(db)
    row = _get_or_404(db, rid)
    ensure_owner(row, current, "修改")
    ks, js = _validate(data)
    _apply(row, data, ks, js)
    row.finadate = datetime.now()
    db.commit()
    db.refresh(row)
    return gz_row(row, dept_names(db))


@router.delete("/{rid}")
def delete_gz(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdgz:view")),
):
    ensure_not_locked(db)
    row = _get_or_404(db, rid)
    ensure_current_month(row, "不能删除往期数据")
    ensure_owner(row, current, "删除")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.get("/{rid}")
def get_gz(
    rid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("cdgz:view")),
):
    ensure_not_locked(db)
    return gz_row(_get_or_404(db, rid), dept_names(db))
