"""车辆出险信息(照旧 ChuxianView 1:1 复刻)。

- 列表:主表 cl_chuxian 关联 cl_che,按年度多选/部门/关键字筛选,部门子树数据权限
- 增删改:记录人取当前登录人;删除仅限本人(超管除外)
- 图片:返回 cl_cxTP,前端用短令牌查看(复用 /api/vehicles/image)
- 导出:Excel 11 列(照旧 ExportExcel)
- 字典:责任/部门/年度/车辆检索(照旧 GetZrList/GetDeptList/GetYears/GetVehicles)
- 辅助:按车号+日期带出驾驶人/公里数(照旧 GetCarExtraInfo)

权限沿用 vehicle:view(模块入口 + 日常增删改/导出),与车辆模块口径一致。
"""

from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, ClChuxian, ClCxTP, Yongcherc
from app.services.chuxian import (
    accident_query, build_excel, build_rows, car_counts, content_disposition,
)
from app.services.vehicle_common import ZEREN_OPTIONS

router = APIRouter()
IMAGE_TOKEN_MINUTES = 30


class AccidentIn(BaseModel):
    cheid: Optional[int] = None
    riqi: Optional[date] = None
    zeren: Optional[str] = None
    jiashiyuan: Optional[str] = None
    jine: Optional[float] = None
    miaoshu: Optional[str] = None
    dizhi: Optional[str] = None
    gongli: Optional[int] = None


# ==================== 公共辅助 ====================
def _get_accident_or_404(db: Session, acc_id: int) -> ClChuxian:
    row = db.get(ClChuxian, acc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="出险记录不存在")
    return row


def _car_of(db: Session, row: ClChuxian) -> Optional[ClChe]:
    return db.get(ClChe, row.cheid) if row.cheid else None


def _check_visible(db: Session, user: User, car: Optional[ClChe]):
    if car is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")


def _image_path(url: str) -> Path:
    raw = (url or "").replace("\\", "/").lstrip("/")
    if raw.lower().startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="图片路径不合法")
    return path


def _dept_name(db: Session, car: Optional[ClChe]) -> str:
    if car is None:
        return ""
    return dept_name_map(db).get(car.bmid) or car.bm or ""


def _row_dict(db: Session, row: ClChuxian, car: Optional[ClChe]) -> dict:
    d = row.to_dict()
    d["chehao"] = car.chehao if car else ""
    d["bumen"] = _dept_name(db, car) or row.bm or ""
    d["tps"] = [t.to_dict() for t in db.query(ClCxTP).filter(ClCxTP.cxid == row.id).all()]
    return d


def _year_list(db: Session) -> list:
    """出险记录里出现过的年度(倒序)。表数据量小,用 DISTINCT 日期在 Python 里算年度,兼容 SQLite。"""
    dates = db.query(ClChuxian.riqi).filter(ClChuxian.riqi.isnot(None)).distinct().all()
    return sorted({d.year for (d,) in dates if d is not None}, reverse=True)


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def list_accidents(
    page: int = 1,
    size: int = 30,
    years: str = "",
    dept: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = accident_query(db, current, years=years, dept=dept, keyword=keyword)
    total = q.count()
    counts = car_counts(q)
    pairs = (
        q.order_by(ClChuxian.riqi.desc(), ClChe.bmid.desc(), ClChuxian.id.desc())
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
    return {"departments": departments, "zeren": ZEREN_OPTIONS, "years": _year_list(db)}


@router.get("/years")
def years(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    return [{"value": y, "text": y} for y in _year_list(db)]


@router.get("/vehicles")
def vehicle_options(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    query = db.query(ClChe).filter(ClChe.delf != 0, ClChe.yongtu != "油卡")
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


@router.get("/car-extra")
def car_extra(
    cheId: int,
    riqi: date,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = db.get(ClChe, cheId)
    _check_visible(db, current, car)
    last = (
        db.query(Yongcherc.jsgl)
        .filter(Yongcherc.cheid == cheId,
                Yongcherc.jsdate <= datetime.combine(riqi, dtime.min))
        .order_by(Yongcherc.jsdate.desc())
        .first()
    )
    return {"jiashiyuan": car.jiashiyuan or "", "gongli": last[0] if last else None}


@router.get("/export")
def export_excel(
    years: str = "",
    dept: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = accident_query(db, current, years=years, dept=dept, keyword=keyword)
    counts = car_counts(q)
    pairs = q.order_by(
        ClChuxian.riqi.desc(), ClChe.bmid.desc(), ClChuxian.id.desc()
    ).all()
    buf = build_excel(build_rows(db, pairs, counts))
    filename = f"出险记录_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post("/images/{image_id}/token")
def create_image_token(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = db.get(ClCxTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    acc = db.get(ClChuxian, row.cxid) if row.cxid else None
    if acc is not None:
        _check_visible(db, current, _car_of(db, acc))
    token = create_short_token(
        "vehicle_image",
        {"iid": image_id, "k": "accident", "sub": str(current.id)},
        minutes=IMAGE_TOKEN_MINUTES,
    )
    return {"token": token, "url": f"/api/vehicles/image?token={token}",
            "expires_minutes": IMAGE_TOKEN_MINUTES}


# ==================== 单条 / 增删改(动态路由放最后) ====================
@router.get("/{acc_id}")
def get_accident(
    acc_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_accident_or_404(db, acc_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    return _row_dict(db, row, car)


@router.post("")
def create_accident(
    data: AccidentIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    if data.cheid is None:
        raise HTTPException(status_code=400, detail="请选择车辆")
    if data.riqi is None:
        raise HTTPException(status_code=400, detail="出险日期不能为空")
    car = db.get(ClChe, data.cheid)
    _check_visible(db, current, car)
    row = ClChuxian(
        cheid=data.cheid,
        riqi=data.riqi,
        bm=_dept_name(db, car),
        zeren=(data.zeren or "").strip(),
        jiashiyuan=(data.jiashiyuan or "").strip(),
        jine=data.jine,
        miaoshu=(data.miaoshu or "").strip(),
        dizhi=(data.dizhi or "").strip(),
        gongli=data.gongli,
        caozuo=current.username,
        zuihou=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.put("/{acc_id}")
def update_accident(
    acc_id: int,
    data: AccidentIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_accident_or_404(db, acc_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)

    if "cheid" in data.model_fields_set and data.cheid is not None and data.cheid != row.cheid:
        new_car = db.get(ClChe, data.cheid)
        _check_visible(db, current, new_car)
        row.cheid = data.cheid
        car = new_car
    if "riqi" in data.model_fields_set:
        if data.riqi is None:
            raise HTTPException(status_code=400, detail="出险日期不能为空")
        row.riqi = data.riqi
    for f in ("zeren", "jiashiyuan", "miaoshu", "dizhi"):
        if f in data.model_fields_set:
            setattr(row, f, (getattr(data, f) or "").strip())
    for f in ("jine", "gongli"):
        if f in data.model_fields_set:
            setattr(row, f, getattr(data, f))

    row.bm = _dept_name(db, car) or row.bm
    row.caozuo = current.username
    row.zuihou = datetime.now()
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.delete("/{acc_id}")
def delete_accident(
    acc_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_accident_or_404(db, acc_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    if not current.is_superuser and (row.caozuo or "") != current.username:
        raise HTTPException(status_code=403, detail="只能删除自己录入的记录")
    for tp in db.query(ClCxTP).filter(ClCxTP.cxid == acc_id).all():
        try:
            path = _image_path(tp.url)
            if path.exists():
                path.unlink()
        except HTTPException:
            pass
        db.delete(tp)
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
