"""车辆管理(照旧 cheliangguanliController 复刻)。

- 主表 cl_che:台账 CRUD / 软删 / 报废 / 审批状态 / 部门数据权限
- 年检:标注、撤销、批量标注,周期按车辆类型+车龄重算(照 CarNianJian.cs)
- 子表:车辆图片、出险记录(含出险图片)
- 统计:年度加油升数/派车次数/维修次数金额/出险数、加油月度明细
- 导出:Excel 台账(25 列)、车辆图片资料 PDF

权限:vehicle:view=入口 + 日常操作(增删改/年检/出险登记/统计/导出);
     vehicle:manage=删除车辆/报废/图片附件类管理操作(与工程、水费模块口径一致)。
"""

import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import (
    dept_name_map, dept_scope_ids, get_current_user, require_permission,
)
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, ClChetupian, ClChuxian, ClCxTP, ClWxdan, PlusOil, Yongcherc
from app.services.vehicle_common import (
    DATE_FIELDS, EDITABLE_FIELDS, LX_OPTIONS, NUMBER_FIELDS, OIL_OPTIONS,
    REMINDER_LABELS, STATUS_OPTIONS, YONGTU_OPTIONS, ZEREN_OPTIONS,
    build_rows, correct_next_inspection, filtered_query, refresh_inspection_cycle,
)
from app.services.vehicle_export import (
    build_excel, build_pdf, content_disposition, excel_filename, pdf_disposition,
)

router = APIRouter()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
IMAGE_TOKEN_MINUTES = 30


# ==================== 请求体 ====================
class VehicleIn(BaseModel):
    """全部可选:编辑时没传的字段视为不修改。"""

    lx: Optional[str] = None
    jiashiyuan: Optional[str] = None
    telphone: Optional[str] = None
    chehao: Optional[str] = None
    chuchang: Optional[date] = None
    pingshi: Optional[str] = None
    zhoumo: Optional[str] = None
    bmid: Optional[int] = None
    yongtu: Optional[str] = None
    oil: Optional[str] = None
    oilcard: Optional[str] = None
    jsz: Optional[str] = None
    jiage: Optional[float] = None
    grriqi: Optional[date] = None
    etc: Optional[str] = None
    danganhao: Optional[str] = None
    syxingzhi: Optional[str] = None
    zws: Optional[int] = None
    fadongjihao: Optional[str] = None
    chejiahao: Optional[str] = None
    pailiang: Optional[str] = None
    pinpai: Optional[str] = None
    xinghao: Optional[str] = None


class AccidentIn(BaseModel):
    riqi: Optional[date] = None
    zeren: Optional[str] = None
    jiashiyuan: Optional[str] = None
    jine: Optional[float] = None
    miaoshu: Optional[str] = None
    dizhi: Optional[str] = None
    gongli: Optional[int] = None
    bm: Optional[str] = None


class InspectIn(BaseModel):
    riqi: Optional[date] = None


class BatchInspectIn(BaseModel):
    ids: List[int]
    riqi: Optional[date] = None


class PdfIn(BaseModel):
    ids: List[int]


# ==================== 公共辅助 ====================
def _get_car_or_404(db: Session, vid: int) -> ClChe:
    car = db.get(ClChe, vid)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=404, detail="车辆不存在")
    return car


def _check_visible(car: ClChe, db: Session, user: User):
    """非超管不能操作本人部门子树之外的车辆(与列表作用域一致)。"""
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")


def _resolve_bmid(value, user: User) -> Optional[int]:
    """照工程模块归属规则:多部门用户可在本人部门内自选,越界/未选兜底第一个;超管自由选。"""
    if user.is_superuser:
        return value
    my_ids = [d.id for d in user.departments]
    if not my_ids:
        return value
    return value if value in my_ids else my_ids[0]


