"""车辆维修(照旧 chelwxController 复刻)。

- 主表 cl_wxdan:维修单台账(日期/部门/车号/维修单位/金额/审批/图片)
- 子表 cl_wxmx:维修明细(配件费/工时费),增删改后自动回写维修单工时费/配件费
- 字典 cl_wxdw:维修单位,按使用频度排序(照旧 GetWxdwAllByFreq)
- 统计:年度按月维修费柱状图(照旧 GetZchart)
- 导出:维修单 / 维修明细两套 Excel(照旧 Excelclwxd)

权限:
- repair:view  模块入口 + 日常操作(新增/编辑自己的单、明细、图片、导出、图表)
- repair:manage 删除维修单
- repair:audit 审批 / 取消审批(旧系统 bb_user.clsp=1 的车辆审批人)
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

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, ClWxdan, ClWxdw, ClWxmx, ClWxdTP
from app.services.repair_common import (
    LX_OPTIONS, PJORGS_OPTIONS, ZK_OPTIONS, build_order_rows, has_perm,
    order_query, recompute_fees, remaining, subtree_ids,
)
from app.services.repair_export import build_excel, excel_disposition

router = APIRouter()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
IMAGE_TOKEN_MINUTES = 30


# ==================== 请求体 ====================
class OrderIn(BaseModel):
    cheid: int
    lx: str
    wxdw: int
    jcriqi: date
    xiangmu: str
    jine: float
    gonglinum: Optional[int] = None
    bxren: str = ""
    ccriqi: Optional[date] = None
    zk: Optional[float] = None


class DetailIn(BaseModel):
    pjorgs: str
    xiangmu: str
    guige: str = ""
    gjz: str = ""
    zkqiandanjia: float
    shuliang: float = 1


class AuditIn(BaseModel):
    ids: List[int]
    approved: bool


# ==================== 公共辅助 ====================
def _get_order_or_404(db: Session, oid: int) -> ClWxdan:
    order = db.get(ClWxdan, oid)
    if order is None:
        raise HTTPException(status_code=404, detail="维修单不存在")
    return order


def _order_car(db: Session, order: ClWxdan) -> Optional[ClChe]:
    return db.get(ClChe, order.cheid) if order.cheid else None


def _check_visible(db: Session, order: ClWxdan, user: User):
    """部门范围兜底(与列表作用域一致;超管/无部门用户不限)。"""
    car = _order_car(db, order)
    if car is None:
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="维修单关联车辆不存在")
        return
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该维修单的权限")


def _is_owner(order, user) -> bool:
    return user.is_superuser or (order.username or "") == (user.username or "")


def _check_editable(db: Session, order: ClWxdan, user: User, is_detail_owner=None):
    _check_visible(db, order, user)
    if is_detail_owner is not None:
        if not is_detail_owner:
            raise HTTPException(status_code=403, detail="不能编辑非自己录入的数据")
    elif not _is_owner(order, user):
        raise HTTPException(status_code=403, detail="不能编辑非自己录入的数据")
    if order.sp:
        raise HTTPException(status_code=400, detail="该维修单已审批，不允许修改")


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
            raise HTTPException(status_code=400, detail=f"只允许上传图片,不支持 {ext or '无扩展名'}")
        content = f.file.read()
        if len(content) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"图片超过 10MB:{f.filename}")
        stored = f"{uuid.uuid4().hex}{ext}"
        (target / stored).write_bytes(content)
        saved.append(f"/Upload/{subdir}/{now.year}/{now.month}/{now.day}/{stored}")
    return saved


def _order_row(db: Session, order: ClWxdan) -> dict:
    return build_order_rows(db, [order])[0]


def _zk(order: ClWxdan) -> float:
    return float(order.zk) if order.zk is not None else 1.0


# ==================== 列表 / 字典 / 图表 / 导出 ====================
@router.get("")
def list_orders(
    page: int = 1,
    size: int = 30,
    rq: Optional[date] = None,
    rqend: Optional[date] = None,
    bmid: Optional[int] = None,
    cheid: Optional[int] = None,
    wxdw: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    q, _start, _end = order_query(db, current, rq=rq, rqend=rqend, bmid=bmid,
                                  cheid=cheid, wxdw=wxdw, keyword=keyword)
    total = q.count()
    jine_sum = q.with_entities(func.coalesce(func.sum(ClWxdan.jine), 0)).scalar() or 0
    orders = (
        q.order_by(ClWxdan.djriqi.desc(), ClWxdan.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {
        "total": total,
        "items": build_order_rows(db, orders),
        "footer": {"jine": round(float(jine_sum), 2)},
    }


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]

    cq = db.query(ClChe).filter(ClChe.delf == 1, ClChe.yongtu != "油卡")
    if scope is not None:
        cq = cq.filter(ClChe.bmid.in_(scope))
    names = dept_name_map(db)
    vehicles = [
        {"id": c.id, "chehao": c.chehao or "",
         "bumen": names.get(c.bmid) or c.bm or "",
         "text": f"{c.chehao or ''} → {names.get(c.bmid) or c.bm or ''}"}
        for c in cq.order_by(ClChe.chehao).all()
    ]

    wcq = db.query(ClWxdan.wxdw, func.count(ClWxdan.id)).join(
        ClChe, ClWxdan.cheid == ClChe.id
    ).filter(ClWxdan.wxdw.isnot(None))
    if scope is not None:
        wcq = wcq.filter(ClChe.bmid.in_(scope))
    counts = dict(wcq.group_by(ClWxdan.wxdw).all())
    units = db.query(ClWxdw).filter(ClWxdw.id != 0).order_by(ClWxdw.dwname).all()
    wxdw_all = sorted(
        [{"id": u.id, "dwname": u.dwname or "", "count": counts.get(u.id, 0)} for u in units if u.dwname],
        key=lambda r: (-r["count"], r["dwname"]),
    )
    wxdw_used = [u for u in wxdw_all if u["count"] > 0]

    years = list(range(date.today().year - 5, date.today().year + 1))[::-1]
    return {
        "departments": departments,
        "vehicles": vehicles,
        "wxdw_all": wxdw_all,
        "wxdw_used": wxdw_used,
        "lx": LX_OPTIONS,
        "pjorgs": PJORGS_OPTIONS,
        "zk": ZK_OPTIONS,
        "years": years,
        "current_year": date.today().year,
        "perms": {
            "view": True,
            "manage": has_perm(current, "repair:manage"),
            "audit": has_perm(current, "repair:audit"),
        },
    }


@router.get("/vehicles")
def search_vehicles(
    num: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    """添加维修单左侧:按车号模糊查车(照旧 getch)。"""
    scope = dept_scope_ids(db, current)
    q = db.query(ClChe).filter(ClChe.delf == 1, ClChe.yongtu != "油卡")
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    if num.strip():
        q = q.filter(ClChe.chehao.contains(num.strip()))
    names = dept_name_map(db)
    rows = q.order_by(ClChe.chehao).limit(50).all()
    return [
        {"id": c.id, "chehao": c.chehao or "",
         "bumen": names.get(c.bmid) or c.bm or "",
         "text": f"{c.chehao or ''} → {names.get(c.bmid) or c.bm or ''}"}
        for c in rows
    ]


@router.get("/vehicle-history")
def vehicle_history(
    cheid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    """添加维修单左侧:选中车辆的历史维修记录(照旧 Getwxd)。"""
    car = db.get(ClChe, cheid)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = dept_scope_ids(db, current)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有查看该车辆的权限")
    orders = db.query(ClWxdan).filter(ClWxdan.cheid == cheid).order_by(
        ClWxdan.jcriqi.desc(), ClWxdan.id.desc()
    ).all()
    rows = build_order_rows(db, orders)
    return {"total": len(rows), "items": [
        {k: r[k] for k in ("ID", "xiangmu", "chehao", "gonglinum", "jine", "jcriqi", "sp")}
        for r in rows
    ]}


@router.get("/chart")
def chart(
    bmid: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    """年度按月维修费(照旧 GetZchart:按进场日期所在年份统计)。"""
    y = year or date.today().year
    start, end = date(y, 1, 1), date(y + 1, 1, 1)
    month_expr = func.month(ClWxdan.jcriqi)
    q = db.query(month_expr, func.coalesce(func.sum(ClWxdan.jine), 0)).join(
        ClChe, ClWxdan.cheid == ClChe.id
    ).filter(ClWxdan.jcriqi >= start, ClWxdan.jcriqi < end)
    scope = dept_scope_ids(db, current)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    if bmid:
        q = q.filter(ClChe.bmid.in_(subtree_ids(db, bmid)))
    months = [0.0] * 12
    for m, s in q.group_by(month_expr).all():
        if m:
            months[int(m) - 1] = round(float(s), 2)
    total = round(sum(months), 2)
    names = dept_name_map(db)
    if bmid:
        name = names.get(bmid, "")
    elif scope is None:
        name = "全部部门"
    else:
        name = next((d.name for d in current.departments), "本部门")
    return {"name": name, "year": y, "total": total, "months": months}


@router.get("/export")
def export_orders(
    kind: str = "dan",
    rq: Optional[date] = None,
    rqend: Optional[date] = None,
    bmid: Optional[int] = None,
    cheid: Optional[int] = None,
    wxdw: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    q, _start, _end = order_query(db, current, rq=rq, rqend=rqend, bmid=bmid,
                                  cheid=cheid, wxdw=wxdw, keyword=keyword)
    orders = q.order_by(ClWxdan.djriqi.desc(), ClWxdan.id.desc()).all()
    rows = build_order_rows(db, orders)
    if kind == "mx":
        detail_rows = []
        order_map = {o.id: o for o in orders}
        row_map = {r["ID"]: r for r in rows}
        details = db.query(ClWxmx).filter(
            ClWxmx.wxdid.in_([o.id for o in orders] or [0])
        ).order_by(ClWxmx.wxdid, ClWxmx.djriqi.desc()).all()
        for d in details:
            base = row_map.get(d.wxdid)
            order = order_map.get(d.wxdid)
            if not base or not order:
                continue
            item = d.to_dict()
            item.update({
                "jcriqi": base["jcriqi"], "bm": base["bm"], "chehao": base["chehao"],
                "gonglinum": base["gonglinum"], "cllx": base["cllx"],
                "jiashiyuan": base["jiashiyuan"], "telphone": base["telphone"],
                "chuchang": base["chuchang"],
                "car_age": (
                    order.jcriqi.year - int(base["chuchang"][:4])
                    if order.jcriqi and base["chuchang"] else None
                ),
            })
            detail_rows.append(item)
        filename = "车辆维修明细.xlsx"
    else:
        detail_rows = rows
        filename = "车辆维修单.xlsx"
    buf = build_excel(detail_rows, "mx" if kind == "mx" else "dan")
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


# ==================== 明细(静态先于 /{order_id}) ====================
@router.get("/details")
def search_details(
    cheid: Optional[int] = None,
    wxdid: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    """添加明细弹窗左侧:该车全部维修明细,可按项目名/关键字过滤(照旧 Getwxmx)。"""
    if not wxdid:
        return {"total": 0, "items": []}
    order = _get_order_or_404(db, wxdid)
    _check_visible(db, order, current)
    q = db.query(ClWxmx)
    if cheid:
        q = q.filter(ClWxmx.cheid == cheid)
    kw = (keyword or "").strip()
    if kw:
        q = q.filter((ClWxmx.xiangmu.contains(kw)) | (ClWxmx.gjz.contains(kw)))
    details = q.order_by(ClWxmx.djriqi.desc(), ClWxmx.id.desc()).all()
    order_map = {}
    ids = {d.wxdid for d in details if d.wxdid}
    if ids:
        order_map = {o.id: o for o in db.query(ClWxdan).filter(ClWxdan.id.in_(ids)).all()}
    items = []
    for d in details:
        item = d.to_dict()
        o = order_map.get(d.wxdid)
        item["jcriqi"] = o.jcriqi.strftime("%Y-%m-%d") if o and o.jcriqi else None
        items.append(item)
    return {"total": len(items), "items": items}


@router.put("/details/{detail_id}")
def update_detail(
    detail_id: int,
    data: DetailIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    mx = db.get(ClWxmx, detail_id)
    if mx is None:
        raise HTTPException(status_code=404, detail="维修明细不存在")
    order = _get_order_or_404(db, mx.wxdid)
    _check_editable(db, order, current, is_detail_owner=(mx.username or "") == (current.username or "") or current.is_superuser)
    if data.pjorgs not in PJORGS_OPTIONS:
        raise HTTPException(status_code=400, detail="请选择配件费或工时费")
    if not data.xiangmu.strip():
        raise HTTPException(status_code=400, detail="请填写项目名称")
    mx.pjorgs = data.pjorgs
    mx.xiangmu = data.xiangmu.strip()
    mx.guige = (data.guige or "").strip()
    mx.gjz = (data.gjz or "").strip()
    mx.zkqiandanjia = data.zkqiandanjia
    mx.danjia = round(_zk(order) * float(data.zkqiandanjia), 2)
    mx.shuliang = data.shuliang
    mx.zonge = round(float(mx.danjia) * float(data.shuliang or 0), 2)
    mx.username = current.username
    mx.djriqi = datetime.now()
    recompute_fees(db, order)
    db.commit()
    return {"ok": True, "detail": mx.to_dict(), "order": _order_row(db, order)}


@router.delete("/details/{detail_id}")
def delete_detail(
    detail_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    mx = db.get(ClWxmx, detail_id)
    if mx is None:
        raise HTTPException(status_code=404, detail="维修明细不存在")
    order = _get_order_or_404(db, mx.wxdid)
    _check_editable(db, order, current, is_detail_owner=(mx.username or "") == (current.username or "") or current.is_superuser)
    db.delete(mx)
    db.flush()
    recompute_fees(db, order)
    db.commit()
    return {"ok": True, "order": _order_row(db, order)}


# ==================== 图片 ====================
@router.post("/images/{image_id}/token")
def image_token(
    image_id: int,
    user: User = Depends(require_permission("repair:view")),
    db: Session = Depends(get_db),
):
    row = db.get(ClWxdTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    token = create_short_token(
        "repair_image", {"iid": image_id, "sub": str(user.id)}, minutes=IMAGE_TOKEN_MINUTES
    )
    return {"token": token, "url": f"/api/repairs/image?token={token}",
            "expires_minutes": IMAGE_TOKEN_MINUTES}


@router.get("/image")
def image_file(token: str = "", db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "repair_image")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    row = db.get(ClWxdTP, int(payload.get("iid", 0)))
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _image_path(row.url)
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片文件缺失(旧系统生产服务器 Upload 目录未拷入)")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    row = db.get(ClWxdTP, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    order = _get_order_or_404(db, row.wxdid)
    _check_editable(db, order, current)
    path = _image_path(row.url)
    if path.exists():
        path.unlink()
    db.delete(row)
    db.commit()
    return {"ok": True}


# ==================== 审批 ====================
@router.post("/audit")
def audit_orders(
    data: AuditIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:audit")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请选择维修单")
    orders = db.query(ClWxdan).filter(ClWxdan.id.in_(data.ids)).all()
    now = datetime.now()
    for o in orders:
        _check_visible(db, o, current)
        o.sp = data.approved
        o.spren = current.username
        o.sptime = now
    db.commit()
    return {"ok": True, "count": len(orders), "approved": data.approved}


# ==================== 维修单 ====================
@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_visible(db, order, current)
    row = _order_row(db, order)
    details = db.query(ClWxmx).filter(ClWxmx.wxdid == order_id).order_by(
        ClWxmx.djriqi.desc(), ClWxmx.id.desc()
    ).all()
    row["details"] = [d.to_dict() for d in details]
    return row


@router.get("/{order_id}/details")
def list_details(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_visible(db, order, current)
    rows = db.query(ClWxmx).filter(ClWxmx.wxdid == order_id).order_by(
        ClWxmx.djriqi.desc(), ClWxmx.id.desc()
    ).all()
    return {"total": len(rows), "items": [r.to_dict() for r in rows]}


@router.get("/{order_id}/remaining")
def get_remaining(
    order_id: int,
    ze: float = 0,
    mxid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_visible(db, order, current)
    if mxid:
        mx = db.get(ClWxmx, mxid)
        if mx is None or mx.wxdid != order_id:
            raise HTTPException(status_code=400, detail="明细不属于该维修单")
    value = remaining(db, order, ze=ze, mxid=mxid)
    return {"remaining": value, "text": f"尚需：{value}元"}


@router.post("")
def create_order(
    data: OrderIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    car = db.get(ClChe, data.cheid)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=400, detail="请选择有效车辆")
    scope = dept_scope_ids(db, current)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")
    if db.get(ClWxdw, data.wxdw) is None:
        raise HTTPException(status_code=400, detail="请选择维修单位")
    if not data.xiangmu.strip():
        raise HTTPException(status_code=400, detail="请填写项目名称")
    if not data.lx.strip():
        raise HTTPException(status_code=400, detail="请至少选择一个维修类别")

    order = ClWxdan(
        cheid=data.cheid, lx=data.lx.strip(), wxdw=data.wxdw,
        jcriqi=data.jcriqi, xiangmu=data.xiangmu.strip(), jine=data.jine,
        gonglinum=data.gonglinum, bxren=(data.bxren or "").strip(),
        ccriqi=data.ccriqi, zk=data.zk if data.zk is not None else 1,
        djriqi=datetime.now(), username=current.username,
        gongshifei=0, peijianfei=0, sp=False, spren="", sptime=None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_row(db, order)


@router.put("/{order_id}")
def update_order(
    order_id: int,
    data: OrderIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_editable(db, order, current)
    car = db.get(ClChe, data.cheid)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=400, detail="请选择有效车辆")
    scope = dept_scope_ids(db, current)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该车辆的权限")
    if db.get(ClWxdw, data.wxdw) is None:
        raise HTTPException(status_code=400, detail="请选择维修单位")
    if not data.xiangmu.strip():
        raise HTTPException(status_code=400, detail="请填写项目名称")
    if not data.lx.strip():
        raise HTTPException(status_code=400, detail="请至少选择一个维修类别")

    order.cheid = data.cheid
    order.lx = data.lx.strip()
    order.wxdw = data.wxdw
    order.jcriqi = data.jcriqi
    order.xiangmu = data.xiangmu.strip()
    order.jine = data.jine
    order.gonglinum = data.gonglinum
    order.bxren = (data.bxren or "").strip()
    order.ccriqi = data.ccriqi
    order.zk = data.zk if data.zk is not None else 1
    order.djriqi = datetime.now()
    order.username = current.username
    recompute_fees(db, order)
    db.commit()
    db.refresh(order)
    return _order_row(db, order)


@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:manage")),
):
    order = _get_order_or_404(db, order_id)
    _check_visible(db, order, current)
    if db.query(func.count(ClWxmx.id)).filter(ClWxmx.wxdid == order_id).scalar():
        raise HTTPException(status_code=400, detail="该维修单有明细记录，无法删除")
    if order.sp:
        raise HTTPException(status_code=400, detail="已审批，无法删除")
    for tp in db.query(ClWxdTP).filter(ClWxdTP.wxdid == order_id).all():
        path = _image_path(tp.url)
        if path.exists():
            path.unlink()
        db.delete(tp)
    db.delete(order)
    db.commit()
    return {"ok": True}


@router.post("/{order_id}/details")
def add_detail(
    order_id: int,
    data: DetailIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_editable(db, order, current)
    if data.pjorgs not in PJORGS_OPTIONS:
        raise HTTPException(status_code=400, detail="请选择配件费或工时费")
    if not data.xiangmu.strip():
        raise HTTPException(status_code=400, detail="请填写项目名称")
    mx = ClWxmx(
        wxdid=order_id, cheid=order.cheid, pjorgs=data.pjorgs,
        xiangmu=data.xiangmu.strip(), guige=(data.guige or "").strip(),
        gjz=(data.gjz or "").strip(), zkqiandanjia=data.zkqiandanjia,
        danjia=round(_zk(order) * float(data.zkqiandanjia), 2),
        shuliang=data.shuliang or 0,
        username=current.username, djriqi=datetime.now(),
    )
    mx.zonge = round(float(mx.danjia) * float(mx.shuliang or 0), 2)
    db.add(mx)
    db.flush()
    recompute_fees(db, order)
    db.commit()
    db.refresh(mx)
    return {"ok": True, "detail": mx.to_dict(), "order": _order_row(db, order)}


@router.post("/{order_id}/images")
def upload_images(
    order_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("repair:view")),
):
    order = _get_order_or_404(db, order_id)
    _check_editable(db, order, current)
    urls = _save_images(files, "weixiudanImages")
    rows = []
    for url in urls:
        tp = ClWxdTP(wxdid=order_id, url=url)
        db.add(tp)
        rows.append(tp)
    db.commit()
    return {"ok": True, "items": [{"id": r.id, "url": r.url} for r in rows]}
