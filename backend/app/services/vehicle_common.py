"""车辆管理公共逻辑:字典、年检周期、筛选、年度统计(照旧 cheliangguanliController/chelService/CarNianJian)。"""

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, ClChetupian, ClChuxian, ClWxdan, PlusOil, Yongcherc

# ===== 旧系统字典(逐字取自 cheliangguanliController.Index) =====
LX_OPTIONS = [
    "小型轿车", "小型普通客车", "轻型栏板货车", "重型栏板货车", "轻型厢式货车",
    "轻型多用途货车", "轻型普通货车", "中型普通货车", "中型厢式货车", "中型普通客车",
    "大型普通客车", "其他特种车", "轻型非载货专项作业车", "重型非载货专项作业车",
    "柴油发电机", "汽油发电机", "柴、汽油发电机", "普通二轮摩托车", "三轮摩托车",
]
YONGTU_OPTIONS = ["日常保障", "油卡", "110联动车", "抄表用车", "运输", "特殊保障"]
OIL_OPTIONS = ["92#", "0#", "95#", "其他"]
ZEREN_OPTIONS = ["全部责任", "主要责任", "次要责任", "其他"]
STATUS_OPTIONS = [{"value": 1, "label": "正常"}, {"value": 2, "label": "报废"}]
REMINDER_LABELS = {0: "未提醒", 1: "90天提醒", 2: "30天提醒", 3: "7天紧急提醒", 4: "已过期"}

# 编辑/新增允许写入的字段(照旧 Addcl/Editcl 的白名单,审批字段由后端控制)
EDITABLE_FIELDS = [
    "lx", "jiashiyuan", "telphone", "chehao", "pingshi", "zhoumo", "yongtu",
    "oil", "oilcard", "jsz", "etc", "danganhao", "syxingzhi", "fadongjihao",
    "chejiahao", "pailiang", "pinpai", "xinghao",
]
DATE_FIELDS = ["chuchang", "grriqi"]
NUMBER_FIELDS = ["jiage", "zws"]

KEYWORD_FIELDS = [
    "chehao", "jiashiyuan", "oilcard", "lx", "yongtu", "telphone", "pinpai",
    "pingshi", "fadongjihao", "chejiahao", "danganhao", "syxingzhi",
]


# ===== 年检周期(照旧 VehicleInspectionHelper / CarNianJian) =====
def _add_months_safe(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _vehicle_age(register: date, ref: date) -> int:
    age = ref.year - register.year
    try:
        anniversary = register.replace(year=register.year + age)
    except ValueError:  # 2 月 29 日
        anniversary = date(register.year + age, 2, 28)
    if ref < anniversary:
        age -= 1
    return age


def _cycle_months(vehicle_type: str, register: date, base: date) -> int:
    age = _vehicle_age(register, base)
    if "摩托" in (vehicle_type or ""):
        return 12 if age >= 4 else 24
    if "货" in (vehicle_type or ""):
        return 6 if age >= 10 else 12
    return 12 if age >= 10 else 24


def inspection_dates(register: date, vehicle_type: str, today: Optional[date] = None):
    """返回 (上一个, 下一个, 下下一个) 年检日,照旧 GetInspectionDates 逐年累加周期。"""
    today = today or date.today()
    base = register
    guard = 0
    while guard < 200:
        guard += 1
        months = _cycle_months(vehicle_type, register, base)
        nxt = _add_months_safe(base, months)
        if nxt > today:
            return base, nxt, _add_months_safe(nxt, months)
        base = nxt
    return base, base, base


def refresh_inspection_cycle(che: ClChe):
    """登记信息变更后重算下次年检日(照旧 RefreshInspectionCycle)。"""
    if che.chuchang:
        _prev, nxt, _nn = inspection_dates(che.chuchang, che.lx)
        che.NextInspectionDate = nxt
    else:
        che.NextInspectionDate = None
    che.ReminderLevel = 0
    che.LastReminderDate = None


def correct_next_inspection(che: ClChe, action: str) -> Optional[date]:
    """照旧 CalculateCorrectNextInspectionDate。"""
    if not che.chuchang:
        return che.NextInspectionDate
    prev, nxt, nn = inspection_dates(che.chuchang, che.lx)
    days = (nxt - date.today()).days
    if action == "撤销年检":
        return prev if days > 90 else nxt
    if action == "标注年检":
        # 旧 MarkAsInspected 先把 ReminderLevel 置 0,故不会命中 level==4 分支
        return nxt if days > 90 else nn
    if action == "检查过期":
        return prev if che.ReminderLevel == 4 else nxt
    return nxt


def reminder_view(che: ClChe) -> dict:
    """列表「年检剩余天数」进度条口径(照旧 Index.cshtml formatter)。"""
    if not che.NextInspectionDate:
        return {"remaining_days": None, "reminder_percent": 0, "reminder_color": "#909399",
                "reminder_text": "-"}
    days = (che.NextInspectionDate - date.today()).days
    clamped = max(0, min(days, 90))
    percent = round(clamped / 90 * 100, 1)
    if days <= 7:
        color = "#FF5722"
    elif days <= 30:
        color = "#FFC107"
    elif days <= 90:
        color = "#8BC34A"
    else:
        color = "#4CAF50"
    if days > 0:
        text = f"{days}天"
    elif che.ReminderLevel == 4:
        text = f"已过期 {-days} 天"
        color = "#b3261e"
        percent = 100
    else:
        text = "已过期"
    return {"remaining_days": days, "reminder_percent": percent,
            "reminder_color": color, "reminder_text": text}


# ===== 筛选(照旧 chelService.LoadSearchEntities + 新系统部门作用域) =====
def filtered_query(
    db: Session, user, *, keyword: str = "", bmid: Optional[int] = None,
    chellx: str = "", chelyt: str = "", scrap: bool = False,
    nocd: bool = False, next_month: bool = False,
):
    q = db.query(ClChe).filter(ClChe.delf == (2 if scrap else 1))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(*[getattr(ClChe, f).like(like) for f in KEYWORD_FIELDS]))
    types = [s.strip() for s in (chellx or "").split(",") if s.strip()]
    if types:
        q = q.filter(ClChe.lx.in_(types))
    if (chelyt or "").strip():
        q = q.filter(ClChe.yongtu == chelyt.strip())
    if nocd:
        q = q.filter(ClChe.yongtu != "油卡")
    if next_month:
        month = date.today().month % 12 + 1
        q = q.filter(func.month(ClChe.chuchang) == month)
    if bmid:
        q = q.filter(ClChe.bmid == bmid)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    return q


