"""车辆违章信息(照旧 ClweizhangController)公共逻辑:筛选、行组装、Excel 导出。"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClChe, ClWeizhang


def parse_years(raw: str) -> list:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def weizhang_query(db, user, *, years: str = "", dept=None, keyword: str = ""):
    """违章记录 + 车辆联查,带部门子树数据权限(照旧 LoadSearchEntities)。"""
    q = db.query(ClWeizhang, ClChe).join(ClChe, ClWeizhang.cheid == ClChe.id)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    year_list = parse_years(years)
    if year_list:
        q = q.filter(func.year(ClWeizhang.wzriqi).in_(year_list))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            ClWeizhang.lu.like(like),
            ClWeizhang.xingming.like(like),
            ClWeizhang.wz.like(like),
            ClWeizhang.dj.like(like),
            ClChe.chehao.like(like),
        ))
    if dept:
        q = q.filter(ClChe.bmid == dept)
    return q


def car_counts(q) -> dict:
    """筛选结果内每辆车的违章次数,用于车牌号气泡(照旧 carCounts)。"""
    return {
        cheid: int(n)
        for cheid, n in (
            q.order_by(None)
            .with_entities(ClWeizhang.cheid, func.count(ClWeizhang.id))
            .group_by(ClWeizhang.cheid)
            .all()
        )
    }


def build_rows(db, pairs, counts=None) -> list:
    if counts is None:
        counts = {}
        for row, _car in pairs:
            counts[row.cheid] = counts.get(row.cheid, 0) + 1
    names = dept_name_map(db)
    rows = []
    for row, car in pairs:
        d = row.to_dict()
        d["chehao"] = car.chehao if car else ""
        dept_name = (names.get(car.bmid) if car and car.bmid else "") or ""
        d["bumen"] = dept_name or (car.bm if car else "") or ""
        d["wzCount"] = counts.get(row.cheid, 1)
        rows.append(d)
    return rows


# 照旧 ExportExcel 11 列:车牌号/违章日期/驾驶人/路段/内容/罚款金额/公里数/车辆部门/次数/记录/最后日期
EXPORT_COLUMNS = [
    ("车牌号", "chehao"), ("违章日期", "wzriqi"), ("驾驶人", "xingming"),
    ("路段", "lu"), ("内容", "wz"), ("罚款金额", "jine"),
    ("公里数", "gongli"), ("车辆部门", "bumen"), ("次数", "wzCount"),
    ("记录", "dj"), ("最后日期", "zhriqi"),
]


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "违章记录"
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

    widths = [14, 13, 10, 30, 30, 12, 8, 12, 6, 10, 20]
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
