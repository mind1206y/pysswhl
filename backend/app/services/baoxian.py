"""车辆保险(照旧 CLbaoxianController / baoxianService)公共逻辑:
筛选查询、行组装、Excel 导出、导入模板、上传解析。
"""

from datetime import date, datetime
from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.vehicle import ClBaoxian, ClChe

LX_OPTIONS = ["商业车险", "交强险"]


def baoxian_query(db: Session, user, *, keyword: str = "", year: int = None,
                  lx: str = "", dept: int = None):
    """保险记录 + 车辆联查,带部门子树数据权限(照旧 LoadSearchEntities)。

    关键字匹配 保险公司/车号(照旧 GetList);年度按投保日期;
    保险种类精确匹配;部门下拉在权限子树内再按所选部门(含子树)过滤。
    """
    q = db.query(ClBaoxian, ClChe).join(ClChe, ClBaoxian.cheid == ClChe.id)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(ClChe.bmid.in_(scope))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(ClBaoxian.bxcom.like(like), ClChe.chehao.like(like)))
    if year:
        q = q.filter(func.year(ClBaoxian.tbdate) == year)
    if lx:
        q = q.filter(ClBaoxian.lx == lx)
    if dept:
        # 部门下拉旧口径是 cj 前缀(含下级),新库用 parent_id 子树
        q = q.filter(ClChe.bmid.in_(_dept_subtree(db, dept)))
    return q


def _dept_subtree(db: Session, dept: int) -> set:
    """部门 id + 全部下级(parent_id 递归),对应旧 cj 前缀匹配。"""
    from app.models.user import Department

    ids = {dept}
    stack = [dept]
    while stack:
        pid = stack.pop()
        for (cid,) in db.query(Department.id).filter(Department.parent_id == pid).all():
            if cid not in ids:
                ids.add(cid)
                stack.append(cid)
    return ids


def build_rows(db: Session, pairs) -> list:
    names = dept_name_map(db)
    rows = []
    for row, car in pairs:
        d = row.to_dict()
        d["chehao"] = car.chehao if car else ""
        d["yongtu"] = (car.yongtu or "") if car else ""
        dept_name = (names.get(car.bmid) if car and car.bmid else "") or ""
        d["bumen"] = dept_name or (car.bm if car else "") or ""
        rows.append(d)
    return rows


def sum_jine(q) -> float:
    """筛选结果合计金额(照旧 tongjijine,作用于全部筛选行而非当前页)。"""
    total = q.with_entities(func.sum(ClBaoxian.jine)).scalar()
    return float(total) if total is not None else 0.0


