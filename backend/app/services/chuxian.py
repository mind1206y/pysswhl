"""车辆出险信息(照旧 ChuxianView)公共逻辑:筛选、行组装、Excel 导出。"""

from datetime import date
from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import and_, func, or_

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, ClChuxian, ClCxTP


def parse_years(raw: str) -> list:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def accident_query(db, user, *, years: str = "", dept=None, keyword: str = ""):
    """出险记录 + 车辆联查,带部门子树作用域(照旧 LoadSearchEntitiesAll 的车号/部门筛选)。"""
    q = db.query(ClChuxian, ClChe).join(ClChe, ClChuxian.cheid == ClChe.id)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    year_list = parse_years(years)
    if year_list:
        # 用日期区间代替 YEAR():MySQL/SQLite 都可用,且能走 riqi 索引
        q = q.filter(or_(*[
            and_(ClChuxian.riqi >= date(y, 1, 1), ClChuxian.riqi < date(y + 1, 1, 1))
            for y in year_list
        ]))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            ClChe.chehao.like(like),
            ClChuxian.jiashiyuan.like(like),
            ClChuxian.miaoshu.like(like),
            ClChuxian.zeren.like(like),
        ))
    if dept:
        q = q.filter(ClChe.bmid == dept)
    return q


def car_counts(q) -> dict:
    """筛选结果内每辆车(cheid)的出险次数,用于车牌号气泡(照旧 carCounts)。"""
    return {
        cheid: int(n)
        for cheid, n in (
            q.order_by(None)
            .with_entities(ClChuxian.cheid, func.count(ClChuxian.id))
            .group_by(ClChuxian.cheid)
            .all()
        )
    }


def build_rows(db, pairs, counts=None) -> list:
    if counts is None:
        counts = {}
        for acc, _car in pairs:
            counts[acc.cheid] = counts.get(acc.cheid, 0) + 1
    names = dept_name_map(db)
    ids = [acc.id for acc, _car in pairs]
    images = {}
    if ids:
        for tp in db.query(ClCxTP).filter(ClCxTP.cxid.in_(ids)).all():
            images.setdefault(tp.cxid, []).append(tp.to_dict())
    rows = []
    for acc, car in pairs:
        d = acc.to_dict()
        d["chehao"] = car.chehao if car else ""
        dept_name = (names.get(car.bmid) if car and car.bmid else "") or ""
        d["bumen"] = dept_name or (car.bm if car else "") or acc.bm or ""
        d["cxCount"] = counts.get(acc.cheid, 1)
        d["tps"] = images.get(acc.id, [])
        rows.append(d)
    return rows


# 照旧 ExportExcel 11 列:车牌号/出险日期/驾驶人/描述/金额/地点/公里/部门/出险次数/记录人/最后操作日期
EXPORT_COLUMNS = [
    ("车牌号", "chehao"), ("出险日期", "riqi"), ("驾驶人", "jiashiyuan"),
    ("描述", "miaoshu"), ("金额（元）", "jine"), ("地点", "dizhi"),
    ("公里", "gongli"), ("部门", "bumen"), ("出险次数", "cxCount"),
    ("记录人", "caozuo"), ("最后操作日期", "zuihou"),
]


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "出险记录"
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
            v = row.get(key)
            ws.cell(row=r, column=c, value=v if v is not None else "")
        for c in range(1, len(EXPORT_COLUMNS) + 1):
            ws.cell(row=r, column=c).border = border

    widths = [14, 13, 10, 30, 12, 24, 8, 12, 9, 10, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码报 500。"""
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")