def _apply_fields(car: ClChe, data: VehicleIn, db: Session, user: User, creating: bool):
    old_chuchang, old_lx = car.chuchang, car.lx
    for f in EDITABLE_FIELDS:
        v = getattr(data, f)
        if v is not None:
            setattr(car, f, v.strip() if isinstance(v, str) else v)
    for f in DATE_FIELDS:
        # 只有前端显式传了字段才写(传 null 表示清空);未传保持不变
        if f in data.model_fields_set:
            setattr(car, f, getattr(data, f))
    for f in NUMBER_FIELDS:
        v = getattr(data, f)
        if v is not None:
            setattr(car, f, v)

    if creating:
        car.bmid = _resolve_bmid(data.bmid, user)
    elif data.bmid is not None:
        car.bmid = _resolve_bmid(data.bmid, user)
    names = dept_name_map(db)
    if car.bmid:
        car.bm = names.get(car.bmid, car.bm or "")

    # 注册日期/类型变化 → 重算年检周期(照旧 Editcl / Addcl)
    if creating or car.chuchang != old_chuchang or car.lx != old_lx:
        refresh_inspection_cycle(car)

    car.caozuo = user.username
    car.zuihoutime = datetime.now()
    # 新增或改过资料都要重新审批(照旧 Addcl/Editcl)
    car.spzt = "待审批"
    car.spren = ""
    car.spdate = None


def _image_path(url: str) -> Path:
    """旧库 url 形如 /Upload/cheliangImages/2021/7/28/x.jpg,映射到 uploads 下同名目录。

    把旧系统生产服务器的 Upload 目录拷进 backend/uploads 即可恢复历史图片。
    """
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
            raise HTTPException(status_code=400, detail=f"只允许上传图片,不支持 {ext or '无扩展名'}")
        content = f.file.read()
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"图片超过 10MB:{f.filename}")
        stored = f"{uuid.uuid4().hex}{ext}"
        (target / stored).write_bytes(content)
        url = f"/Upload/{subdir}/{now.year}/{now.month}/{now.day}/{stored}"
        saved.append((url, f.filename or stored))
    return saved


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def list_vehicles(
    page: int = 1,
    size: int = 10,
    keyword: str = "",
    bmid: Optional[int] = None,
    chellx: str = "",
    chelyt: str = "",
    scrap: bool = False,
    nocd: bool = False,
    next_month: bool = False,
    year: Optional[int] = None,
    sort: str = "",
    order: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    year = year or date.today().year
    q = filtered_query(db, current, keyword=keyword, bmid=bmid, chellx=chellx,
                       chelyt=chelyt, scrap=scrap, nocd=nocd, next_month=next_month)
    rows = build_rows(db, q.all(), year)
    # 默认按部门+车号;前端点表头可排任意返回字段(年度统计列也能排,照旧 oilYear 排序)
    if sort and sort in (rows[0].keys() if rows else {}):
        non_null = [r for r in rows if r.get(sort) is not None]
        nulls = [r for r in rows if r.get(sort) is None]
        try:
            non_null.sort(key=lambda r: r[sort], reverse=order.lower() == "desc")
        except TypeError:
            non_null.sort(key=lambda r: str(r[sort]), reverse=order.lower() == "desc")
        rows = non_null + nulls
    else:
        rows.sort(key=lambda r: (r.get("bumen") or "", r.get("chehao") or ""))
    total = len(rows)
    return {"total": total, "items": rows[(page - 1) * size:page * size]}


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
    lx_used = [r[0] for r in db.query(ClChe.lx).filter(ClChe.delf != 0, ClChe.lx != "")
               .distinct().order_by(ClChe.lx).all()]
    yt_used = [r[0] for r in db.query(ClChe.yongtu).filter(ClChe.delf != 0, ClChe.yongtu != "")
               .distinct().order_by(ClChe.yongtu).all()]
    y = date.today().year
    return {
        "lx": LX_OPTIONS, "yongtu": YONGTU_OPTIONS, "oil": OIL_OPTIONS,
        "zeren": ZEREN_OPTIONS, "status": STATUS_OPTIONS,
        "reminder": [{"value": k, "label": v} for k, v in REMINDER_LABELS.items()],
        "departments": departments, "lx_used": lx_used, "yongtu_used": yt_used,
        "years": list(range(y - 9, y + 2)), "current_year": y,
    }


@router.get("/export")
def export_excel(
    keyword: str = "", bmid: Optional[int] = None, chellx: str = "", chelyt: str = "",
    scrap: bool = False, nocd: bool = False, next_month: bool = False,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    q = filtered_query(db, current, keyword=keyword, bmid=bmid, chellx=chellx,
                       chelyt=chelyt, scrap=scrap, nocd=nocd, next_month=next_month)
    rows = build_rows(db, q.all(), year or date.today().year)
    buf = build_excel(rows)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(excel_filename())},
    )


