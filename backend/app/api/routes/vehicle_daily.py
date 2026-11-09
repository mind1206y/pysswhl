"""日常用车(照旧 yongcherichangController)。

- 列表/查询:部门子树、车号、司机、日期区间、关键字
- 新增/编辑/批量删除:沿用旧系统待审核/待审批、预登记、时段占用校验
- 图片:上传、短时效令牌直链、删除
- Excel:导出用车登记表、导出重叠里程、导出空挡里程、上传水务派车记录
- 异常里程:查找、清理
"""

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, Yongcherc, YongchercTP
from app.services.vehicle_daily import (
    build_rows, compute_gap_rows, compute_overlap_rows, daily_query,
    driver_counts, extract_year_mileage, find_abnormal_rows, latest_car_info,
    reason_options, scope_cars,
)
from app.services.vehicle_daily_excel import (
    build_daily_excel, build_gap_excel, build_overlap_excel, import_dispatch_excel,
)

router = APIRouter()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_EXCEL_SIZE = 50 * 1024 * 1024
IMAGE_TOKEN_MINUTES = 30


class DailyIn(BaseModel):
    cheid: int
    ksdate: datetime
    jsdate: Optional[datetime] = None
    ksgl: Optional[int] = None
    jsgl: Optional[int] = None
    yuanyin: str = ""
    didian: str = ""
    usercar: str = ""
    shenhe: str = ""
    shenpi: str = ""
    tingfang: str = ""
    sj: str = ""
    shenQingTime: Optional[datetime] = None


class IdsIn(BaseModel):
    ids: List[int]


# ==================== 公共辅助 ====================
def _record_or_404(db: Session, record_id: int) -> Yongcherc:
    rec = db.get(Yongcherc, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="用车记录不存在")
    return rec


def _check_car_scope(db: Session, user: User, car: Optional[ClChe]):
    if car is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")


def _record_car(db: Session, user: User, rec: Yongcherc) -> ClChe:
    car = db.get(ClChe, rec.cheid) if rec.cheid else None
    _check_car_scope(db, user, car)
    return car


def _check_image_editable(user: User, rec: Yongcherc):
    """图片上传/删除:管理员不限;普通用户只能维护自己待审核的记录(照旧编辑弹窗口径)。"""
    if user.is_superuser:
        return
    owned = {p.code for role in user.roles for p in role.permissions}
    if "vehicle:manage" in owned:
        return
    if ((rec.czy or "") == user.username and rec.shenheqz == "待审核"
            and rec.bumenld == "待审批"):
        return
    raise HTTPException(status_code=403, detail="该记录已审核或非本人录入，不能维护图片")


def _validate_record(rec: Yongcherc):
    if rec.ksdate is None:
        raise HTTPException(status_code=400, detail="用车开始日期不能为空")
    if rec.ksgl is not None and rec.jsgl is not None and rec.ksgl > rec.jsgl:
        raise HTTPException(status_code=400, detail="开始公里数大于结束公里数")
    if rec.jsdate is not None and rec.ksdate > rec.jsdate and (
        rec.jsdate.hour != 0 or rec.jsdate.minute != 0
    ):
        raise HTTPException(status_code=400, detail="开始时间大于结束时间")


def _check_overlap(db: Session, rec: Yongcherc):
    if rec.ksdate is None:
        return
    q = db.query(Yongcherc.id).filter(
        Yongcherc.cheid == rec.cheid,
        Yongcherc.ksdate <= rec.ksdate,
        Yongcherc.jsdate > rec.ksdate,
    )
    if rec.id:
        q = q.filter(Yongcherc.id != rec.id)
    if q.first():
        raise HTTPException(status_code=400, detail="该时段车已申请在用，添加/修改失败")


def _set_status(rec: Yongcherc):
    pre = (
        rec.jsgl is None
        or rec.jsdate is None
        or (rec.jsdate.hour == 0 and rec.jsdate.minute == 0)
    )
    rec.beizhu = "预登记" if pre else "已提交"