# ===== 年度统计(旧系统用 N+1 导航属性,这里一次性聚合) =====
def year_stats(db: Session, year: int) -> Dict[int, dict]:
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    d5 = date(year - 4, 1, 1)
    end_date = date(year + 1, 1, 1)

    out: Dict[int, dict] = {}

    def slot(cid):
        return out.setdefault(cid, {
            "oilYear": 0.0, "useCountYear": 0, "wxCountYear": 0, "wxAmountYear": 0.0,
            "wx5Years": [], "jls": 0, "tps": [],
        })

    for cid, v in (
        db.query(PlusOil.cheid, func.sum(PlusOil.oill))
        .filter(PlusOil.ptime >= start, PlusOil.ptime < end, PlusOil.cheid.isnot(None))
        .group_by(PlusOil.cheid).all()
    ):
        slot(cid)["oilYear"] = round(float(v or 0), 2)

    for cid, n in (
        db.query(Yongcherc.cheid, func.count())
        .filter(Yongcherc.ksdate >= start, Yongcherc.ksdate < end, Yongcherc.cheid.isnot(None))
        .group_by(Yongcherc.cheid).all()
    ):
        slot(cid)["useCountYear"] = int(n)

    for cid, n, amt in (
        db.query(ClWxdan.cheid, func.count(), func.sum(ClWxdan.jine))
        .filter(ClWxdan.jcriqi >= date(year, 1, 1), ClWxdan.jcriqi < end_date,
                ClWxdan.cheid.isnot(None))
        .group_by(ClWxdan.cheid).all()
    ):
        s = slot(cid)
        s["wxCountYear"] = int(n)
        s["wxAmountYear"] = round(float(amt or 0), 2)

    five: Dict[int, dict] = {}
    for cid, y, n, amt in (
        db.query(ClWxdan.cheid, func.year(ClWxdan.jcriqi), func.count(), func.sum(ClWxdan.jine))
        .filter(ClWxdan.jcriqi >= d5, ClWxdan.jcriqi < end_date, ClWxdan.cheid.isnot(None))
        .group_by(ClWxdan.cheid, func.year(ClWxdan.jcriqi)).all()
    ):
        five.setdefault(cid, {})[int(y)] = {"year": int(y), "count": int(n),
                                            "amount": round(float(amt or 0), 2)}
    for cid, by_year in five.items():
        slot(cid)["wx5Years"] = [by_year.get(y) or {"year": y, "count": 0, "amount": 0.0}
                                 for y in range(year - 4, year + 1)]

    for cid, n in (
        db.query(ClChuxian.cheid, func.count()).filter(ClChuxian.cheid.isnot(None))
        .group_by(ClChuxian.cheid).all()
    ):
        slot(cid)["jls"] = int(n)

    for p in db.query(ClChetupian).all():
        if p.cheid is not None:
            slot(p.cheid)["tps"].append({"id": p.id, "url": p.url,
                                          "name": p.file_name or p.url.split("/")[-1]})
    return out


def build_rows(db: Session, cars: List[ClChe], year: int) -> List[dict]:
    """组装列表行:部门名 + 年度统计 + 年检倒计时(一次查完,避免 N+1)。"""
    names = dept_name_map(db)
    stats = year_stats(db, year)
    rows = []
    for che in cars:
        d = che.to_dict()
        d["bumen"] = names.get(che.bmid) or che.bm or ""
        d["zt"] = che.delf
        d["txjb"] = che.ReminderLevel
        d["ifnj"] = bool(che.IsInspected) if che.IsInspected is not None else None
        d.update(stats.get(che.id, {
            "oilYear": 0.0, "useCountYear": 0, "wxCountYear": 0, "wxAmountYear": 0.0,
            "wx5Years": [], "jls": 0, "tps": [],
        }))
        d.update(reminder_view(che))
        rows.append(d)
    return rows


# ===== Excel 导出(照旧 loadchelexcel.cs 25 列) =====
EXPORT_COLUMNS = [
    ("序号", None), ("部门", "bumen"), ("车号", "chehao"), ("品牌", "pinpai"),
    ("型号", "xinghao"), ("类型", "lx"), ("注册日期", "chuchang"),
    ("办公地点", "pingshi"), ("停放点", "zhoumo"), ("驾驶员", "jiashiyuan"),
    ("电话", "telphone"), ("用途", "yongtu"), ("油类", "oil"), ("油卡号", "oilcard"),
    ("驾照号", "jsz"), ("购入日期", "grriqi"), ("价格", "jiage"),
    ("ETC", "etc"), ("档案号", "danganhao"), ("使用性质", "syxingzhi"),
    ("座位数", "zws"), ("发动机号", "fadongjihao"), ("车架号", "chejiahao"),
    ("排量", "pailiang"), ("下次年检", "NextInspectionDate"),
]
