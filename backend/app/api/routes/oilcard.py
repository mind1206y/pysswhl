"""油卡管理(照旧 OilCarManController 复刻)。

- 列表:按部门作用域 + 关键字/状态/部门/车型/用途筛选,含上月本月加油、年度统计、余额预警
- 台账 CRUD;油卡明细表/余额记录/消费明细 Excel 导入;模板下载
- 导出:补充到定额、差额充值(智能预测/历史最高)、手动充值表;手动充值清零
- 图表/明细:按卡的月度加油金额与升数、派车次数

权限:oilcard:view=入口 + 日常操作(增删改/查询/导出);
     oilcard:manage=删除、Excel 导入、手动充值清零。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClChe, OilCard
from app.services import oilcard_common as svc

router = APIRouter()

NAME = "油卡"


# ==================== 请求体 ====================
class OilCardCreate(BaseModel):
    kanum: str
    yanzhengma: Optional[str] = None
    carid: Optional[int] = None
    youpin: Optional[str] = None
    zt: Optional[str] = None
    bz: Optional[str] = None
    handadd: Optional[float] = None


class OilCardUpdate(BaseModel):
    kanum: Optional[str] = None
    yanzhengma: Optional[str] = None
    carid: Optional[int] = None
    youpin: Optional[str] = None
    zt: Optional[str] = None
    bz: Optional[str] = None
    handadd: Optional[float] = None


# ==================== 公共辅助 ====================
def _get_card_or_404(db: Session, card_id: int) -> OilCard:
    card = db.get(OilCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"{NAME}不存在")
    return card


def _check_visible(db: Session, card: OilCard, user: User):
    if not svc.card_visible(db, card, user):
        raise HTTPException(status_code=403, detail=f"没有操作该{NAME}的权限")


def _check_car_visible(db: Session, car_id: Optional[int], user: User):
    if not car_id:
        return
    car = db.get(ClChe, car_id)
    if car is None or car.delf == 0:
        raise HTTPException(status_code=400, detail="所选车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="所选车辆不在本人部门范围内")


def _content_disposition(filename: str) -> str:
    return f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(filename)}"


def _excel_response(buf, filename: str) -> Response:
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


# ==================== 列表 / 字典 ====================
@router.get("")
def list_cards(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    zt: str = "",
    bmid: Optional[int] = None,
    chellx: str = "",
    chelyt: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    q = svc.filtered_cards_query(db, current, keyword=keyword, zt=zt, bmid=bmid,
                                 chellx=chellx, chelyt=chelyt)
    total = q.count()
    # 照旧 OilCardService 按 (备付金+余额) 升序,低余额卡排在前面
    balance_expr = func.coalesce(OilCard.bfj, 0) + func.coalesce(OilCard.ye, 0)
    cards = (q.order_by(balance_expr.asc(), OilCard.id.asc())
             .offset(max(page - 1, 0) * size).limit(size).all())
    all_ids = [r[0] for r in q.with_entities(OilCard.id).all()]
    return {
        "total": total,
        "items": svc.build_card_rows(db, cards, start=max(page - 1, 0) * size + 1),
        "footer": svc.footer_stats(db, all_ids),
    }


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]

    cars_q = db.query(ClChe).filter(ClChe.delf != 0)
    if scope is not None:
        cars_q = cars_q.filter(ClChe.bmid.in_(scope))
    cars = [{"id": c.id, "chehao": c.chehao or "", "bumen": c.bm or ""}
            for c in cars_q.order_by(ClChe.chehao).all()]

    lx_used = [r[0] for r in db.query(ClChe.lx).filter(ClChe.lx != "")
               .distinct().order_by(ClChe.lx).all()]
    yt_used = [r[0] for r in db.query(ClChe.yongtu).filter(ClChe.yongtu != "")
               .distinct().order_by(ClChe.yongtu).all()]
    y = date.today().year
    return {
        "status": svc.STATUS_OPTIONS, "oil": svc.OIL_OPTIONS,
        "departments": departments, "cars": cars,
        "lx": lx_used, "yongtu": yt_used,
        "years": list(range(y - 9, y + 2)), "current_year": y,
    }


# ==================== 模板 / 导出(静态路径须在 /{card_id} 前) ====================
@router.get("/template")
def download_template(
    type: str = "card",
    _user: User = Depends(require_permission("oilcard:view")),
):
    try:
        wb, filename = svc.build_template(type)
    except svc.ExcelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    buf = svc._save(wb)  # noqa: SLF001  同一模块内的保存工具
    return _excel_response(buf, filename)


@router.get("/export/balance")
def export_balance(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    return _excel_response(svc.build_balance_export(db, current), "油卡充值列表.xlsx")


@router.get("/export/diff")
def export_diff(
    type: str = "new",
    price: float = 8,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    mode = "old" if type == "old" else "new"
    amount = Decimal(str(price if price and price > 0 else 8))
    return _excel_response(svc.build_diff_export(db, current, mode, amount), "智能充值.xlsx")


@router.get("/export/manual")
def export_manual(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    return _excel_response(svc.build_manual_export(db, current), "油卡充值列表.xlsx")


@router.post("/manual-zero")
def manual_zero(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:manage")),
):
    cards = svc.filtered_cards_query(db, current).filter(OilCard.zt == "正常").all()
    for card in cards:
        card.handadd = 0
    db.commit()
    return {"message": "已清零", "count": len(cards)}


# ==================== Excel 导入 ====================
async def _import_file(file: UploadFile, handler, db: Session, user: User):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        rows = svc.first_sheet(data, file.filename or "")
        result = handler(db, rows, user)
    except svc.ExcelError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/upload/card")
async def upload_card(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:manage")),
):
    return await _import_file(file, svc.import_card_excel, db, current)


@router.post("/upload/balance")
async def upload_balance(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:manage")),
):
    return await _import_file(file, svc.import_balance_excel, db, current)


@router.post("/upload/transaction")
async def upload_transaction(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:manage")),
):
    return await _import_file(file, svc.import_transaction_excel, db, current)


# ==================== 单卡:明细 / 图表 / CRUD ====================
@router.get("/{card_id}/monthly-oil-data")
def monthly_oil_data(
    card_id: int,
    year: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    card = _get_card_or_404(db, card_id)
    _check_visible(db, card, current)
    y = year or date.today().year
    return svc.monthly_oil_data(db, card_id, y)


@router.get("/{card_id}/oil-month-stat")
def oil_month_stat(
    card_id: int,
    year: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    card = _get_card_or_404(db, card_id)
    _check_visible(db, card, current)
    y = year or date.today().year
    return svc.oil_month_stat(db, card, y)


@router.get("/{card_id}")
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    card = _get_card_or_404(db, card_id)
    _check_visible(db, card, current)
    return card.to_dict()


@router.post("")
def create_card(
    data: OilCardCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    kanum = (data.kanum or "").strip()
    if not kanum:
        raise HTTPException(status_code=400, detail="卡号不能为空")
    if db.query(OilCard).filter(OilCard.kanum == kanum).first():
        raise HTTPException(status_code=400, detail="重复卡号")
    _check_car_visible(db, data.carid, current)
    car = db.get(ClChe, data.carid) if data.carid else None
    now = datetime.now()
    card = OilCard(
        kanum=kanum,
        yanzhengma=(data.yanzhengma or "").strip(),
        carid=data.carid,
        youpin=data.youpin or (car.oil if car else ""),
        zt=data.zt or "正常",
        bz=(data.bz or "").strip(),
        bfj=0, ye=0, handadd=data.handadd or 0,
        djdate=now, editdate=now,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card.to_dict()


@router.put("/{card_id}")
def update_card(
    card_id: int,
    data: OilCardUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:view")),
):
    card = _get_card_or_404(db, card_id)
    _check_visible(db, card, current)
    fields = data.model_dump(exclude_unset=True)
    if "kanum" in fields:
        kanum = (fields["kanum"] or "").strip()
        if not kanum:
            raise HTTPException(status_code=400, detail="卡号不能为空")
        if db.query(OilCard).filter(OilCard.kanum == kanum, OilCard.id != card_id).first():
            raise HTTPException(status_code=400, detail="重复卡号")
        card.kanum = kanum
    if "carid" in fields:
        _check_car_visible(db, fields["carid"], current)
        card.carid = fields["carid"]
    for key in ("yanzhengma", "youpin", "zt", "bz"):
        if key in fields and fields[key] is not None:
            setattr(card, key, str(fields[key]).strip())
    if "handadd" in fields:
        card.handadd = fields["handadd"] or 0
    card.editdate = datetime.now()
    db.commit()
    return card.to_dict()


@router.delete("/{card_id}")
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("oilcard:manage")),
):
    card = _get_card_or_404(db, card_id)
    _check_visible(db, card, current)
    db.delete(card)
    db.commit()
    return {"message": "已删除"}