def _apply_fields(rec: Yongcherc, data: DailyIn, creating: bool = False):
    if creating:
        rec.ksdate = data.ksdate
        rec.jsdate = data.jsdate
        rec.ksgl = data.ksgl
        rec.jsgl = data.jsgl
        rec.yuanyin = (data.yuanyin or "").strip()
        rec.didian = (data.didian or "").strip()
        rec.usercar = (data.usercar or "").strip()
        rec.shenhe = (data.shenhe or "").strip()
        rec.shenpi = (data.shenpi or "").strip()
        rec.tingfang = (data.tingfang or "").strip()
        rec.sj = (data.sj or "").strip()
        rec.shenQingTime = data.shenQingTime
        return

    fields = (
        "ksdate", "jsdate", "ksgl", "jsgl", "shenQingTime",
    )
    for f in fields:
        if f in data.model_fields_set:
            setattr(rec, f, getattr(data, f))
    for f in ("yuanyin", "didian", "usercar", "shenhe", "shenpi", "tingfang", "sj"):
        if f in data.model_fields_set:
            setattr(rec, f, (getattr(data, f) or "").strip())


def _image_path(url: str) -> Path:
    raw = (url or "").replace("\\", "/").lstrip("/")
    if raw.lower().startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="图片路径不合法")
    return path


def _save_images(files: List[UploadFile], subdir: str) -> list:
    now = datetime.now()
    target = Path(settings.UPLOAD_DIR) / subdir / str(now.year) / str(now.month) / str(now.day)
    target.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in IMAGE_EXTS:
            raise HTTPException(status_code=400, detail=f"只允许上传图片，不支持 {ext or '无扩展名'}")
        content = f.file.read()
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"图片超过 10MB：{f.filename}")
        stored = f"{uuid.uuid4().hex}{ext}"
        (target / stored).write_bytes(content)
        url = f"/Upload/{subdir}/{now.year}/{now.month}/{now.day}/{stored}"
        saved.append(url)
    return saved


def _attachment(filename: str) -> str:
    return f'attachment; filename="export.xlsx"; filename*=UTF-8\'\'{quote(filename)}'


def _delete_images(db: Session, record_ids: List[int]):
    rows = db.query(YongchercTP).filter(YongchercTP.yongchercid.in_(record_ids)).all()
    for row in rows:
        try:
            path = _image_path(row.url)
            if path.exists():
                path.unlink()
        except HTTPException:
            pass
        db.delete(row)


def _filter_kwargs(
    keyword: str = "", dept_id: Optional[int] = None, car_id: Optional[int] = None,
    driver: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None,
    year: Optional[int] = None,
):
    return {
        "keyword": keyword, "dept_id": dept_id, "car_id": car_id,
        "driver": driver, "date_from": date_from, "date_to": date_to, "year": year,
    }