@router.post("/export-pdf")
def export_pdf(
    data: PdfIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请先选择要导出的车辆")
    cars = db.query(ClChe).filter(ClChe.id.in_(data.ids), ClChe.delf != 0).all()
    for car in cars:
        _check_visible(car, db, current)
    rows = build_rows(db, cars, date.today().year)
    image_paths = {}
    for row in rows:
        paths = []
        for img in row.get("tps", []):
            p = _image_path(img["url"])
            if p.exists():
                paths.append(p)
        image_paths[row["id"]] = paths
    buf = build_pdf(rows, image_paths)
    return Response(
        content=buf.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition": pdf_disposition("车辆图片资料.pdf")},
    )


# ==================== 年检 ====================
def _mark_inspected(car: ClChe, day: date):
    if car.IsInspected:
        raise HTTPException(status_code=400, detail="该车辆已标注年检")
    car.IsInspected = True
    car.InspectionDate = day
    car.ReminderLevel = 0
    car.LastReminderDate = None
    car.NextInspectionDate = correct_next_inspection(car, "标注年检")


@router.post("/batch-inspect")
def batch_inspect(
    data: BatchInspectIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    day = data.riqi or date.today()
    ok, failed = 0, []
    for vid in data.ids:
        car = db.get(ClChe, vid)
        if car is None or car.delf == 0:
            failed.append({"id": vid, "reason": "车辆不存在"})
            continue
        try:
            _check_visible(car, db, current)
            _mark_inspected(car, day)
            ok += 1
        except HTTPException as e:
            failed.append({"id": vid, "reason": e.detail})
    db.commit()
    return {"success": ok, "failed": failed, "date": day.isoformat()}


# ==================== 图片(短时效令牌直链) ====================
@router.post("/images/{image_id}/token")
def create_image_token(
    image_id: int,
    kind: str = "car",  # car=车辆图片, accident=出险图片
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("vehicle:view")),
):
    model = ClCxTP if kind == "accident" else ClChetupian
    if db.get(model, image_id) is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    token = create_short_token(
        "vehicle_image", {"iid": image_id, "k": kind, "sub": str(user.id)},
        minutes=IMAGE_TOKEN_MINUTES,
    )
    return {"token": token, "url": f"/api/vehicles/image?token={token}",
            "expires_minutes": IMAGE_TOKEN_MINUTES}


@router.get("/image")
def image_file(token: str = "", db: Session = Depends(get_db)):
    """<img> 直链用:只认短时效图片令牌,不认登录令牌。"""
    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "vehicle_image")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="签发账号不可用")
    kind = payload.get("k", "car")
    model = ClCxTP if kind == "accident" else ClChetupian
    row = db.get(model, int(payload.get("iid", 0)))
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
    current: User = Depends(require_permission("vehicle:manage")),
):
    row = db.get(ClChetupian, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    car = db.get(ClChe, row.cheid) if row.cheid else None
    if car:
        _check_visible(car, db, current)
    path = _image_path(row.url)
    if path.exists():
        path.unlink()
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.delete("/accident-images/{image_id}")
def delete_accident_image(
    image_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("vehicle:manage")),
):
    row = db.get(ClCxTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _image_path(row.url)
    if path.exists():
        path.unlink()
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


# ==================== 出险记录 ====================
def _get_accident_or_404(db: Session, aid: int) -> ClChuxian:
    row = db.get(ClChuxian, aid)
    if row is None:
        raise HTTPException(status_code=404, detail="出险记录不存在")
    return row


@router.get("/accidents/{acc_id}/images")
def list_accident_images(
    acc_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("vehicle:view")),
):
    return [r.to_dict() for r in db.query(ClCxTP).filter(ClCxTP.cxid == acc_id).all()]


