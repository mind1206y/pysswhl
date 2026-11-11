"""领料结算公共逻辑(照旧 jiesuandanService / JiesuanService 1:1 复刻)。

核心口径:
- 结算明细只从「已审核(+)」领料明细中取,可结算 = 实发数量 - 已结算数量。
- 新增/修改结算明细时同步更新 lingliaodetail.jiesuannum/jiesuanzt、lingliao.shzt,
  并把结算单价写回 material_library.lastdanjia。
- 领料主表状态:全部明细未结算 -> 2 已审核;有实发明细全部结算 -> 6 全部结算;否则 5 部分结算。
- 结算单总额 zonge 始终按该结算单下全部明细 SUM(jine) 重算。
- 部门可见范围沿用 dept_scope_ids 子树(旧系统 cj 前缀语义)。
"""

from datetime import datetime
from io import BytesIO
from typing import Iterable, Optional
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.jiesuandan import JiesuanCailiao, JiesuanDetail
from app.models.lingliao import LingLiao, LingLiaoDetail
from app.models.material import MaterialLibrary

STATUS_LABELS = {
    0: "未结算",
    1: "部分结算",
    2: "全部结算",
}


def s(v) -> str:
    return "" if v is None else str(v)


def r4(v) -> float:
    return round(float(v or 0), 4)


def parse_date(value) -> Optional[datetime]:
    """兼容 yyyy-MM-dd / yyyy-MM-dd HH:mm:ss / ISO。"""
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


def generate_danno() -> str:
    """旧系统 CreateInit 直接拼当前秒:JS + yyyyMMddHHmmss。"""
    return "JS" + datetime.now().strftime("%Y%m%d%H%M%S")


def order_query(db: Session, user, keyword: str = "", bmid: Optional[int] = None):
    """结算单列表:部门子树 + (单号/供应商)模糊。"""
    scope = dept_scope_ids(db, user)
    q = db.query(JiesuanCailiao)
    if bmid:
        q = q.filter(JiesuanCailiao.bmid == bmid)
    elif scope is not None:
        q = q.filter(JiesuanCailiao.bmid.in_(scope))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(
            JiesuanCailiao.jiesuandanno.like(like),
            JiesuanCailiao.gongyingshang.like(like),
        ))
    return q


def sort_order_query(q):
    return q.order_by(JiesuanCailiao.jiesuanriqi.desc(), JiesuanCailiao.id.desc())


def supplier_options(db: Session, user) -> list:
    """供应商下拉:本人部门子树内、未作废领料单的供应商去重。"""
    scope = dept_scope_ids(db, user)
    q = db.query(LingLiao.gongyingshang).filter(
        LingLiao.gongyingshang.isnot(None),
        LingLiao.gongyingshang != "",
        LingLiao.shzt != 4,
    )
    if scope is not None:
        q = q.filter(LingLiao.bmid.in_(scope))
    rows = q.distinct().order_by(LingLiao.gongyingshang).all()
    return [r[0] for r in rows if r[0]]


def _candidate_join(db: Session):
    return (
        db.query(LingLiaoDetail, LingLiao, MaterialLibrary)
        .join(LingLiao, LingLiaoDetail.lingliaoid == LingLiao.id)
        .outerjoin(MaterialLibrary, LingLiaoDetail.material_id == MaterialLibrary.id)
    )


def candidate_query(db: Session, keyword: str = "", gongyingshang: str = ""):
    """可结算领料明细:剩余数量>0 且领料单已审核/部分结算(照旧 shzt in 2,5)。"""
    q = _candidate_join(db).filter(
        (LingLiaoDetail.renum - LingLiaoDetail.jiesuannum) > 0,
        LingLiao.shzt.in_((2, 5)),
    )
    if gongyingshang:
        q = q.filter(LingLiao.gongyingshang == gongyingshang)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(
            LingLiao.gongyingshang.like(like),
            LingLiaoDetail.llname.like(like),
        ))
    return q


