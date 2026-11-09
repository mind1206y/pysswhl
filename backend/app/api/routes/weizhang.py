"""车辆违章信息(照旧 ClweizhangController 1:1 复刻)。

- 列表:clweizhang 关联 cl_che,按年度多选/部门/关键字筛选,部门子树数据权限
- 增删改:登记人取当前登录人;编辑时更新登记人;删除仅限本人(超管除外)
- 字典:年度/部门/车辆检索/历史违章内容/最近一次扣分罚款/驾驶员
- 导出:Excel 11 列(照旧 ExportExcel)

权限沿用 vehicle:view(模块入口 + 日常增删改/导出),与车辆/出险模块口径一致。
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, ClWeizhang
from app.services.weizhang import (
    build_excel, build_rows, car_counts, content_disposition, weizhang_query,
)

router = APIRouter()


class WeizhangIn(BaseModel):
    cheid: Optional[int] = None
    wzriqi: Optional[date] = None
    lu: Optional[str] = None
    jine: Optional[float] = None
    fen: Optional[int] = None
    xingming: Optional[str] = None
    wz: Optional[str] = None
    gongli: Optional[int] = None


# ==================== 公共辅助 ====================
def _get_or_404(db: Session, wz_id: int) -> ClWeizhang:
    row = db.get(ClWeizhang, wz_id)
    if row is None:
        raise HTTPException(status_code=404, detail="违章记录不存在")
    return row


def _car_of(db: Session, row: ClWeizhang) -> Optional[ClChe]:
    return db.get(ClChe, row.cheid) if row.cheid else None


def _check_visible(db: Session, user: User, car: Optional[ClChe]):
    if car is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")


def _row_dict(db: Session, row: ClWeizhang, car: Optional[ClChe]) -> dict:
    d = row.to_dict()
    d["chehao"] = car.chehao if car else ""
    dept_name = (dept_name_map(db).get(car.bmid) if car and car.bmid else "") or ""
    d["bumen"] = dept_name or (car.bm if car else "") or ""
    return d


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def list_weizhang(
    page: int = 1,
    size: int = 30,
    years: str = "",
    dept: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = weizhang_query(db, current, years=years, dept=dept, keyword=keyword)
    total = q.count()
    counts = car_counts(q)
    pairs = (
        q.order_by(ClWeizhang.wzriqi.desc(), ClChe.bmid.desc(), ClWeizhang.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"total": total, "items": build_rows(db, pairs, counts)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    years = [int(y) for (y,) in (
        db.query(func.year(ClWeizhang.wzriqi))
        .filter(ClWeizhang.wzriqi.isnot(None))
        .distinct().order_by(func.year(ClWeizhang.wzriqi).desc()).all()
    )]
    return {"departments": departments, "years": years}


@router.get("/years")
def years(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    rows = (
        db.query(func.year(ClWeizhang.wzriqi))
        .filter(ClWeizhang.wzriqi.isnot(None))
        .distinct().order_by(func.year(ClWeizhang.wzriqi).desc()).all()
    )
    return [{"value": int(y), "text": int(y)} for (y,) in rows]


@router.get("/vehicles")
def vehicle_options(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    query = db.query(ClChe).filter(ClChe.delf == 1, ClChe.yongtu != "油卡")
    scope = dept_scope_ids(db, current)
    if scope is not None:
        query = query.filter(ClChe.bmid.in_(scope))
    kw = (q or "").strip()
    if kw:
        query = query.filter(ClChe.chehao.like(f"%{kw}%"))
    cars = query.order_by(ClChe.chehao).limit(20).all()
    return [
        {"id": c.id, "text": c.chehao or "", "chehao": c.chehao or "",
         "jiashiyuan": c.jiashiyuan or ""}
        for c in cars
    ]


@router.get("/wz-contents")
def wz_contents(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    kw = (q or "").strip()
    if not kw:
        return []
    rows = (
        db.query(ClWeizhang.wz)
        .filter(ClWeizhang.wz.like(f"%{kw}%"))
        .group_by(ClWeizhang.wz)
        .order_by(ClWeizhang.wz)
        .limit(20).all()
    )
    return [{"text": text} for (text,) in rows if text]


@router.get("/latest-wz")
def latest_wz(
    wz: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    if not (wz or "").strip():
        return {"fen": 0, "jine": 0}
    latest = (
        db.query(ClWeizhang)
        .filter(ClWeizhang.wz == wz)
        .order_by(ClWeizhang.wzriqi.desc())
        .first()
    )
    if latest is None:
        return {"fen": 0, "jine": 0}
    return {"fen": latest.fen or 0,
            "jine": float(latest.jine) if latest.jine is not None else 0}


@router.get("/driver")
def driver(
    chehao: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    number = (chehao or "").strip()
    if not number:
        return None
    car = db.query(ClChe).filter(ClChe.chehao == number).first()
    if car is None:
        return None
    return {"jiashiyuan": car.jiashiyuan or ""}


@router.get("/export")
def export_excel(
    years: str = "",
    dept: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = weizhang_query(db, current, years=years, dept=dept, keyword=keyword)
    counts = car_counts(q)
    pairs = q.order_by(
        ClWeizhang.wzriqi.desc(), ClChe.bmid.desc(), ClWeizhang.id.desc()
    ).all()
    buf = build_excel(build_rows(db, pairs, counts))
    filename = f"违章记录_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


# ==================== 单条 / 增删改(动态路由放最后) ====================
@router.get("/{wz_id}")
def get_weizhang(
    wz_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, wz_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    return _row_dict(db, row, car)


@router.post("")
def create_weizhang(
    data: WeizhangIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    if data.cheid is None:
        raise HTTPException(status_code=400, detail="请选择车辆")
    if data.wzriqi is None:
        raise HTTPException(status_code=400, detail="违章日期不能为空")
    car = db.get(ClChe, data.cheid)
    _check_visible(db, current, car)
    now = datetime.now()
    row = ClWeizhang(
        cheid=data.cheid,
        wzriqi=data.wzriqi,
        lu=(data.lu or "").strip(),
        jine=data.jine,
        fen=data.fen,
        xingming=(data.xingming or "").strip(),
        wz=(data.wz or "").strip(),
        dj=current.username,
        djriqi=now,
        zhriqi=now,
        gongli=data.gongli,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.put("/{wz_id}")
def update_weizhang(
    wz_id: int,
    data: WeizhangIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, wz_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)

    if "cheid" in data.model_fields_set and data.cheid is not None and data.cheid != row.cheid:
        new_car = db.get(ClChe, data.cheid)
        _check_visible(db, current, new_car)
        row.cheid = data.cheid
        car = new_car
    if "wzriqi" in data.model_fields_set:
        if data.wzriqi is None:
            raise HTTPException(status_code=400, detail="违章日期不能为空")
        row.wzriqi = data.wzriqi
    for f in ("lu", "xingming", "wz"):
        if f in data.model_fields_set:
            setattr(row, f, (getattr(data, f) or "").strip())
    for f in ("jine", "fen", "gongli"):
        if f in data.model_fields_set:
            setattr(row, f, getattr(data, f))

    row.dj = current.username
    row.zhriqi = datetime.now()
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.delete("/{wz_id}")
def delete_weizhang(
    wz_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_or_404(db, wz_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    if not current.is_superuser and (row.dj or "") != current.username:
        raise HTTPException(status_code=403, detail="只能删除自己录入的记录")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