@router.post("/accidents/{acc_id}/images")
def upload_accident_images(
    acc_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("vehicle:manage")),
):
    _get_accident_or_404(db, acc_id)
    saved = []
    for url, _name in _save_images(files, "cheliangImages/chuxian"):
        row = ClCxTP(cxid=acc_id, url=url)
        db.add(row)
        saved.append(row)
    db.commit()
    return [r.to_dict() for r in saved]


@router.put("/accidents/{acc_id}")
def update_accident(
    acc_id: int,
    data: AccidentIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_accident_or_404(db, acc_id)
    car = db.get(ClChe, row.cheid) if row.cheid else None
    if car:
        _check_visible(car, db, current)
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v.strip() if isinstance(v, str) else v)
    row.caozuo = current.username
    row.zuihou = datetime.now()
    db.commit()
    return row.to_dict()


@router.delete("/accidents/{acc_id}")
def delete_accident(
    acc_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    row = _get_accident_or_404(db, acc_id)
    car = db.get(ClChe, row.cheid) if row.cheid else None
    if car:
        _check_visible(car, db, current)
    db.query(ClCxTP).filter(ClCxTP.cxid == acc_id).delete()
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


# ==================== 单车主资源(静态路径必须排在 /{vehicle_id} 之前) ====================
@router.get("/{vehicle_id}")
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    d = build_rows(db, [car], date.today().year)[0]
    d["images"] = [r.to_dict() for r in db.query(ClChetupian)
                   .filter(ClChetupian.cheid == vehicle_id).all()]
    return d


@router.post("")
def create_vehicle(
    data: VehicleIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    if not (data.chehao or "").strip():
        raise HTTPException(status_code=400, detail="车号不能为空")
    if not (data.lx or "").strip():
        raise HTTPException(status_code=400, detail="车辆类型不能为空")
    if db.query(ClChe).filter(ClChe.chehao == data.chehao.strip(), ClChe.delf == 1).first():
        raise HTTPException(status_code=400, detail="已有该车号")
    car = ClChe(delf=1, shenheren="")
    _apply_fields(car, data, db, current, creating=True)
    db.add(car)
    db.commit()
    db.refresh(car)
    return car.to_dict()


@router.put("/{vehicle_id}")
def update_vehicle(
    vehicle_id: int,
    data: VehicleIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    if data.chehao is not None and not data.chehao.strip():
        raise HTTPException(status_code=400, detail="车号不能为空")
    if data.chehao and db.query(ClChe).filter(
        ClChe.id != vehicle_id, ClChe.chehao == data.chehao.strip()
    ).first():
        raise HTTPException(status_code=400, detail="已有该车号")
    _apply_fields(car, data, db, current, creating=False)
    db.commit()
    return car.to_dict()


@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    # 照旧 Deletecl:有派车/加油记录不允许删除
    if db.query(Yongcherc).filter(Yongcherc.cheid == vehicle_id).count():
        raise HTTPException(status_code=400, detail="已有用车记录，无法删除")
    if db.query(PlusOil).filter(PlusOil.cheid == vehicle_id).count():
        raise HTTPException(status_code=400, detail="已有加油记录，无法删除")
    car.delf = 0
    car.chehao = (car.chehao or "") + "_X"
    car.zuihoutime = datetime.now()
    car.caozuo = current.username
    db.commit()
    return {"message": "已删除"}


@router.put("/{vehicle_id}/scrap")
def scrap_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    if car.delf == 2:
        raise HTTPException(status_code=400, detail="该车辆已报废")
    car.delf = 2
    car.zuihoutime = datetime.now()
    db.commit()
    return {"message": "已报废"}


@router.post("/{vehicle_id}/inspect")
def inspect_vehicle(
    vehicle_id: int,
    data: InspectIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    _mark_inspected(car, data.riqi or date.today())
    db.commit()
    return {"message": "已标注年检", "NextInspectionDate": car.NextInspectionDate}


@router.post("/{vehicle_id}/undo-inspect")
def undo_inspect(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    if not car.IsInspected:
        raise HTTPException(status_code=400, detail="该车辆未标注年检")
    car.IsInspected = False
    car.InspectionDate = None
    car.NextInspectionDate = correct_next_inspection(car, "撤销年检")
    car.ReminderLevel = 0
    car.LastReminderDate = None
    db.commit()
    return {"message": "已撤销年检", "NextInspectionDate": car.NextInspectionDate}


@router.get("/{vehicle_id}/oil-month-stat")
def oil_month_stat(
    vehicle_id: int,
    year: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    year = year or date.today().year
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    base = db.query(PlusOil).filter(PlusOil.cheid == vehicle_id,
                                    PlusOil.ptime >= start, PlusOil.ptime < end)
    monthly = {(m, lei): (oill, jine, n) for m, lei, oill, jine, n in (
        base.with_entities(func.month(PlusOil.ptime), PlusOil.lei,
                           func.sum(PlusOil.oill), func.sum(PlusOil.jine), func.count())
        .group_by(func.month(PlusOil.ptime), PlusOil.lei).all()
    )}
    # 第 4 列按旧系统口径是「派车次数」(yongcherc 按月计数),不是加油笔数
    use_month = {m: int(n) for m, n in (
        db.query(func.month(Yongcherc.ksdate), func.count())
        .filter(Yongcherc.cheid == vehicle_id,
                Yongcherc.ksdate >= start, Yongcherc.ksdate < end)
        .group_by(func.month(Yongcherc.ksdate)).all()
    )}
    months = []
    for m in range(1, 13):
        details = [{"lei": lei or "-", "oill": round(float(v[0] or 0), 2),
                    "jine": round(float(v[1] or 0), 2), "count": int(v[2])}
                   for (mm, lei), v in monthly.items() if mm == m]
        months.append({
            "month": m, "oill": round(sum(d["oill"] for d in details), 2),
            "jine": round(sum(d["jine"] for d in details), 2),
            "count": sum(d["count"] for d in details), "details": details,
            "useCount": use_month.get(m, 0),
        })
    return {
        "year": year, "chehao": car.chehao, "months": months,
        "total_oill": round(sum(m["oill"] for m in months), 2),
        "total_jine": round(sum(m["jine"] for m in months), 2),
        "total_use_count": sum(use_month.values()),
    }


@router.get("/{vehicle_id}/accidents")
def list_accidents(
    vehicle_id: int,
    year: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    q = db.query(ClChuxian).filter(ClChuxian.cheid == vehicle_id)
    if year:
        q = q.filter(ClChuxian.riqi >= date(year, 1, 1),
                     ClChuxian.riqi < date(year + 1, 1, 1))
    rows = q.order_by(ClChuxian.riqi.desc(), ClChuxian.id.desc()).all()
    out = []
    for r in rows:
        d = r.to_dict()
        d["images"] = [i.to_dict() for i in db.query(ClCxTP).filter(ClCxTP.cxid == r.id).all()]
        out.append(d)
    return out


@router.post("/{vehicle_id}/accidents")
def add_accident(
    vehicle_id: int,
    data: AccidentIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:view")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    if data.riqi is None:
        raise HTTPException(status_code=400, detail="出险日期不能为空")
    row = ClChuxian(
        riqi=data.riqi, cheid=vehicle_id,
        bm=data.bm or dept_name_map(db).get(car.bmid) or car.bm or "",
        zeren=data.zeren or "", jiashiyuan=data.jiashiyuan or "",
        jine=data.jine, miaoshu=data.miaoshu or "", dizhi=data.dizhi or "",
        gongli=data.gongli, caozuo=current.username, zuihou=datetime.now(),
    )
    db.add(row)
    db.commit()
    return row.to_dict()


@router.post("/{vehicle_id}/images")
def upload_vehicle_images(
    vehicle_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("vehicle:manage")),
):
    car = _get_car_or_404(db, vehicle_id)
    _check_visible(car, db, current)
    saved = []
    for url, name in _save_images(files, "cheliangImages"):
        row = ClChetupian(cheid=vehicle_id, url=url, file_name=name)
        db.add(row)
        saved.append(row)
    db.commit()
    return [r.to_dict() for r in saved]
