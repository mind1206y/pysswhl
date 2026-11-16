"""传导完好率分组 4 模块公共逻辑(照旧 CD*Controller / CD*Service 1:1 复刻)。

旧系统约定:
- 报表日期恒为每月 25 日(bbrq.bbdate),报表周期 = 上月26日~本月25日,
  天数 bbrq.ts = (本月26日 - 上月25日).Days - 1;列表不传日期时查本月 25 日。
- 部门数据权限 = 登录人部门 cj 前缀(本部门 + 子树),新系统用 dept_scope_ids。
- 锁定开关 consol_tb.conName='锁定传导报表'(旧 consolTb),锁定时 3 个明细页禁止增删改;
  完好率页的生成报表/编辑备注照旧不受锁定限制。
- 增删改限本人录入(username 中文姓名),删除限本月数据(往期不可删)。
- 列表返回 {items,total,bt};完好率另有 footer(照旧是**当前页**合计,不是全量合计)。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.cd import CDDaxiu, CDGz, CDWhl, CDXz, _d, _dt, _n
from app.models.plan import ConsolTb
from app.models.user import Department, User

LOCK_NAME = "锁定传导报表"

GUANCAI = [
    "PVC", "灰口铸铁", "镀锌", "钢管", "球墨铸铁", "PE", "砼管", "玻璃钢管",
    "PPR管", "塑钢管", "其他材质",
]
GUANJING = [
    "DN100", "DN200", "DN300", "DN400", "DN500", "DN600", "DN700", "DN800",
    "DN1000", "DN1100", "DN1200", "DN1400", "DN1600", "DN1800", "DN2000",
    "其他口径",
]
DAXIU_LB = ["报废更换"]
BD_LB = ["新增设备", "报废设备", "调出设备", "停用设备"]

# 旧「传导设备完好率月报表.xls」统计 sheet 的部门行顺序(照模板硬编码)
EXCEL_DEPT_ORDER = ["厦门营业所", "翔安营业所", "海沧营业所", "集美营业所", "同安营业所"]


# ==================== 报表日期 ====================
def report_date(rq: str = "") -> date:
    """rq 支持 'YYYY-MM'(前端月份选择器) / 'YYYY-MM-DD'(旧日期框) / 空(本月)。"""
    text = (rq or "").strip()
    if not text:
        today = date.today()
        return date(today.year, today.month, 25)
    try:
        parts = text[:10].split("-")
        return date(int(parts[0]), int(parts[1]), 25)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="报表日期格式不正确")


def report_month(rq: str = "") -> str:
    d = report_date(rq)
    return f"{d.year:04d}-{d.month:02d}"


def report_date_str(rq: str = "") -> str:
    return report_date(rq).isoformat()


def bt_title(rq: str = "") -> str:
    """旧 bbrq.Getbtdate: '2026年11月'(月不补零)。"""
    d = report_date(rq)
    return f"{d.year}年{d.month}月"


def period_days(d: date) -> int:
    """旧 bbrq.ts(dt):报表周期(上月26日~本月25日)天数。"""
    first = d.replace(day=1)
    prev_month_last = first - timedelta(days=1)
    start = date(prev_month_last.year, prev_month_last.month, 25)
    end = date(d.year, d.month, 26)
    return (end - start).days - 1


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式不正确")


# ==================== 权限 / 锁定 / 归属 ====================
def has_perm(user: User, code: str) -> bool:
    if user.is_superuser:
        return True
    return any(p.code == code for role in user.roles for p in role.permissions)


def display_name(user: User) -> str:
    """旧 username 存中文姓名;新系统优先 real_name。"""
    return (user.real_name or "").strip() or user.username


def is_locked(db: Session) -> bool:
    row = db.query(ConsolTb).filter(ConsolTb.conName == LOCK_NAME).first()
    if row is None:
        row = ConsolTb(conName=LOCK_NAME, val=False)
        db.add(row)
        db.commit()
        return False
    return bool(row.val)


def set_locked(db: Session, value: bool) -> bool:
    row = db.query(ConsolTb).filter(ConsolTb.conName == LOCK_NAME).first()
    if row is None:
        row = ConsolTb(conName=LOCK_NAME, val=value)
        db.add(row)
    else:
        row.val = value
    db.commit()
    return bool(row.val)


def ensure_not_locked(db: Session):
    if is_locked(db):
        raise HTTPException(status_code=400, detail="报表已锁定无法改动")


def ensure_owner(row, user: User, action: str = "修改"):
    """旧 Editgz/Deletegz:只能改自己录入的数据(超管亦同)。"""
    if (row.username or "") != display_name(user):
        raise HTTPException(status_code=403, detail=f"不能{action}非自己录入的数据！")


def ensure_current_month(row, message: str = "往期数据无法删除"):
    """旧 DateTime.Now.Month > bbdate.Month;新系统按年月比较,避免跨年误判。"""
    if row.bbdate is None:
        return
    now = date.today()
    if (now.year, now.month) > (row.bbdate.year, row.bbdate.month):
        raise HTTPException(status_code=400, detail=message)


def default_bmid(user: User):
    """新增明细的部门:取登录人第一个部门(照旧 bumen.id),超管无部门时置 NULL。"""
    return user.departments[0].id if user.departments else None


def dept_options(db: Session, user: User):
    """部门下拉(照旧 cj 前缀 = 本部门子树;超管看全部)。"""
    scope = dept_scope_ids(db, user)
    q = db.query(Department.id, Department.name)
    if scope is not None:
        q = q.filter(Department.id.in_(scope))
    rows = q.order_by(Department.id).all()
    return [{"id": i, "name": n or ""} for i, n in rows]


def dicts_data(db: Session, user: User) -> dict:
    d = report_date()
    return {
        "departments": dept_options(db, user),
        "guancai": GUANCAI,
        "guanjing": GUANJING,
        "daxiu_lb": DAXIU_LB,
        "bdlb": BD_LB,
        "report_month": f"{d.year:04d}-{d.month:02d}",
        "report_date": d.isoformat(),
        "bt": f"{d.year}年{d.month}月",
        "is_locked": is_locked(db),
        "can_lock": has_perm(user, "cdwhl:manage"),
    }


# ==================== 查询 / 序列化 ====================
def scoped_query(db: Session, user: User, model, rq: str = "", bmid=None,
                 keyword: str = "", keyword_cols=(), extra=None):
    """4 页共用的列表条件:报表日期 + 部门子树 + 部门下拉 + 模糊搜索。"""
    q = db.query(model).filter(model.bbdate == report_date(rq))
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(model.bmid.in_(scope))
    if bmid not in (None, "", 0, "0"):
        try:
            q = q.filter(model.bmid == int(bmid))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="部门参数不正确")
    kw = (keyword or "").strip()
    if kw and keyword_cols:
        q = q.filter(or_(*[col.like(f"%{kw}%") for col in keyword_cols]))
    if extra is not None:
        q = q.filter(extra)
    return q


def dept_names(db: Session) -> dict:
    return {d.id: d.name for d in db.query(Department).all()}


def whl_row(row: CDWhl, names: dict) -> dict:
    return {
        "id": row.id,
        "bumen": names.get(row.bmid, ""),
        "bmid": row.bmid,
        "bbdate": _d(row.bbdate),
        "ts": row.ts,
        "sytss": row.sytss,
        "decgztss": _n(row.decgztss),
        "decwhtss": _n(row.decwhtss),
        "whl": _n(row.whl),
        "xzts": row.xzts,
        "bfts": row.bfts,
        "dcts": row.dcts,
        "tyts": row.tyts,
        "bz": row.bz or "",
        "finadate": _dt(row.finadate),
        "adddate": _dt(row.adddate),
        "username": row.username or "",
    }


def gz_row(row: CDGz, names: dict) -> dict:
    return {
        "id": row.id,
        "bumen": names.get(row.bmid, ""),
        "bmid": row.bmid,
        "bbdate": _d(row.bbdate),
        "sbname": row.sbname or "",
        "guanjing": row.guanjing or "",
        "guancai": row.guancai or "",
        "didian": row.didian or "",
        "ksdate": _d(row.ksdate),
        "jsdate": _d(row.jsdate),
        "yy": row.yy or "",
        "dects": _n(row.dects),
        "bz": row.bz or "",
        "finadate": _dt(row.finadate),
        "adddate": _dt(row.adddate),
        "username": row.username or "",
    }


def daxiu_row(row: CDDaxiu, names: dict) -> dict:
    return {
        "id": row.id,
        "bumen": names.get(row.bmid, ""),
        "bmid": row.bmid,
        "bbdate": _d(row.bbdate),
        "daxiudate": _d(row.daxiudate),
        "lb": row.lb or "",
        "nr": row.nr or "",
        "gdh": row.gdh or "",
        "gdkj": row.gdkj or "",
        "xbqkj": row.xbqkj or "",
        "fmkj": row.fmkj or "",
        "xfskj": row.xfskj or "",
        "num": row.num,
        "bz": row.bz or "",
        "cfd": row.cfd or "",
        "sgy": row.sgy or "",
        "sgtel": row.sgtel or "",
        "finadate": _dt(row.finadate),
        "adddate": _dt(row.adddate),
        "username": row.username or "",
    }


def xz_row(row: CDXz, names: dict) -> dict:
    return {
        "id": row.id,
        "bumen": names.get(row.bmid, ""),
        "bmid": row.bmid,
        "bbdate": _d(row.bbdate),
        "bdlb": row.bdlb or "",
        "sbname": row.sbname or "",
        "adddate": _dt(row.adddate),
        "finadate": _dt(row.finadate),
        "username": row.username or "",
    }


def whl_footer(items: list) -> dict:
    """照旧 Getxz:footer 是**当前页** rows 的合计(不是筛选全量)。"""
    def total(key):
        return sum(float(i.get(key) or 0) for i in items)

    sytss = total("sytss")
    decwhtss = total("decwhtss")
    whl = round(decwhtss / sytss * 100, 2) if sytss and decwhtss else None
    return {
        "bz": "合计", "ts": total("ts"), "sytss": sytss,
        "decgztss": total("decgztss"), "decwhtss": decwhtss, "whl": whl,
        "xzts": total("xzts"), "bfts": total("bfts"),
        "dcts": total("dcts"), "tyts": total("tyts"),
    }


# ==================== 生成报表(旧 CDwhlService.tjbb) ====================
def generate_report(db: Session, user: User, rq: str = "") -> int:
    """按登录人部门子树生成当月完好率汇总;上月无报表的部门不生成。

    设备台数 = 上月台数 + 本月新增 - 报废 - 调出 - 停用;
    实有台时数 = 台数 × 报表周期天数 × 24;
    故障台时数 = 本月故障明细 dects 之和;
    完好台时数 = 实有台时数 - 故障台时数;完好率 = 完好/实有×100(2 位)。
    """
    rd = report_date(rq)
    first = rd.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=25)
    scope = dept_scope_ids(db, user)
    dept_q = db.query(Department.id)
    if scope is not None:
        dept_q = dept_q.filter(Department.id.in_(scope))
    dept_ids = [i for (i,) in dept_q.order_by(Department.id).all()]
    days = period_days(rd)
    now = datetime.now()
    uname = display_name(user)
    created = 0
    for bmid in dept_ids:
        prev_row = (
            db.query(CDWhl).filter(CDWhl.bmid == bmid, CDWhl.bbdate == prev).first()
        )
        if prev_row is None:
            continue
        # 同部门同月已有报表先删除,再重建(照旧 Add 前 DeleteEntity)
        for old in db.query(CDWhl).filter(
            CDWhl.bmid == bmid, CDWhl.bbdate == rd
        ).all():
            db.delete(old)
        db.flush()

        gz_ts = db.query(func.coalesce(func.sum(CDGz.dects), 0)).filter(
            CDGz.bmid == bmid, CDGz.bbdate == rd
        ).scalar() or Decimal("0")
        counts = dict(
            db.query(CDXz.bdlb, func.count(CDXz.id))
            .filter(CDXz.bmid == bmid, CDXz.bbdate == rd)
            .group_by(CDXz.bdlb).all()
        )
        add = counts.get("新增设备", 0)
        scrap = counts.get("报废设备", 0)
        out = counts.get("调出设备", 0)
        stop = counts.get("停用设备", 0)
        ts = int(prev_row.ts or 0) + add - scrap - out - stop
        sytss = ts * days * 24
        decgz = Decimal(str(gz_ts))
        decwh = Decimal(sytss) - decgz
        whl = round(float(decwh) / sytss * 100, 2) if sytss else 0
        db.add(CDWhl(
            bmid=bmid, ts=ts, sytss=sytss,
            decgztss=decgz, decwhtss=decwh, whl=whl,
            bbdate=rd, xzts=add, bfts=scrap, dcts=out, tyts=stop,
            adddate=now, finadate=now, username=uname,
        ))
        created += 1
    db.commit()
    return created
