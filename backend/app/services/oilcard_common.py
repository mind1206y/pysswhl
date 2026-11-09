"""油卡管理公共逻辑(照旧 OilCarManController / OilCardService / OilCardExcel / ViewOilCard 复刻)。

- 列表统计:上月/本月加油金额、近三月平均油量、年度派车次数/升数、最高月用量等
- 预警:按车辆用途阈值写入 yujing(导入油卡明细/余额记录时计算)
- 智能充值预测:historical 三个月 + 去年同期 + 同车型均值;导出充值/差额/手动充值表
- Excel 导入:油卡明细表、余额记录、消费(交易)明细,兼容 .xls(xlrd)/.xlsx(openpyxl)
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, OilCard, PlusOil, Yongcherc

STATUS_OPTIONS = ["正常", "停用", "注销"]
OIL_OPTIONS = ["92#", "0#", "95#", "其他"]

# 中国石化余额查询/台账对账单表头(照旧 OilCardExcel.cs,逐字一致)
CARD_HEADERS = ["卡号", "持卡人", "备付金资金账户", "卡资金账户", "备付金优惠账户", "优惠账户余额", "限车号"]
XF_HEADERS = [
    "卡号", "持卡人", "交易时间", "交易类型", "金额",
    "油品", "数量", "单价", "明折明扣", "优惠返利",
    "余额", "地点", "网点地址",
]

ZERO = Decimal("0")


# ==================== 通用小工具 ====================
def _d(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _f(value) -> float:
    return round(float(value or 0), 2)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").replace("￥", "").strip())
    except (InvalidOperation, ValueError):
        return ZERO


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


# ==================== 筛选 / 可见范围 ====================
def filtered_cards_query(db: Session, user, *, keyword: str = "", zt: str = "",
                         bmid: Optional[int] = None, chellx: str = "",
                         chelyt: str = ""):
    """旧库按登录部门 cj 前缀过滤,新系统换成 departments 子树作用域(与车辆模块一致)。"""
    q = db.query(OilCard).outerjoin(ClChe, ClChe.id == OilCard.carid)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(OilCard.kanum.like(like), OilCard.bz.like(like), ClChe.chehao.like(like)))
    if (zt or "").strip():
        q = q.filter(OilCard.zt == zt.strip())
    if bmid:
        q = q.filter(ClChe.bmid == bmid)
    if (chellx or "").strip():
        q = q.filter(ClChe.lx == chellx.strip())
    if (chelyt or "").strip():
        q = q.filter(ClChe.yongtu == chelyt.strip())
    return q


def card_visible(db: Session, card: OilCard, user) -> bool:
    scope = dept_scope_ids(db, user)
    if scope is None:
        return True
    if not card.carid:
        return False
    car = db.get(ClChe, card.carid)
    return bool(car and car.bmid in scope)


def warning_level(car: Optional[ClChe], bfj, ye) -> Optional[int]:
    """照旧 OilCardExcel 的余额预警阈值(取余额记录上传时较完整的口径)。"""
    if car is None:
        return None
    total = _dec(bfj) + _dec(ye)
    yt = car.yongtu or ""
    lx = car.lx or ""
    if yt == "110联动车" and total < 500:
        return 1
    if yt == "日常保障" and total < 500 and lx != "普通二轮摩托车":
        return 1
    if yt == "油卡" and total < 100:
        return 1
    if lx == "普通二轮摩托车" and total < 100 and total != 0:
        return 1
    return None


# ==================== 列表行统计(照旧 gettable) ====================
def build_card_rows(db: Session, cards: List[OilCard], now: Optional[datetime] = None,
                    start: int = 1) -> List[dict]:
    now = now or datetime.now()
    bennian = now.year
    byue = now.month
    yue = 12 if byue == 1 else byue - 1
    synian = bennian - 1 if byue == 1 else bennian
    first_this_month = _month_start(now.date())
    recent_start = _add_months(first_this_month, -3)

    car_ids = [c.carid for c in cards if c.carid]
    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_(car_ids)).all()} if car_ids else {}
    dept_names = dept_name_map(db)

    # 一次性取这些卡的加油记录,避免逐卡往返
    from collections import defaultdict

    recs = defaultdict(list)
    if cards:
        for r in db.query(PlusOil).filter(PlusOil.kaid.in_([c.id for c in cards])).all():
            recs[r.kaid].append(r)

    # 年度派车次数批量统计
    use_counts = {}
    if car_ids:
        use_counts = {cid: int(n) for cid, n in (
            db.query(Yongcherc.cheid, func.count())
            .filter(Yongcherc.cheid.in_(car_ids),
                    Yongcherc.ksdate >= datetime(bennian, 1, 1),
                    Yongcherc.ksdate < datetime(bennian + 1, 1, 1))
            .group_by(Yongcherc.cheid).all()
        )}

    rows = []
    for idx, card in enumerate(cards, start=start):
        car = cars.get(card.carid) if card.carid else None
        items = recs.get(card.id, [])

        last_add = max((r.ptime for r in items if r.ptime), default=None)
        shangyue = sum((_dec(r.jine) for r in items
                        if r.ptime and r.ptime.year == synian and r.ptime.month == yue), ZERO)
        benyue = sum((_dec(r.jine) for r in items
                      if r.ptime and r.ptime.year == bennian and r.ptime.month == byue), ZERO)

        monthly = defaultdict(Decimal)
        for r in items:
            if r.ptime and r.oill is not None and r.ptime.year in (bennian, bennian - 1):
                monthly[(r.ptime.year, r.ptime.month)] += _dec(r.oill)
        max_monthly = max(monthly.values(), default=ZERO)

        nian_oil = sum((_dec(r.oill) for r in items
                        if r.ptime and r.ptime.year == bennian), ZERO)
        last3 = sum((_dec(r.oill) for r in items
                     if r.ptime and recent_start <= r.ptime.date() < first_this_month), ZERO)
        avg3 = (last3 / Decimal("3")).quantize(Decimal("0.1")) if last3 else ZERO

        bfj = _dec(card.bfj)
        ye = _dec(card.ye)
        zh = bfj + ye
        rows.append({
            "xuhao": idx,
            "ID": card.id,
            "id": card.id,
            "kanum": card.kanum or "",
            "djdate": _dt(card.djdate),
            "editdate": _dt(card.editdate),
            "zt": card.zt or "",
            "chehao": (car.chehao if car and car.chehao else (card.chehao or "")),
            "paicheCount": use_counts.get(card.carid, 0) if card.carid else 0,
            "nianOilL": _f(nian_oil),
            "youpin": card.youpin or "",
            "bumen": dept_names.get(car.bmid) if car else "",
            "cyt": car.yongtu if car else "",
            "clx": car.lx if car else "",
            "ye": _f(ye),
            "handadd": _f(card.handadd),
            "yujing": card.yujing or 0,
            "bfj": _f(bfj),
            "zh": _f(zh),
            "shangyueOil": _f(shangyue),
            "lastAddOilDate": _dt(last_add),
            "benyueOil": _f(benyue),
            "bz": card.bz or "",
            "ce": _f(bfj + ye + benyue - shangyue),
            "maxMonthlyOil": _f(max_monthly),
            "avgLast3MonthsOil": _f(avg3),
            "carid": card.carid,
        })
    return rows


def footer_stats(db: Session, card_ids: List[int], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    bennian = now.year
    byue = now.month
    yue = 12 if byue == 1 else byue - 1
    synian = bennian - 1 if byue == 1 else bennian
    if not card_ids:
        return {"cyt": "合计", "zh": 0.0, "bfj": 0.0, "ye": 0.0,
                "benyueOil": 0.0, "shangyueOil": 0.0, "ce": 0.0}
    sum_bfj, sum_ye = db.query(
        func.coalesce(func.sum(OilCard.bfj), 0), func.coalesce(func.sum(OilCard.ye), 0)
    ).filter(OilCard.id.in_(card_ids)).one()
    sum_benyue = db.query(func.coalesce(func.sum(PlusOil.jine), 0)).filter(
        PlusOil.kaid.in_(card_ids), PlusOil.ptime >= datetime(bennian, byue, 1),
        PlusOil.ptime < _add_months(datetime(bennian, byue, 1), 1),
    ).scalar() or 0
    sum_shangyue = db.query(func.coalesce(func.sum(PlusOil.jine), 0)).filter(
        PlusOil.kaid.in_(card_ids), PlusOil.ptime >= datetime(synian, yue, 1),
        PlusOil.ptime < _add_months(datetime(synian, yue, 1), 1),
    ).scalar() or 0
    bfj, ye = _dec(sum_bfj), _dec(sum_ye)
    bj, sj = _dec(sum_benyue), _dec(sum_shangyue)
    return {
        "cyt": "合计", "zh": _f(bfj + ye), "bfj": _f(bfj), "ye": _f(ye),
        "benyueOil": _f(bj), "shangyueOil": _f(sj),
        "ce": _f(bfj + ye + bj - sj),
    }


# ==================== 智能充值预测(照旧 DownExcelce 系列) ====================
def _no_fuel_last3m(db: Session, car_id: int, now: datetime) -> bool:
    if not car_id:
        return True
    exists = db.query(PlusOil.id).filter(
        PlusOil.cheid == car_id,
        PlusOil.ptime.isnot(None),
        PlusOil.ptime >= now - timedelta(days=90),
        or_(PlusOil.oill > 0, PlusOil.jine > 0),
    ).first()
    return exists is None


def _predict_liters(db: Session, car_id: int, now: datetime) -> Decimal:
    """前三个完整自然月平均 + 去年同期月用量,两者取平均(照旧 GetPredictOilLiters)。"""
    first_this = _month_start(now.date())
    start_recent = _add_months(first_this, -3)
    totals = [
        _dec(v) for (v,) in (
            db.query(func.sum(PlusOil.oill))
            .filter(PlusOil.cheid == car_id, PlusOil.ptime >= start_recent,
                    PlusOil.ptime < first_this)
            .group_by(func.year(PlusOil.ptime), func.month(PlusOil.ptime)).all()
        )
    ]
    avg_recent = (sum(totals, ZERO) / Decimal(len(totals))) if totals else ZERO

    same_start = date(now.year - 1, now.month, 1)
    same_end = _add_months(same_start, 1)
    last_year = db.query(func.coalesce(func.sum(PlusOil.oill), 0)).filter(
        PlusOil.cheid == car_id, PlusOil.ptime >= same_start, PlusOil.ptime < same_end,
    ).scalar() or 0
    last_year = _dec(last_year)

    if last_year > 0 and avg_recent > 0:
        return (avg_recent + last_year) / 2
    if last_year > 0:
        return last_year
    return avg_recent


def _avg_liters_by_type(db: Session, car_type: str, now: datetime) -> Decimal:
    """同车型前三个完整自然月的平均月油耗(照旧 GetAvgLitersByCarType)。"""
    if not car_type:
        return ZERO
    first_this = _month_start(now.date())
    start = _add_months(first_this, -3)
    per_car_month = (
        db.query(PlusOil.cheid, func.sum(PlusOil.oill))
        .join(ClChe, ClChe.id == PlusOil.cheid)
        .filter(ClChe.lx == car_type, PlusOil.ptime >= start, PlusOil.ptime < first_this)
        .group_by(PlusOil.cheid, func.year(PlusOil.ptime), func.month(PlusOil.ptime)).all()
    )
    per_car = {}
    for cid, total in per_car_month:
        per_car.setdefault(cid, []).append(_dec(total))
    avgs = [sum(v, ZERO) / Decimal(len(v)) for v in per_car.values() if v]
    if not avgs:
        return ZERO
    return sum(avgs, ZERO) / Decimal(len(avgs))


def _is_low_usage(db: Session, car_id: int, now: datetime) -> bool:
    start = now - timedelta(days=90)
    vals = [
        _dec(v) for (v,) in (
            db.query(func.sum(PlusOil.jine))
            .filter(PlusOil.cheid == car_id, PlusOil.ptime >= start)
            .group_by(func.year(PlusOil.ptime), func.month(PlusOil.ptime)).all()
        )
    ]
    if not vals:
        return True
    return (sum(vals, ZERO) / Decimal(len(vals))) < 100


def _final_predict_amount(db: Session, car: Optional[ClChe], price: Decimal,
                          now: datetime) -> Decimal:
    if car is None:
        return Decimal("120") * price
    liters = ZERO
    is_new = bool(car.chuchang) and (now.date() - car.chuchang).days <= 180
    low_usage = _is_low_usage(db, car.id, now)
    if not is_new and not low_usage:
        liters = _predict_liters(db, car.id, now)
        if liters < 30:
            type_avg = _avg_liters_by_type(db, car.lx, now)
            if type_avg > 50:
                liters = type_avg
    else:
        liters = _avg_liters_by_type(db, car.lx, now)
    if liters == 0:
        liters = Decimal("120")
    return liters * price


def _last_month_total(db: Session, car_id: int, now: datetime) -> Decimal:
    first_this = _month_start(now.date())
    first_last = _add_months(first_this, -1)
    return _dec(db.query(func.coalesce(func.sum(PlusOil.jine), 0)).filter(
        PlusOil.cheid == car_id, PlusOil.ptime >= first_last, PlusOil.ptime < first_this,
    ).scalar())


def _used_this_month(db: Session, car_id: int, now: datetime) -> Decimal:
    first_this = _month_start(now.date())
    return _dec(db.query(func.coalesce(func.sum(PlusOil.jine), 0)).filter(
        PlusOil.cheid == car_id, PlusOil.ptime >= first_this,
        PlusOil.ptime < _add_months(first_this, 1),
    ).scalar())


def _calculate_recharge(predict: Decimal, balance: Decimal, price: Decimal,
                        car_type: str) -> Decimal:
    min_fuel = Decimal("50") * price
    if balance < min_fuel and "摩托车" not in (car_type or "") and "发电机" not in (car_type or ""):
        return (min_fuel - balance).quantize(Decimal("0.01"))
    need = predict - balance
    if need <= 0:
        return ZERO
    return need.quantize(Decimal("0.01"))


def calculate_card_recharge(db: Session, card: OilCard, car: Optional[ClChe],
                            price: Decimal, now: Optional[datetime] = None):
    """返回 (预测金额, 建议充值金额, 计算说明)。连续三个月无加油记录则不充值。"""
    now = now or datetime.now()
    balance = _dec(card.bfj) + _dec(card.ye)
    if car is None or _no_fuel_last3m(db, car.id, now):
        return ZERO, ZERO, "连续三个月无加油记录，不触发充值"

    predicted = _final_predict_amount(db, car, price, now)
    need = _calculate_recharge(predicted, balance, price, car.lx)
    reason = "正常触发充值" if need > 0 else "余额已覆盖预测"

    last_month = _last_month_total(db, car.id, now)
    if last_month > 0:
        available = balance + need + _used_this_month(db, car.id, now)
        if available < last_month:
            extra = (last_month - available).quantize(Decimal("0.01"))
            need = (need + extra).quantize(Decimal("0.01"))
            reason += f"; 约束补足{extra}元使总可用≥上月用量({last_month})"
        else:
            reason += f"; 满足上月用量约束({available} ≥ {last_month})"
    return predicted.quantize(Decimal("0.01")), need, reason


def top3_avg_month_amount(db: Session, car_id: Optional[int], price: Decimal,
                          now: Optional[datetime] = None) -> Decimal:
    """历史最高三个月用量平均 * 油价(对照旧 GetTop3AvgMonthAmount)。

    旧系统取 tboil 表,新系统统一用 PlusOil 的加油升数(同源,免依赖未迁移的 tboil)。
    """
    if not car_id:
        return ZERO
    now = now or datetime.now()
    monthly = [
        _dec(v) for (v,) in (
            db.query(func.sum(PlusOil.oill))
            .filter(PlusOil.cheid == car_id, PlusOil.ptime.isnot(None),
                    func.year(PlusOil.ptime).in_([now.year - 1, now.year]))
            .group_by(func.year(PlusOil.ptime), func.month(PlusOil.ptime)).all()
        )
    ]
    if not monthly:
        return ZERO
    top3 = sorted(monthly, reverse=True)[:3]
    return (sum(top3, ZERO) / Decimal(len(top3)) * price).quantize(Decimal("0.01"))


# ==================== 月度统计 ====================
def monthly_oil_data(db: Session, card_id: int, year: int) -> List[dict]:
    grouped = {
        int(m): {"amount": _f(j), "volume": _f(o)} for m, j, o in (
            db.query(func.month(PlusOil.ptime), func.sum(PlusOil.jine), func.sum(PlusOil.oill))
            .filter(PlusOil.kaid == card_id, PlusOil.ptime.isnot(None),
                    func.year(PlusOil.ptime) == year)
            .group_by(func.month(PlusOil.ptime)).all()
        )
    }
    return [{"month": m,
             "amount": grouped.get(m, {}).get("amount", 0.0),
             "volume": grouped.get(m, {}).get("volume", 0.0)} for m in range(1, 13)]


def oil_month_stat(db: Session, card: OilCard, year: int, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    grouped = {
        int(m): {"oil": _f(o), "amount": _f(j)} for m, o, j in (
            db.query(func.month(PlusOil.ptime), func.sum(PlusOil.oill), func.sum(PlusOil.jine))
            .filter(PlusOil.kaid == card.id, PlusOil.ptime >= start, PlusOil.ptime < end)
            .group_by(func.month(PlusOil.ptime)).all()
        )
    }
    use_month = {}
    if card.carid:
        use_month = {int(m): int(n) for m, n in (
            db.query(func.month(Yongcherc.ksdate), func.count())
            .filter(Yongcherc.cheid == card.carid, Yongcherc.ksdate >= start,
                    Yongcherc.ksdate < end)
            .group_by(func.month(Yongcherc.ksdate)).all()
        )}
    max_month = 0 if year > now.year else (now.month if year == now.year else 12)
    months = [{
        "month": m,
        "oil": grouped.get(m, {}).get("oil", 0.0),
        "amount": grouped.get(m, {}).get("amount", 0.0),
        "useCount": use_month.get(m, 0),
    } for m in range(1, max_month + 1)]
    return {
        "year": year, "months": months,
        "total_oil": _f(sum(m["oil"] for m in months)),
        "total_amount": _f(sum(m["amount"] for m in months)),
        "total_use_count": sum(m["useCount"] for m in months),
    }


# ==================== Excel 读取 / 导入 ====================
class ExcelError(Exception):
    """面向用户的导入错误。"""


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v).strip()


def _cell(row, idx):
    return row[idx] if idx < len(row) else None


def _to_datetime(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def read_sheets(data: bytes, filename: str) -> dict:
    from pathlib import Path

    ext = Path(filename or "").suffix.lower()
    if ext not in (".xls", ".xlsx"):
        raise ExcelError("只支持 .xls / .xlsx 文件")
    out = {}
    if ext == ".xls":
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as e:  # noqa: BLE001
            raise ExcelError(f"Excel 文件无法读取:{e}")
        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                line = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            line.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                        except Exception:  # noqa: BLE001
                            line.append(cell.value)
                    else:
                        line.append(cell.value)
                rows.append(line)
            out[sh.name] = rows
    else:
        from openpyxl import load_workbook

        try:
            book = load_workbook(BytesIO(data), data_only=True, read_only=True)
        except Exception as e:  # noqa: BLE001
            raise ExcelError(f"Excel 文件无法读取:{e}")
        for sh in book.worksheets:
            out[sh.title] = [list(r) for r in sh.iter_rows(values_only=True)]
        book.close()
    return out


def first_sheet(data: bytes, filename: str) -> List[list]:
    sheets = read_sheets(data, filename)
    if not sheets:
        raise ExcelError("Excel 没有工作表")
    return next(iter(sheets.values()))


def check_headers(rows: List[list], row_index: int, expected: List[str]) -> bool:
    if len(rows) <= row_index:
        return False
    return all(_text(_cell(rows[row_index], i)) == name for i, name in enumerate(expected))


def _find_car(db: Session, chehao: str) -> Optional[ClChe]:
    chehao = (chehao or "").strip()
    if not chehao:
        return None
    return db.query(ClChe).filter(ClChe.chehao == chehao, ClChe.delf != 0).first()


def import_card_excel(db: Session, rows: List[list], user) -> dict:
    """油卡明细表:新增卡号;已存在只补车辆关联(照旧 exeExcel)。"""
    if not check_headers(rows, 1, CARD_HEADERS):
        raise ExcelError("表格表头与油卡明细表模板不符,请核对是否选错文件(可点「下载模板」核对格式)")
    scope = dept_scope_ids(db, user)
    now = datetime.now()
    imported = updated = skipped = 0
    for row in rows[2:]:
        kanum = _text(_cell(row, 0))
        if not kanum:
            break
        chehao = _text(_cell(row, 6))
        bfj = _dec(_cell(row, 2))
        ye = _dec(_cell(row, 3))
        car = _find_car(db, chehao)
        existing = db.query(OilCard).filter(OilCard.kanum == kanum).first()
        if existing:
            if scope is not None and not (car and car.bmid in scope):
                skipped += 1
                continue
            if car:
                existing.carid = car.id
            updated += 1
            continue
        if scope is not None and (car is None or car.bmid not in scope):
            skipped += 1
            continue
        db.add(OilCard(
            kanum=kanum, chehao=chehao, bfj=bfj, ye=ye,
            carid=car.id if car else None, youpin=(car.oil if car else None),
            zt="正常", yujing=warning_level(car, bfj, ye),
            djdate=now, editdate=now,
        ))
        imported += 1
    db.commit()
    return {"imported": imported, "updated": updated, "skipped": skipped}


def import_balance_excel(db: Session, rows: List[list], user) -> dict:
    """余额记录:按卡号更新备付金/余额并重算预警(照旧 exeExcelye)。"""
    if not check_headers(rows, 1, CARD_HEADERS):
        raise ExcelError("表格表头与余额记录模板不符,请核对是否选错文件(可点「下载模板」核对格式)")
    scope = dept_scope_ids(db, user)
    updated = skipped = 0
    for row in rows[2:]:
        kanum = _text(_cell(row, 0))
        if not kanum:
            break
        card = db.query(OilCard).filter(OilCard.kanum == kanum).first()
        if card is None or (scope is not None and not _car_in_scope(db, card, scope)):
            skipped += 1
            continue
        card.bfj = _dec(_cell(row, 2))
        card.ye = _dec(_cell(row, 3))
        car = db.get(ClChe, card.carid) if card.carid else None
        card.yujing = warning_level(car, card.bfj, card.ye)
        card.editdate = datetime.now()
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


def import_transaction_excel(db: Session, rows: List[list], user) -> dict:
    """消费明细:写入 PlusOil(按 ptime+kaid 去重;照旧 exeExcelxf)。"""
    if not check_headers(rows, 3, XF_HEADERS):
        raise ExcelError("表格表头与消费明细模板不符,请核对是否选错文件(可点「下载模板」核对格式)")
    scope = dept_scope_ids(db, user)
    imported = skipped = 0
    now = datetime.now()
    for row in rows[4:]:
        if _text(_cell(row, 3)) != "消费":
            continue
        kanum = _text(_cell(row, 0))
        ptime = _to_datetime(_cell(row, 2))
        if not kanum or ptime is None:
            skipped += 1
            continue
        card = db.query(OilCard).filter(OilCard.kanum == kanum).first()
        if card is None or (scope is not None and not _car_in_scope(db, card, scope)):
            skipped += 1
            continue
        exists = db.query(PlusOil.id).filter(
            PlusOil.kaid == card.id, PlusOil.ptime == ptime,
        ).first()
        if exists:
            skipped += 1
            continue
        car = db.get(ClChe, card.carid) if card.carid else None
        db.add(PlusOil(
            ptime=ptime, kaid=card.id, cheid=car.id if car else None,
            bmid=car.bmid if car else None, lei=car.oil if car else "",
            oill=_dec(_cell(row, 6)), jine=_dec(_cell(row, 4)),
            leibie=_text(_cell(row, 5)), didian=_text(_cell(row, 11)),
            addtime=now,
        ))
        imported += 1
    db.commit()
    return {"imported": imported, "skipped": skipped}


def _car_in_scope(db: Session, card: OilCard, scope: set) -> bool:
    if not card.carid:
        return False
    car = db.get(ClChe, card.carid)
    return bool(car and car.bmid in scope)


# ==================== Excel 生成 ====================
def _new_workbook(title: str = "油卡充值列表"):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "油卡充值列表"
    return wb, ws


def _write_header(ws, headers: List[str]):
    fill = PatternFill("solid", fgColor="eef2f7")
    for i, name in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _autosize(ws, widths: List[int]):
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def build_template(kind: str):
    """下载上传模板:card=油卡明细表 / yue=余额记录 / xf=消费明细。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    if kind in ("card", "yue"):
        ws.cell(row=1, column=1, value="中国石化加油IC卡余额查询")
        for i, name in enumerate(CARD_HEADERS, start=1):
            cell = ws.cell(row=2, column=i, value=name)
            cell.font = Font(bold=True)
        _autosize(ws, [24, 12, 18, 18, 18, 18, 16])
        filename = "油卡明细表模板.xlsx" if kind == "card" else "余额记录模板.xlsx"
        return wb, filename
    if kind == "xf":
        ws.cell(row=1, column=1, value="中国石化加油IC卡台账对账单")
        ws.cell(row=2, column=1, value="客户卡号")
        ws.cell(row=2, column=4, value="开户省份")
        ws.cell(row=2, column=5, value="福建省")
        ws.cell(row=2, column=6, value="主/副卡")
        ws.cell(row=2, column=7, value="主卡")
        ws.cell(row=2, column=8, value="账户类型")
        ws.cell(row=2, column=9, value="全部")
        ws.cell(row=3, column=1, value="客户名称")
        ws.cell(row=3, column=4, value="客户编码")
        for i, name in enumerate(XF_HEADERS, start=1):
            cell = ws.cell(row=4, column=i, value=name)
            cell.font = Font(bold=True)
        _autosize(ws, [24, 12, 20, 10, 12, 10, 10, 10, 10, 10, 12, 20, 20])
        return wb, "消费明细模板.xlsx"
    raise ExcelError("未知模板类型")