# ==================== 字典 / 司机 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    cars = scope_cars(db, current)
    names = dept_name_map(db)
    today = date.today()
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    return {
        "departments": [
            {"id": d.id, "name": d.name}
            for d in dq.order_by(Department.id).all()
        ],
        "cars": [
            {"id": c.id, "chehao": c.chehao, "lx": c.lx, "bmid": c.bmid,
             "bumen": names.get(c.bmid, "") or (c.bm or "")}
            for c in cars
        ],
        "drivers": driver_counts(db, current),
        "shiyou": reason_options(db, current),
        "years": list(range(today.year - 9, today.year + 2)),
        "current_year": today.year,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/drivers")
def drivers(
    keyword: str = "", dept_id: Optional[int] = None, car_id: Optional[int] = None,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    return driver_counts(
        db, current, **_filter_kwargs(
            keyword=keyword, dept_id=dept_id, car_id=car_id,
            date_from=date_from, date_to=date_to, year=year,
        )
    )


@router.get("/car-info/{car_id}")
def car_info(
    car_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = db.get(ClChe, car_id)
    _check_car_scope(db, current, car)
    return latest_car_info(db, car)


# ==================== 列表 / 详情 ====================
@router.get("")
def list_daily(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    dept_id: Optional[int] = None,
    car_id: Optional[int] = None,
    driver: str = "",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = daily_query(
        db, current, **_filter_kwargs(
            keyword=keyword, dept_id=dept_id, car_id=car_id, driver=driver,
            date_from=date_from, date_to=date_to, year=year,
        )
    )
    total = q.count()
    records = (
        q.order_by(Yongcherc.jsgl.is_(None), Yongcherc.jsgl.desc(), Yongcherc.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"total": total, "items": build_rows(db, records)}


# ==================== 新增 / 编辑 / 删除 ====================
@router.post("")
def create_daily(
    data: DailyIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = db.get(ClChe, data.cheid)
    if car is None or car.delf != 1:
        raise HTTPException(status_code=404, detail="车辆不存在或不可用")
    _check_car_scope(db, current, car)

    rec = Yongcherc(cheid=car.id)
    _apply_fields(rec, data, creating=True)
    rec.czy = current.username
    rec.cz = datetime.now()
    rec.shenQingTime = rec.shenQingTime or rec.cz
    if not rec.shenhe:
        rec.shenhe = car.shenheren or ""
    rec.shenheqz = "待审核"
    rec.bumenld = "待审批"
    _validate_record(rec)
    _check_overlap(db, rec)
    _set_status(rec)

    db.add(rec)
    db.commit()
    db.refresh(rec)
    return build_rows(db, [rec])[0]


@router.put("/{record_id}")
def update_daily(
    record_id: int,
    data: DailyIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    rec = _record_or_404(db, record_id)
    _record_car(db, current, rec)

    if not current.is_superuser and (rec.czy or "") != current.username:
        raise HTTPException(status_code=403, detail="不能编辑非自己录入的信息")
    if rec.shenheqz != "待审核" or rec.bumenld != "待审批":
        raise HTTPException(status_code=400, detail="该记录已审核，无法编辑")

    if data.cheid != rec.cheid:
        car = db.get(ClChe, data.cheid)
        if car is None or car.delf != 1:
            raise HTTPException(status_code=404, detail="车辆不存在或不可用")
        _check_car_scope(db, current, car)
        rec.cheid = data.cheid

    _apply_fields(rec, data, creating=False)
    _validate_record(rec)
    _check_overlap(db, rec)
    _set_status(rec)
    rec.cz = datetime.now()
    rec.shenheqz = "待审核"
    rec.bumenld = "待审批"

    db.commit()
    db.refresh(rec)
    return build_rows(db, [rec])[0]


@router.post("/bulk-delete")
def bulk_delete(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请选择要删除的记录")
    records = db.query(Yongcherc).filter(Yongcherc.id.in_(data.ids)).all()
    for rec in records:
        _record_car(db, current, rec)
    _delete_images(db, [r.id for r in records])
    for rec in records:
        db.delete(rec)
    db.commit()
    return {"deleted": len(records)}


@router.delete("/{record_id}")
def delete_daily(
    record_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    rec = _record_or_404(db, record_id)
    _record_car(db, current, rec)
    _delete_images(db, [rec.id])
    db.delete(rec)
    db.commit()
    return {"message": "已删除"}


# ==================== 图片 ====================
@router.post("/{record_id}/images")
def upload_images(
    record_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    rec = _record_or_404(db, record_id)
    _record_car(db, current, rec)
    _check_image_editable(current, rec)
    saved = []
    for url in _save_images(files, "yongchercimages"):
        row = YongchercTP(yongchercid=record_id, url=url)
        db.add(row)
        saved.append(row)
    db.commit()
    return [r.to_dict() for r in saved]


@router.post("/images/{image_id}/token")
def create_image_token(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = db.get(YongchercTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    rec = db.get(Yongcherc, row.yongchercid) if row.yongchercid else None
    if rec is not None:
        _record_car(db, current, rec)
    token = create_short_token(
        "vehicle_daily_image", {"iid": image_id, "sub": str(current.id)},
        minutes=IMAGE_TOKEN_MINUTES,
    )
    return {
        "token": token,
        "url": f"/api/vehicle-daily/image?token={token}",
        "expires_minutes": IMAGE_TOKEN_MINUTES,
    }


@router.get("/image")
def image_file(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "vehicle_daily_image")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="签发账号不可用")
    row = db.get(YongchercTP, int(payload.get("iid", 0)))
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _image_path(row.url)
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件缺失(需从旧系统服务器拷贝 Upload 目录)")
    return FileResponse(path)


@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = db.get(YongchercTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    rec = db.get(Yongcherc, row.yongchercid) if row.yongchercid else None
    if rec is not None:
        _record_car(db, current, rec)
        _check_image_editable(current, rec)
    try:
        path = _image_path(row.url)
        if path.exists():
            path.unlink()
    except HTTPException:
        pass
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


# ==================== 导出 / 导入 ====================
@router.get("/export")
def export_daily(
    keyword: str = "", dept_id: Optional[int] = None, car_id: Optional[int] = None,
    driver: str = "", date_from: Optional[date] = None, date_to: Optional[date] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = daily_query(
        db, current, **_filter_kwargs(
            keyword=keyword, dept_id=dept_id, car_id=car_id, driver=driver,
            date_from=date_from, date_to=date_to, year=year,
        )
    )
    rows = build_rows(db, q.order_by(Yongcherc.ksdate.asc(), Yongcherc.id.asc()).all(),
                      with_images=False)
    buf = build_daily_excel(rows)
    filename = f"用车登记表_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _attachment(filename)},
    )


@router.get("/export-overlap")
def export_overlap(
    keyword: str = "", dept_id: Optional[int] = None, car_id: Optional[int] = None,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    q = daily_query(
        db, current, **_filter_kwargs(
            keyword=keyword, dept_id=dept_id, car_id=car_id,
            date_from=date_from, date_to=date_to, year=year,
        )
    )
    rows = build_rows(db, q.all(), with_images=False)
    buf = build_overlap_excel(compute_overlap_rows(rows))
    filename = f"公里数出错列表_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _attachment(filename)},
    )


@router.get("/export-gap")
def export_gap(
    keyword: str = "", dept_id: Optional[int] = None, car_id: Optional[int] = None,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    q = daily_query(
        db, current, **_filter_kwargs(
            keyword=keyword, dept_id=dept_id, car_id=car_id,
            date_from=date_from, date_to=date_to, year=year,
        )
    )
    rows = build_rows(db, q.all(), with_images=False)
    buf = build_gap_excel(compute_gap_rows(rows))
    filename = f"公里数空挡列表_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _attachment(filename)},
    )


@router.post("/import")
def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")
    content = file.file.read()
    if len(content) > MAX_EXCEL_SIZE:
        raise HTTPException(status_code=400, detail="文件超过 50MB")
    try:
        return import_dispatch_excel(db, current, content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/extract-mileage")
def extract_mileage(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    return extract_year_mileage(db, current, year)


# ==================== 异常里程 ====================
@router.get("/abnormal")
def list_abnormal(
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    rows = find_abnormal_rows(db, current)
    total = len(rows)
    return {"total": total, "items": rows[(page - 1) * size:page * size]}


@router.post("/abnormal/clean")
def clean_abnormal(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    rows = find_abnormal_rows(db, current)
    ids = [r["id"] for r in rows]
    if not ids:
        return {"success": True, "count": 0}
    records = db.query(Yongcherc).filter(Yongcherc.id.in_(ids)).all()
    _delete_images(db, [r.id for r in records])
    for rec in records:
        db.delete(rec)
    db.commit()
    return {"success": True, "count": len(records)}


# 动态路由必须排在所有静态 GET 之后，避免 /export、/image 等被当成 record_id
@router.get("/{record_id}")
def get_daily(
    record_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    rec = _record_or_404(db, record_id)
    _record_car(db, current, rec)
    row = build_rows(db, [rec])[0]
    row["images"] = [
        r.to_dict() for r in db.query(YongchercTP)
        .filter(YongchercTP.yongchercid == record_id).all()
    ]
    return row
