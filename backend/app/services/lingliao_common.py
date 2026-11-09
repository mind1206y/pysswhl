"""领料申请公共逻辑(照旧 LingLiaoController / LingLiaoService 1:1 复刻)。

- 单号规则 LL + yyyyMMdd + 4 位流水。
- 状态:0 草稿 / 1 已提交 / 2 已审核 / 3 已驳回 / 4 已作废 / 5 部分结算 / 6 全部结算。
- 部门可见范围沿用 dept_scope_ids 子树(旧系统 cj 前缀语义)。
- 导出的「材料需求单」版式照旧 ExportDetail(HSSFWorkbook) 平移到 openpyxl。
"""

from datetime import datetime
from io import BytesIO
from typing import Optional
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.lingliao import LingLiao, LingLiaoDetail
from app.models.material import MaterialLibrary
from app.models.user import User

STATUS_LABELS = {
    0: "草稿",
    1: "已提交",
    2: "已审核",
    3: "已驳回",
    4: "已作废",
    5: "部分结算",
    6: "全部结算",
}

# 可编辑(草稿/驳回)与可作废状态
EDITABLE_STATUS = (0, 3)
SUBMITTABLE_STATUS = (0, 3)
CANCELLABLE_STATUS = (0, 3)


def r1(v) -> float:
    return round(float(v or 0), 1)


def r2(v) -> float:
    return round(float(v or 0), 2)


def s(v) -> str:
    return "" if v is None else str(v)


def parse_date(value) -> Optional[datetime]:
    """兼容 el-date-picker 的 yyyy-MM-dd / yyyy-MM-dd HH:mm:ss / ISO。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:19] if len(raw) > 19 else raw, fmt)
        except ValueError:
            continue
    return None


def generate_danno(db: Session) -> str:
    prefix = "LL" + datetime.now().strftime("%Y%m%d")
    today_max = (
        db.query(LingLiao.danno)
        .filter(LingLiao.danno.like(prefix + "%"))
        .order_by(LingLiao.danno.desc())
        .first()
    )
    number = 1
    if today_max and today_max[0]:
        seq = today_max[0][len(prefix):]
        try:
            number = int(seq) + 1
        except ValueError:
            number = 1
    return f"{prefix}{number:04d}"


def scoped_query(db: Session, user: User, bmid: Optional[int] = None):
    """返回按部门子树(或指定部门)收窄的领料单查询。"""
    scope = dept_scope_ids(db, user)
    q = db.query(LingLiao)
    if bmid:
        q = q.filter(LingLiao.bmid == bmid)
    elif scope is not None:
        q = q.filter(LingLiao.bmid.in_(scope))
    return q


def list_query(db: Session, user: User, keyword: str = "", shzt: Optional[int] = None,
               bmid: Optional[int] = None):
    q = scoped_query(db, user, bmid)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(LingLiao.danno.like(like), LingLiao.gongyingshang.like(like)))
    if shzt is not None:
        q = q.filter(LingLiao.shzt == shzt)
    return q


def detail_rows(db: Session, lingliaoid: int) -> list:
    rows = (
        db.query(LingLiaoDetail)
        .filter(LingLiaoDetail.lingliaoid == lingliaoid)
        .order_by(LingLiaoDetail.id)
        .all()
    )
    return [r.to_dict() for r in rows]


def material_options(db: Session) -> list:
    rows = db.query(MaterialLibrary).order_by(MaterialLibrary.material_name).all()
    result = []
    for m in rows:
        result.append({
            "MaterialId": m.id,
            "materialname": f"{m.material_name or ''} / {m.model or ''} / {m.spec or ''}",
            "model": m.model or "",
            "spec": m.spec or "",
            "unit": m.unit or "",
        })
    return result


def supplier_options(db: Session) -> list:
    rows = (
        db.query(LingLiao.gongyingshang)
        .filter(
            LingLiao.gongyingshang.isnot(None),
            LingLiao.gongyingshang != "",
            LingLiao.shzt != 4,
        )
        .distinct()
        .order_by(LingLiao.gongyingshang)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def build_form_excel(db: Session, order: LingLiao) -> BytesIO:
    """照旧 ExportDetail 生成「材料需求单」(.xlsx)。"""
    details = (
        db.query(LingLiaoDetail)
        .filter(LingLiaoDetail.lingliaoid == order.id)
        .order_by(LingLiaoDetail.id)
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "材料需求单"

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    # 标题
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=7)
    title = ws.cell(row=1, column=1, value="材料需求单")
    title.font = Font(size=16, bold=True)
    title.alignment = center
    ws.row_dimensions[1].height = 24

    # 空行
    ws.row_dimensions[2].height = 15

    # 申请日期 / 领用部门
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=2)
    ws.cell(row=3, column=1, value="申请日期：").alignment = left
    ws.cell(row=3, column=3, value=order.sqriqi.strftime("%Y-%m-%d") if order.sqriqi else "")
    ws.cell(row=3, column=4, value="领用部门：").alignment = left
    ws.merge_cells(start_row=3, start_column=6, end_row=3, end_column=7)
    ws.cell(row=3, column=6, value=order.bm or "")

    # 申请人 / 计划领用时间
    ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=2)
    ws.cell(row=4, column=1, value="申请人姓名及联系方式：").alignment = left
    ws.cell(row=4, column=3, value=order.sqren or "")
    ws.cell(row=4, column=4, value="计划领用时间：").alignment = left
    ws.merge_cells(start_row=4, start_column=6, end_row=4, end_column=7)
    ws.cell(row=4, column=6, value="")

    # 用途说明 / 单号
    ws.merge_cells(start_row=5, start_column=1, end_row=5, end_column=2)
    ws.cell(row=5, column=1, value="用途说明：").alignment = left
    ws.cell(row=5, column=3, value=order.shuoming or "")
    ws.cell(row=5, column=4, value="单号：").alignment = left
    ws.merge_cells(start_row=5, start_column=5, end_row=5, end_column=7)
    ws.cell(row=5, column=5, value=order.danno or "")

    # 空行
    ws.row_dimensions[6].height = 15

    # 明细表头
    headers = ["序号", "材料名称", "规格型号", "单位", "申请数量", "实发数量", "备注"]
    header_row = 7
    for idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=text)
        cell.font = Font(bold=True)
        cell.alignment = center
        cell.border = border

    # 明细
    row_no = header_row + 1
    for serial, item in enumerate(details, start=1):
        spec_model = f"{item.model or ''} {item.spec or ''}".strip()
        values = [
            serial,
            item.llname or "",
            spec_model,
            item.unit or "",
            float(item.num) if item.num is not None else 0,
            float(item.renum) if item.renum not in (None, 0) else "",
            item.beizhu or "",
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_no, column=idx, value=value)
            cell.border = border
            cell.alignment = center if idx in (1, 4, 5, 6) else left
        row_no += 1

    # 备注行
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
    ws.cell(row=row_no, column=1, value="备注：").alignment = left
    row_no += 1

    # 签名行
    ws.cell(row=row_no, column=1, value="领料人：")
    ws.cell(row=row_no, column=3, value="主任：")
    ws.cell(row=row_no, column=4, value="厂站所长：")
    ws.cell(row=row_no, column=6, value="发料人：")
    row_no += 1

    # 底部说明
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
    ws.cell(row=row_no, column=1, value="（本表一式两份，发料仓库、领料部门各留一份）")

    # 列宽
    widths = [5, 22, 24, 8, 10, 10, 18]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def excel_disposition(filename: str) -> str:
    return "attachment; filename*=UTF-8''" + quote(filename)