def _sheet_name_for(user) -> str:
    depts = getattr(user, "departments", None) or []
    if depts and depts[0].name == "售水事业部":
        return "1000113500009380321"
    return "油卡充值列表"


def _cards_with_cars(db: Session, user, *, normal_only: bool = True) -> List[tuple]:
    q = filtered_cards_query(db, user)
    if normal_only:
        q = q.filter(OilCard.zt == "正常")
    cards = q.all()
    car_ids = [c.carid for c in cards if c.carid]
    cars = {c.id: c for c in db.query(ClChe).filter(ClChe.id.in_(car_ids)).all()} if car_ids else {}
    return [(card, cars.get(card.carid) if card.carid else None) for card in cards]


def build_balance_export(db: Session, user) -> BytesIO:
    """补充到定额:按车辆用途计算分配金额(照旧 loadAllsim)。"""
    wb, ws = _new_workbook(_sheet_name_for(user))
    _write_header(ws, ["校验码", "副卡", "车牌号", "持卡人", "分配金额", "分配积分"])
    for row, (card, car) in enumerate(_cards_with_cars(db, user), start=2):
        ye = _dec(card.ye)
        yt = car.yongtu if car else ""
        lx = car.lx if car else ""
        if yt == "110联动车":
            recharge = Decimal("2200") - ye
        elif yt == "日常保障" and lx != "普通二轮摩托车":
            recharge = Decimal("1200") - ye
        else:
            recharge = Decimal("300") - ye
        ws.cell(row=row, column=1, value=card.yanzhengma or "")
        ws.cell(row=row, column=2, value=card.kanum or "")
        ws.cell(row=row, column=3, value=car.chehao if car else "")
        ws.cell(row=row, column=4, value=user.username)
        ws.cell(row=row, column=5, value=float(recharge))
    _autosize(ws, [42, 24, 14, 14, 14, 14])
    return _save(wb)


