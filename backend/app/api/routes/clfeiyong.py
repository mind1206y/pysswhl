"""车辆各类费用(照旧 CLfeiyongController 「车辆各类费用表」 1:1 复刻)。

- 列表:cl_feiyong 关联 cl_che,按年度/费用类别/关键字(车号或收费单位)筛选,
  部门取车辆 bmid 子树;筛选后全量金额合计(照旧 footer 「合计（元）：」)
- 字典:年度 / 费用类别 / 车辆下拉(排除油卡用途与已删除车辆) / 收费单位联想
- 增删改:登记人取当前登录人姓名,新增写登记日期,编辑刷最后操作日期、不改登记人
- 导出:当前筛选全量,照旧 9 列「车辆其他各项费用」模板

与出险/违章模块口径一致,权限沿用 vehicle:view(旧系统仅菜单控制访问)。
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import User
from app.models.vehicle import ClChe, ClFeiyong
from app.services.clfeiyong import (
    CATEGORIES, build_excel, build_rows, content_disposition, fee_query, total_amount,
)

router = APIRouter()


class FeiyongIn(BaseModel):
    cheid: Optional[int] = None
    lx: Optional[str] = None
    jine: Optional[float] = None
    bz: Optional[str] = None
    feiyongdate: Optional[date] = None
    dw: Optional[str] = None
    fangshi: Optional[str] = None
    jingshou: Optional[str] = None


# ==================== 公共辅助 ====================
def _get_or_404(db: Session, fee_id: int) -> ClFeiyong:
    row = db.get(ClFeiyong, fee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="费用记录不存在")
    return row


def _car_of(db: Session, row: ClFeiyong) -> Optional[ClChe]:
    return db.get(ClChe, row.cheid) if row.cheid else None


def _check_visible(db: Session, user: User, car: Optional[ClChe]):
    """旧系统靠车辆所属部门的 cj 层级码限制查看,新系统用 dept_scope_ids 子树。"""
    if car is None:
        raise HTTPException(status_code=404, detail="关联车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")


def _row_dict(db: Session, row: ClFeiyong, car: Optional[ClChe]) -> dict:
    return build_rows(db, [(row, car)])[0]


def _validate(data: FeiyongIn, db: Session, user: User) -> ClChe:
    if data.cheid is None:
        raise HTTPException(status_code=400, detail="请选择有效车号")
    if data.feiyongdate is None:
        raise HTTPException(status_code=400, detail="请选择费用日期")
    if data.jine is None:
        raise HTTPException(status_code=400, detail="请输入金额")
    if not (data.fangshi or "").strip():
        raise HTTPException(status_code=400, detail="请输入收费方式")
    if not (data.jingshou or "").strip():
        raise HTTPException(status_code=400, detail="请输入经手人")
    if (data.lx or "") not in CATEGORIES:
        raise HTTPException(status_code=400, detail="请选择费用类别")
    car = db.get(ClChe, data.cheid)
    _check_visible(db, user, car)
    return car


def _display_name(user: User) -> str:
    """旧 username 存的是中文姓名(张建平/戴杰),新系统优先取 real_name。"""
    return (user.real_name or "").strip() or user.username


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def list_feiyong(
    page: int = 1,
    size: int = 30,
    year: str = "",
    lx: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = fee_query(db, current, year=year, lx=lx, keyword=keyword)
    total = q.count()
    amount = total_amount(q)
    pairs = (
        q.order_by(ClFeiyong.feiyongdate.desc(), ClFeiyong.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"total": total, "sum": amount, "items": build_rows(db, pairs)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    rows = (
        db.query(func.year(ClFeiyong.feiyongdate))
        .filter(ClFeiyong.feiyongdate.isnot(None))
        .distinct().order_by(func.year(ClFeiyong.feiyongdate).desc()).all()
    )
    return {"years": [int(y) for (y,) in rows if y], "categories": CATEGORIES}


@router.get("/vehicles")
def vehicle_options(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    """照旧 Getch:排除油卡用途与 delf=0 已删除车辆,部门子树内。"""
    query = db.query(ClChe).filter(ClChe.yongtu != "油卡", ClChe.delf != 0)
    scope = dept_scope_ids(db, current)
    if scope is not None:
        query = query.filter(ClChe.bmid.in_(scope))
    kw = (q or "").strip()
    if kw:
        query = query.filter(ClChe.chehao.like(f"%{kw}%"))
    cars = query.order_by(ClChe.chehao).limit(300).all()
    return [{"id": c.id, "value": c.chehao or "", "chehao": c.chehao or ""} for c in cars]


@router.get("/units")
def unit_options(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    """照旧 Getzd:收费单位历史值联想,query 为空时返回空列表。"""
    kw = (q or "").strip()
    if not kw:
        return []
    rows = (
        db.query(ClFeiyong.dw)
        .filter(ClFeiyong.dw.like(f"%{kw}%"))
        .group_by(ClFeiyong.dw)
        .order_by(ClFeiyong.dw)
        .limit(20).all()
    )
    return [{"value": text} for (text,) in rows if text]


@router.get("/export")
def export_excel(
    year: str = "",
    lx: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = fee_query(db, current, year=year, lx=lx, keyword=keyword)
    pairs = q.order_by(ClFeiyong.feiyongdate.desc(), ClFeiyong.id.desc()).all()
    buf = build_excel(build_rows(db, pairs))
    filename = f"车辆其他费用清单（{datetime.now():%Y年%m月%d日}）.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


# ==================== 单条 / 增删改(动态路由放最后,避免吞静态路径) ====================
@router.get("/{fee_id}")
def get_feiyong(
    fee_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, fee_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    return _row_dict(db, row, car)


@router.post("")
def create_feiyong(
    data: FeiyongIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _validate(data, db, current)
    now = datetime.now()
    row = ClFeiyong(
        cheid=data.cheid,
        lx=data.lx,
        jine=data.jine,
        bz=(data.bz or "").strip(),
        username=_display_name(current),
        djdate=now,
        zuihoudate=now,
        feiyongdate=data.feiyongdate,
        dw=(data.dw or "").strip(),
        fangshi=(data.fangshi or "").strip(),
        jingshou=(data.jingshou or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.put("/{fee_id}")
def update_feiyong(
    fee_id: int,
    data: FeiyongIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, fee_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    new_car = _validate(data, db, current)

    # 旧 Editgz 漏了 jine(弹窗有金额框却不保存),新系统补齐;username/djdate 照旧不改
    for field in ("cheid", "lx", "jine", "feiyongdate"):
        setattr(row, field, getattr(data, field))
    for field in ("bz", "dw", "fangshi", "jingshou"):
        setattr(row, field, (getattr(data, field) or "").strip())
    row.zuihoudate = datetime.now()
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, new_car)


@router.delete("/{fee_id}")
def delete_feiyong(
    fee_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, fee_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