def candidate_row(detail: LingLiaoDetail, main: LingLiao, material) -> dict:
    lastdanjia = material.lastdanjia if material is not None else None
    shengyu = float(detail.renum or 0) - float(detail.jiesuannum or 0)
    return {
        "id": detail.id,
        "danno": s(main.danno),
        "llname": s(detail.llname),
        "model": s(detail.model),
        "spec": s(detail.spec),
        "unit": s(detail.unit),
        "renum": r4(detail.renum),
        "jiesuannum": r4(detail.jiesuannum),
        "shengyu": round(shengyu, 4),
        "thisnum": round(shengyu, 4),
        "danjia": r4(lastdanjia),
        "gongyingshang": s(main.gongyingshang),
        "cailiaoID": detail.material_id,
        "MaterialId": detail.material_id,
    }


def candidate_page(
    db: Session, keyword: str = "", gongyingshang: str = "",
    page: int = 1, size: int = 20,
) -> tuple:
    q = candidate_query(db, keyword, gongyingshang)
    total = q.count()
    current = max(int(page or 1), 1)
    page_size = max(int(size or 20), 1)
    rows = (
        q.order_by(LingLiaoDetail.id)
        .offset((current - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, [candidate_row(detail, main, material) for detail, main, material in rows]


def candidate_rows(db: Session, keyword: str = "", gongyingshang: str = "") -> list:
    rows = candidate_query(db, keyword, gongyingshang).order_by(LingLiaoDetail.id).all()
    return [candidate_row(detail, main, material) for detail, main, material in rows]


def detail_query(db: Session, jiesuanid: int):
    return (
        db.query(JiesuanDetail, LingLiaoDetail, LingLiao)
        .join(LingLiaoDetail, JiesuanDetail.lingliaodetailid == LingLiaoDetail.id)
        .join(LingLiao, LingLiaoDetail.lingliaoid == LingLiao.id)
        .filter(JiesuanDetail.jiesuanid == jiesuanid)
        .order_by(JiesuanDetail.id)
    )


def detail_rows(db: Session, jiesuanid: int) -> list:
    rows = []
    for detail, ling_detail, main in detail_query(db, jiesuanid).all():
        rows.append({
            "id": detail.id,
            "danno": s(main.danno),
            "gongyingshang": s(main.gongyingshang),
            "MaterialId": ling_detail.material_id,
            "cailiaoID": ling_detail.material_id,
            "llname": s(ling_detail.llname),
            "model": s(ling_detail.model),
            "spec": s(ling_detail.spec),
            "unit": s(ling_detail.unit),
            "num": r4(detail.num),
            "danjia": r4(detail.danjia),
            "jine": r4(detail.jine),
            "beizhu": s(ling_detail.beizhu),
            "renum": r4(ling_detail.renum),
            "jiesuannum": r4(ling_detail.jiesuannum),
            "jiesuanzt": ling_detail.jiesuanzt if ling_detail.jiesuanzt is not None else 0,
        })
    return rows


def cg_rows(db: Session, jiesuanid: int) -> list:
    """采购申请单/验收单取数行(按结算明细 id 升序)。"""
    rows = []
    for _detail, ling_detail, _main in detail_query(db, jiesuanid).all():
        rows.append({
            "llname": s(ling_detail.llname),
            "model": s(ling_detail.model),
            "spec": s(ling_detail.spec),
            "unit": s(ling_detail.unit),
            "num": r4(_detail.num),
            "danjia": r4(_detail.danjia),
            "jine": r4(_detail.jine),
            "beizhu": s(ling_detail.beizhu),
        })
    return rows


def recalc_order_total(db: Session, jiesuanid: int) -> float:
    total = (
        db.query(JiesuanDetail)
        .filter(JiesuanDetail.jiesuanid == jiesuanid)
        .with_entities(JiesuanDetail.jine)
        .all()
    )
    value = round(sum(float(row[0] or 0) for row in total), 4)
    order = db.get(JiesuanCailiao, jiesuanid)
    if order is not None:
        order.zonge = value
    return value


def recalc_lingliao_status(db: Session, lingliao_ids: Iterable[int]) -> None:
    """按剩余明细重算领料主表状态(有实发明细全部结算 -> 6,否则 5/2)。"""
    for main_id in {int(i) for i in lingliao_ids if i}:
        all_details = (
            db.query(LingLiaoDetail)
            .filter(LingLiaoDetail.lingliaoid == main_id)
            .all()
        )
        details_with_renum = [d for d in all_details if float(d.renum or 0) > 0]
        all_zero = bool(all_details) and all(
            (d.jiesuanzt or 0) == 0 for d in all_details
        )
        all_two = bool(details_with_renum) and all(
            (d.jiesuanzt or 0) == 2 for d in details_with_renum
        )
        main = db.get(LingLiao, main_id)
        if main is None:
            continue
        if all_zero:
            main.shzt = 2
        elif all_two:
            main.shzt = 6
        else:
            main.shzt = 5


def update_lingliao_detail_status(detail: LingLiaoDetail) -> None:
    """按累计结算数量更新单条领料明细的结算状态。"""
    jiesuannum = float(detail.jiesuannum or 0)
    renum = float(detail.renum or 0)
    if jiesuannum <= 0:
        detail.jiesuanzt = 0
    elif jiesuannum < renum:
        detail.jiesuanzt = 1
    else:
        detail.jiesuanzt = 2


# ==================== Excel ====================
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
MONEY_FMT = "#,##0.00"


def _join_gg(model: str, spec: str) -> str:
    a = (model or "").strip()
    b = (spec or "").strip()
    if a and b:
        return f"{a}/{b}"
    return a + b


def build_settlement_excel(db: Session, order: JiesuanCailiao) -> BytesIO:
    """照旧 ExportDetail 生成「销售结算表」(.xlsx)。"""
    rows = detail_rows(db, order.id)

    wb = Workbook()
    ws = wb.active
    ws.title = "结算明细"
    col_count = 12

    # 标题
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    title = ws.cell(row=1, column=1, value="销售结算表")
    title.font = Font(size=18, bold=True)
    title.alignment = CENTER
    ws.row_dimensions[1].height = 30

    # 结算信息
    ws.cell(row=2, column=1, value="结算单号：" + s(order.jiesuandanno))
    ws.cell(
        row=2, column=col_count - 2,
        value="结算日期：" + (
            order.jiesuanriqi.strftime("%Y-%m-%d") if order.jiesuanriqi else ""
        ),
    )

    # 供应商
    supplier = rows[0]["gongyingshang"] if rows else s(order.gongyingshang)
    ws.cell(row=3, column=1, value="供应商：" + supplier)

    # 表头
    headers = [
        "序号", "供应商", "材料ID", "材料名称", "型号", "规格",
        "单位", "数量", "单价", "金额", "备注", "领料单号",
    ]
    header_row = 4
    for idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=idx, value=text)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
        cell.border = BORDER
        cell.fill = HEADER_FILL

    # 数据
    row_no = header_row + 1
    first_data_row = row_no
    for serial, item in enumerate(rows, start=1):
        values = [
            serial,
            item["gongyingshang"],
            item["MaterialId"] if item["MaterialId"] is not None else "",
            item["llname"],
            item["model"],
            item["spec"],
            item["unit"],
            float(item["num"] or 0),
            float(item["danjia"] or 0),
            float(item["jine"] or 0),
            item["beizhu"],
            item["danno"],
        ]
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_no, column=idx, value=value)
            cell.border = BORDER
            cell.alignment = CENTER if idx in (1, 3, 7, 8) else LEFT
            if idx in (9, 10):
                cell.number_format = MONEY_FMT
        row_no += 1

    # 合计
    last_data_row = row_no - 1
    total_row = row_no
    ws.cell(row=total_row, column=9, value="合计：").font = Font(bold=True)
    total_cell = ws.cell(
        row=total_row, column=10,
        value=f"=SUM(J{first_data_row}:J{last_data_row})",
    )
    total_cell.number_format = MONEY_FMT
    total_cell.font = Font(bold=True)

    # 冻结表头 + 列宽
    ws.freeze_panes = f"A{header_row + 1}"
    widths = [7, 24, 10, 24, 16, 18, 8, 10, 12, 14, 22, 16]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_cg_excel(
    db: Session,
    order: JiesuanCailiao,
    cg_type: int,
    sgbm: str = "",
    sgyy: str = "",
    user_bm: str = "",
) -> BytesIO:
    """照旧 DownloadCg 生成采购申请单(type=1)/验收单(type=2)(.xlsx)。"""
    rows = cg_rows(db, order.id)
    is_ys = cg_type == 2

    wb = Workbook()
    ws = wb.active
    ws.title = "采购验收单" if is_ys else "采购申请单"

    col_count = 9 if is_ys else 8
    widths = (
        [5, 18, 15, 7, 8, 10, 11, 11, 14]
        if is_ys else [5, 20, 16, 8, 8, 10, 12, 16]
    )
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:3" if is_ys else "1:4"
    ws.oddFooter.center.text = "第 &P 页 / 共 &N 页"

    dept = sgbm
    row_no = 1

    # 标题
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=col_count)
    title = ws.cell(
        row=row_no, column=1,
        value=f"{user_bm}{'物资采购验收单' if is_ys else '物资采购申请单'}",
    )
    title.font = Font(size=16, bold=True)
    title.alignment = CENTER
    ws.row_dimensions[row_no].height = 26
    row_no += 1

    # 信息行
    if is_ys:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=col_count)
        ws.cell(
            row=row_no, column=1,
            value=(
                "部门名称：" + dept
                + "    结算单号：" + s(order.jiesuandanno)
                + "    日期：" + (
                    order.jiesuanriqi.strftime("%Y-%m-%d") if order.jiesuanriqi else ""
                )
            ),
        ).alignment = LEFT
        row_no += 1
    else:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=col_count)
        ws.cell(
            row=row_no, column=1,
            value="申请部门：" + dept + "    结算单号：" + s(order.jiesuandanno),
        ).alignment = LEFT
        row_no += 1

        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=col_count)
        ws.cell(row=row_no, column=1, value="申购原因：" + s(sgyy)).alignment = LEFT
        row_no += 1

    # 表头
    heads = (
        ["序号", "材料名称", "规格、型号", "单位", "数量", "单价", "金额", "验收情况", "备注"]
        if is_ys else
        ["序号", "材料名称", "规格、型号", "单位", "数量", "单价", "金额", "备注"]
    )
    for idx, text in enumerate(heads, start=1):
        cell = ws.cell(row=row_no, column=idx, value=text)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
        cell.border = BORDER
        cell.fill = HEADER_FILL
    row_no += 1

    # 明细
    for serial, item in enumerate(rows, start=1):
        values = [
            serial,
            item["llname"],
            _join_gg(item["model"], item["spec"]),
            item["unit"],
            float(item["num"] or 0),
            float(item["danjia"] or 0),
            float(item["jine"] or 0),
        ]
        # 验收单「验收情况」列统一写「完成」；申请单无此列，直接写备注
        values.append("完成" if is_ys else item["beizhu"])
        if is_ys:
            values.append(item["beizhu"])
        for idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_no, column=idx, value=value)
            cell.border = BORDER
            cell.alignment = LEFT if idx in (2, 3, len(heads)) else CENTER
            if idx in (6, 7):
                cell.number_format = MONEY_FMT
        row_no += 1

    # 合计行
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
    ws.cell(row=row_no, column=1, value="合计").font = Font(bold=True)
    ws.cell(row=row_no, column=1).alignment = CENTER
    ws.cell(row=row_no, column=7, value=float(order.zonge or 0)).number_format = MONEY_FMT
    for idx in range(1, len(heads) + 1):
        ws.cell(row=row_no, column=idx).border = BORDER
    row_no += 1

    # 签字行：申请单三栏 审批 / 审核 / 申请人，验收单仍两栏 验收 / 经办
    if is_ys:
        ws.cell(row=row_no, column=1, value="验收：")
        ws.cell(row=row_no, column=6, value="经办：")
    else:
        ws.row_dimensions[row_no].height = 28
        ws.cell(row=row_no, column=1, value="审批：").alignment = LEFT
        ws.cell(row=row_no, column=3, value="审核：").alignment = LEFT
        ws.cell(row=row_no, column=6, value="申请人：").alignment = LEFT

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def excel_disposition(filename: str) -> str:
    return "attachment; filename*=UTF-8''" + quote(filename)
