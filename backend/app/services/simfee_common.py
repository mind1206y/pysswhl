"""通信费(旧 simFeiyongController 复刻)公共口径。

- 列表按年度/月份查询 feiyong,金额倒序、id 正序
- 部门权限:feiyong.bm 落在登录人部门子树内
- 关键字:卡号模糊,或卡号属于 SIM 卡(有效)地点/用途/备注/卡号命中
- 本人:feiyong.syren = 当前用户名(旧系统“只看本人”)
- 年度合计:同一卡号在所选年度的全部月份话费合计(跨部门,照旧 yearSum)
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.simcard import Feiyong, SimCard


def _money(v) -> float:
    if v is None:
        return 0.0
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def available_years(db: Session) -> list:
    return [
        int(r[0]) for r in db.query(Feiyong.nian)
        .filter(Feiyong.nian.isnot(None)).distinct()
        .order_by(Feiyong.nian.desc()).all()
    ]


def available_months(db: Session, year: int) -> list:
    return [
        int(r[0]) for r in db.query(Feiyong.yue)
        .filter(Feiyong.nian == year, Feiyong.yue.isnot(None)).distinct()
        .order_by(Feiyong.yue).all()
    ]


def default_period(db: Session) -> tuple:
    years = available_years(db)
    if years:
        year = years[0]
        months = available_months(db, year)
        return year, (months[-1] if months else date.today().month)
    return date.today().year, date.today().month


def base_query(db: Session, user, year: int, month: int, bmid: Optional[int] = None,
               keyword: str = "", only_self: bool = False, username: str = ""):
    q = db.query(Feiyong).filter(Feiyong.nian == year, Feiyong.yue == month)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(Feiyong.bm.in_(scope))
    if bmid:
        q = q.filter(Feiyong.bm == bmid)
    if only_self:
        q = q.filter(Feiyong.syren == username)
    kw = (keyword or "").strip()
    if kw:
        sim_kahaos = db.query(SimCard.kahao).filter(
            SimCard.delf == 1,
            or_(
                SimCard.kahao.contains(kw),
                SimCard.didian.contains(kw),
                SimCard.yongtu.contains(kw),
                SimCard.bz.contains(kw),
            ),
        )
        q = q.filter(or_(Feiyong.kahao.contains(kw), Feiyong.kahao.in_(sim_kahaos)))
    return q


def build_rows(db: Session, fees: list, year: int) -> list:
    if not fees:
        return []
    names = dept_name_map(db)
    kahaos = {f.kahao for f in fees if f.kahao}
    sims = (
        db.query(SimCard)
        .filter(SimCard.delf == 1, SimCard.kahao.in_(kahaos))
        .order_by(SimCard.id)
        .all()
    )
    sim_map = {}
    for s in sims:
        sim_map.setdefault(s.kahao, s)
    year_sum = {}
    if kahaos:
        for kahao, total in (
            db.query(Feiyong.kahao, func.coalesce(func.sum(Feiyong.jine), 0))
            .filter(Feiyong.nian == year, Feiyong.kahao.in_(kahaos))
            .group_by(Feiyong.kahao).all()
        ):
            year_sum[kahao] = _money(total)
    rows = []
    for f in fees:
        s = sim_map.get(f.kahao)
        rows.append({
            "id": f.id,
            "kahao": f.kahao or "",
            "jine": _money(f.jine),
            "nian": f.nian,
            "yue": f.yue,
            "syren": f.syren or "",
            "didian": (s.didian or "") if s else "",
            "yongtu": (s.yongtu or "") if s else "",
            "wangluo": (s.wangluo or "") if s else "",
            "zt": (s.zt or "") if s else "",
            "zhanghu": (s.zhanghu or "") if s else "",
            "bz": (s.bz or "") if s else "",
            "bm": (names.get(s.bm) or "") if s else "",
            "upbm": names.get(f.bm) or "",
            "huizongjine": year_sum.get(f.kahao, 0.0),
        })
    return rows


def empty_yongtu_rows(db: Session, user, year: int) -> list:
    """年度“用途为空”明细(照旧 ExportYongtuEmptyAllYear),每个卡号取首条。"""
    scope = dept_scope_ids(db, user)
    fq = db.query(Feiyong).filter(Feiyong.nian == year)
    if scope is not None:
        fq = fq.filter(Feiyong.bm.in_(scope))
    fees = fq.order_by(Feiyong.id).all()
    if not fees:
        return []
    kahaos = {f.kahao for f in fees if f.kahao}
    sq = db.query(SimCard).filter(SimCard.delf == 1, SimCard.kahao.in_(kahaos))
    if scope is not None:
        sq = sq.filter(SimCard.bm.in_(scope))
    sims = sq.order_by(SimCard.id).all()
    sim_map = {}
    for s in sims:
        sim_map.setdefault(s.kahao, s)
    empty = {
        f.kahao for f in fees
        if not (sim_map.get(f.kahao) and (sim_map[f.kahao].yongtu or "").strip())
    }
    if not empty:
        return []
    year_sum = {}
    for kahao, total in (
        db.query(Feiyong.kahao, func.coalesce(func.sum(Feiyong.jine), 0))
        .filter(Feiyong.nian == year, Feiyong.kahao.in_(empty))
        .group_by(Feiyong.kahao).all()
    ):
        year_sum[kahao] = _money(total)
    names = dept_name_map(db)
    seen = set()
    rows = []
    for f in fees:
        if f.kahao not in empty or f.kahao in seen:
            continue
        seen.add(f.kahao)
        s = sim_map.get(f.kahao)
        rows.append({
            "id": f.id,
            "kahao": f.kahao or "",
            "jine": _money(f.jine),
            "nian": f.nian,
            "yue": f.yue,
            "syren": f.syren or "",
            "didian": (s.didian or "") if s else "",
            "yongtu": (s.yongtu or "") if s else "",
            "wangluo": (s.wangluo or "") if s else "",
            "zt": (s.zt or "") if s else "",
            "zhanghu": (s.zhanghu or "") if s else "",
            "bz": (s.bz or "") if s else "",
            "bm": (names.get(s.bm) or "") if s else "",
            "upbm": names.get(f.bm) or "",
            "huizongjine": year_sum.get(f.kahao, 0.0),
        })
    return rows


EXPORT_COLUMNS = [
    ("卡号", "kahao"), ("本月金额", "jine"), ("地点", "didian"), ("用途", "yongtu"),
    ("年", "nian"), ("月", "yue"), ("年度汇总", "huizongjine"), ("网络", "wangluo"),
    ("状态", "zt"), ("部门", "bm"), ("使用人", "syren"), ("账户", "zhanghu"),
    ("归属部门", "upbm"), ("备注", "bz"),
]


def build_export(rows: list, sheet_name: str = "费用明细") -> bytes:
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")
    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    money_keys = {"jine", "huizongjine"}
    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
            v = row.get(key)
            cell = ws.cell(row=r, column=c, value=v if v is not None else "")
            cell.border = border
            if key in money_keys:
                cell.number_format = "#,##0.00"
    widths = {
        "kahao": 18, "jine": 12, "didian": 28, "yongtu": 20, "nian": 8,
        "yue": 8, "huizongjine": 14, "wangluo": 14, "zt": 12, "bm": 16,
        "syren": 12, "zhanghu": 14, "upbm": 16, "bz": 28,
    }
    for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(key, 14)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