def build_diff_export(db: Session, user, mode: str = "new", price: Decimal = Decimal("8")) -> BytesIO:
    """差额充值:new=智能预测,old=历史最高三个月平均差额(照旧 DownExcelce)。"""
    wb, ws = _new_workbook(_sheet_name_for(user))
    _write_header(ws, ["校验码", "副卡", "车牌号", "持卡人", "分配金额", "分配积分"])
    now = datetime.now()
    row = 2
    for card, car in _cards_with_cars(db, user):
        if mode == "new":
            _predicted, recharge, _reason = calculate_card_recharge(db, card, car, price, now)
        else:
            target = top3_avg_month_amount(db, card.carid, Decimal("8"), now)
            recharge = target - (_dec(card.bfj) + _dec(card.ye))
            recharge = recharge if recharge > 0 else ZERO
        if recharge == 0:
            continue
        ws.cell(row=row, column=1, value=card.yanzhengma or "")
        ws.cell(row=row, column=2, value=card.kanum or "")
        ws.cell(row=row, column=3, value=car.chehao if car else "")
        ws.cell(row=row, column=4, value=user.username)
        ws.cell(row=row, column=5, value=float(recharge))
        row += 1
    _autosize(ws, [42, 24, 14, 14, 14, 14])
    return _save(wb)


def build_manual_export(db: Session, user) -> BytesIO:
    """导出手动充值表(照旧 loadOilsd),分配金额 = handadd。"""
    wb, ws = _new_workbook(_sheet_name_for(user))
    _write_header(ws, ["校验码", "副卡", "车牌号", "持卡人", "分配金额", "分配积分"])
    for row, (card, car) in enumerate(_cards_with_cars(db, user), start=2):
        ws.cell(row=row, column=1, value=card.yanzhengma or "")
        ws.cell(row=row, column=2, value=card.kanum or "")
        ws.cell(row=row, column=3, value=car.chehao if car else "")
        ws.cell(row=row, column=4, value=user.username)
        ws.cell(row=row, column=5, value=float(_dec(card.handadd)))
    _autosize(ws, [42, 24, 14, 14, 14, 14])
    return _save(wb)


def _save(wb) -> BytesIO:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