# 导出 12 列照旧 loadbxExcel:序号/车号/投保日期/保单号/保险种类/投保金额/
# 保险公司/保险到期/经手人/备注/用途/部门
EXPORT_COLUMNS = ["序号", "车号", "投保日期", "保单号", "保险种类", "投保金额",
                  "保险公司", "保险到期", "经手人", "备注", "用途", "部门"]


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "保险费用"
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, label in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        values = [
            r - 1, row.get("chehao"), row.get("tbdate"), row.get("bdnumber"),
            row.get("lx"), row.get("jine"), row.get("bxcom"), row.get("dqdate"),
            row.get("jingshou"), row.get("bz"), row.get("yongtu"), row.get("bumen"),
        ]
        for c, v in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=v if v is not None else "")
        for c in range(1, len(EXPORT_COLUMNS) + 1):
            ws.cell(row=r, column=c).border = border

    widths = [6, 16, 13, 24, 12, 12, 24, 13, 10, 20, 12, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_template() -> BytesIO:
    """导入模板(照旧 DownloadTemplate):3 行表头区,数据从第 4 行开始。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "保险导入"

    ws.cell(row=1, column=1, value="保险费用导入模板")
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.cell(row=2, column=1, value=(
        "说明：车号须为系统中已登记的车号；日期填 yyyy/MM/dd（或日期格式单元格）；"
        "保险类别填「商业车险」或「交强险」；保单号必填且用于判断重复上传；"
        "投保金额只填数字。数据从第 4 行开始填写。"
    ))

    headers = ["", "车号", "投保日期", "保单号", "保险类别", "投保金额(元)",
               "保险公司", "保险到期", "经手人"]
    for c, label in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=c, value=label)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = PatternFill("solid", fgColor="eef2f7")

    widths = [6, 16, 14, 22, 12, 14, 24, 14, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _parse_date(cell) -> date:
    """照旧 ParseExcelDate:Excel 日期数值直接转;字符串支持 yyyy/MM/dd;兜底通用解析。"""
    if cell is None or (isinstance(cell, str) and not cell.strip()):
        raise ValueError("日期单元格不能为空")
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = str(cell).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        raise ValueError(f"无法解析日期: {text}")


def _parse_money(cell) -> float:
    if cell is None or (isinstance(cell, str) and not cell.strip()):
        raise ValueError("投保金额不能为空")
    text = str(cell).strip().replace("¥", "").replace(",", "").replace("，", "")
    try:
        return round(float(text), 4)
    except ValueError:
        raise ValueError(f"投保金额不是数字: {text}")


def _cell_str(cell) -> str:
    if cell is None:
        return ""
    return str(cell).strip()


def import_xlsx(data: bytes, username: str, db: Session) -> str:
    """上传导入(照旧 exeExcel):第 4 行起,B~I 列;保单号去重;逐行容错汇总。"""
    try:
        wb = load_workbook(BytesIO(data), data_only=True)
    except Exception as exc:
        return f"读取文件失败：{exc}"
    ws = wb.worksheets[0]

    ok_count = dup_count = err_count = 0
    added_bd = set()  # 本批次已入库保单号,防文件内自重复
    err_msgs = []     # 错误摘要(最多 5 条)

    # 预加载全部车号 → 首个匹配车辆(照旧按 chehao 首条,不限 delf)
    cars_by_no = {}
    for car in db.query(ClChe).order_by(ClChe.id).all():
        cars_by_no.setdefault(car.chehao, car)

    # 预加载已存在保单号(旧库逐条查,这里一次取出去重判断等价)
    exists_bd = {
        num for (num,) in db.query(ClBaoxian.bdnumber).filter(
            ClBaoxian.bdnumber.isnot(None), ClBaoxian.bdnumber != "").all()
    }

    for idx, row in enumerate(ws.iter_rows(min_row=4, max_col=9), start=4):
        cells = {i: row[i - 1].value for i in range(1, 10)}
        if not any(_cell_str(cells.get(i)) for i in range(2, 10)):
            continue  # 整行空白(尾行格式行)跳过,不计失败
        try:
            chehao = _cell_str(cells.get(2))
            car = cars_by_no.get(chehao)
            if car is None:
                raise ValueError("车号不存在")
            tbrq = _parse_date(cells.get(3))
            bd = _cell_str(cells.get(4))
            lx = _cell_str(cells.get(5))
            jine = _parse_money(cells.get(6))
            bxcom = _cell_str(cells.get(7))
            dqd = _parse_date(cells.get(8))
            jingshou = _cell_str(cells.get(9))

            if not bd or bd in exists_bd or bd in added_bd:
                dup_count += 1  # 重复:跳过单条,不中断后续导入
                continue

            db.add(ClBaoxian(
                cheid=car.id, tbdate=tbrq, bdnumber=bd, lx=lx, jine=jine,
                bxcom=bxcom, dqdate=dqd, djname=username,
                jingshou=jingshou, djdate=datetime.now(),
            ))
            added_bd.add(bd)
            ok_count += 1
        except Exception as exc:
            err_count += 1
            if len(err_msgs) < 5:
                err_msgs.append(f"第{idx}行：{exc}")

    db.commit()

    summary = f"导入成功 {ok_count} 条，跳过重复 {dup_count} 条，导入失败 {err_count} 条"
    if err_msgs:
        summary += "；" + "；".join(err_msgs) + (" 等" if err_count > len(err_msgs) else "")
    return summary


def content_disposition(filename: str) -> str:
    """中文文件名必须 quote,否则 Starlette 按 latin-1 编码报 500。"""
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")
