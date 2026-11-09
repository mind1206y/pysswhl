"""工单领料 WorkOrder 公共逻辑(照旧 WorkOrderController 1:1 复刻)。

口径备忘:
- 列表/导出筛选按「工单创建时间」;结束日期含当天 23:59:59(旧 AddDays(1).AddSeconds(-1))。
- 领料类别固定 11 项(旧前端硬编码);筛选 '__EMPTY__' 表示未分类。
- 大口径:列表按材料 dakoujing 非空即算,导出按 == 'on'(旧系统两处口径不同,照旧保留)。
- 已领用 IsUsed = EXISTS(gongdancailiao.gongdanhao == work_order.work_order_no),
  WorkOrder.is_used 是旧系统从未写过的死列,不参与判定。
- 提交/删除领料单即时增减 material_library.num,不写 in_stock_record(出库流水即 material_record)。
- 数量一律 1 位小数;部门可见范围统一走 dept_scope_ids 子树(旧系统仅本部门,按新系统约定放宽)。
"""

from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.material import MaterialLibrary, MaterialRecord, WorkOrder
from app.models.road_repair import Qiangxiurenyuan
from app.models.user import User
from app.models.workorder import GongdanCailiao, WorkOrderAttachment
from app.services.material_common import split_keywords

# 旧 Views/WorkOrder/Index.cshtml 的 LINGLIAO_TYPE_LIST,顺序即下拉顺序
LINGLIAO_TYPES = [
    "管网维抢修",
    "阀门及阀门井维修改造",
    "水表及水表井维修改造",
    "市政消防栓及配套设施维抢修",
    "小区域供水管网维修改造",
    "管网排污、排气更新改造",
    "阀门专项维护费用",
    "市政消防栓维护保养",
    "立式水表箱及供水支管更换",
    "创文明费用",
    "其他",
]
FILTER_ALL = "全部类别"
FILTER_EMPTY = "（未分类）"
EMPTY_SENTINEL = "__EMPTY__"


def r1(v) -> float:
    return round(float(v or 0), 1)


def s(v) -> str:
    return "" if v is None else str(v)


def fmt_dt(v, with_seconds: bool = True) -> str:
    if not v:
        return ""
    return v.strftime("%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M")


def parse_date(value: str, end: bool = False) -> Optional[datetime]:
    """旧 DateTime.TryParse + 结束日 AddDays(1).AddSeconds(-1)。"""
    if not value:
        return None
    raw = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw[:19] if len(raw) > 19 else raw, fmt)
            return dt + timedelta(days=1) - timedelta(seconds=1) if end else dt
        except ValueError:
            continue
    return None


def scoped(db: Session, user: User, requested_bmid: Optional[int] = None):
    """可见部门 id 集合;None=不限定(超管/无部门)。指定 bmid 时收窄。"""
    scope = dept_scope_ids(db, user)
    if requested_bmid and requested_bmid > 0:
        if scope is not None:
            return {requested_bmid} if requested_bmid in scope else {-1}
        return {requested_bmid}
    return scope


def used_exists_expr():
    """EXISTS 子查询:该工单号是否已在工单材料登记表登记过。"""
    return exists(
        select(GongdanCailiao.id).where(GongdanCailiao.gongdanhao == WorkOrder.work_order_no)
    )


def _apply_type_filter(q, lingliaotype: str):
    lt = (lingliaotype or "").strip()
    if not lt or lt == FILTER_ALL:
        return q
    if lt == EMPTY_SENTINEL:
        return q.filter(or_(WorkOrder.lingliaotype.is_(None), WorkOrder.lingliaotype == ""))
    return q.filter(WorkOrder.lingliaotype == lt)


def order_query(db: Session, user: User, *, search_text: str = "", start_date: str = "",
                end_date: str = "", dakoujing: str = "", lingliaotype: str = "",
                unused_only: bool = False, bmid: Optional[int] = None):
    """工单列表基查询(照旧 BuildWorkOrderQuery,补上部门子树与 unusedOnly 前置过滤)。"""
    q = db.query(WorkOrder)
    scope = scoped(db, user, bmid)
    if scope is not None:
        q = q.filter(WorkOrder.bmid.in_(scope))
    if search_text:
        like = f"%{search_text.strip()}%"
        detail_exists = exists(
            select(MaterialRecord.id)
            .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
            .where(
                MaterialRecord.work_order_id == WorkOrder.id,
                or_(
                    MaterialLibrary.material_name.like(like),
                    MaterialLibrary.spec.like(like),
                    MaterialLibrary.model.like(like),
                    MaterialLibrary.alias1.like(like),
                    MaterialLibrary.alias2.like(like),
                    MaterialLibrary.alias3.like(like),
                ),
            )
        )
        q = q.filter(or_(
            detail_exists,
            WorkOrder.banzu.like(like),
            WorkOrder.work_order_no.like(like),
            WorkOrder.beizhu.like(like),
        ))
    if dakoujing:  # 旧口径:材料 dakoujing 非空即算大口径
        q = q.filter(exists(
            select(MaterialRecord.id)
            .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
            .where(
                MaterialRecord.work_order_id == WorkOrder.id,
                MaterialLibrary.dakoujing.isnot(None),
                MaterialLibrary.dakoujing != "",
            )
        ))
    start = parse_date(start_date)
    end = parse_date(end_date, end=True)
    if start:
        q = q.filter(WorkOrder.create_time >= start)
    if end:
        q = q.filter(WorkOrder.create_time <= end)
    q = _apply_type_filter(q, lingliaotype)
    if unused_only:
        q = q.filter(~used_exists_expr())
    return q


def used_no_set(db: Session, nos: list) -> set:
    if not nos:
        return set()
    rows = (
        db.query(GongdanCailiao.gongdanhao)
        .filter(GongdanCailiao.gongdanhao.in_([n for n in nos if n]))
        .distinct().all()
    )
    return {r[0] for r in rows}


def attachment_counts(db: Session, ids: list) -> dict:
    if not ids:
        return {}
    rows = (
        db.query(WorkOrderAttachment.workorderid, func.count(WorkOrderAttachment.id))
        .filter(WorkOrderAttachment.workorderid.in_(ids))
        .group_by(WorkOrderAttachment.workorderid).all()
    )
    return {r[0]: int(r[1]) for r in rows}


def order_rows(db: Session, orders: list) -> list:
    used = used_no_set(db, [o.work_order_no for o in orders])
    atts = attachment_counts(db, [o.id for o in orders])
    return [{
        "Id": o.id,
        "id": o.id,
        "WorkOrderNo": s(o.work_order_no),
        "Remark": s(o.remark),
        "banzu": s(o.banzu),
        "lingliaotype": s(o.lingliaotype),
        "Creator": s(o.creator),
        "beizhu": s(o.beizhu),
        "IsUsed": bool(o.work_order_no and o.work_order_no in used),
        "AttachmentCount": atts.get(o.id, 0),
        "CreatedTime": fmt_dt(o.create_time),
        "EditTime": fmt_dt(o.edittime),
        "editor": s(o.editor),
        "bmid": o.bmid,
    } for o in orders]


def detail_rows(db: Session, order_id: int) -> list:
    """领料明细(旧 GetOrderDetails):CreatedTime 精确到分钟。"""
    q = (
        db.query(MaterialRecord, MaterialLibrary)
        .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
        .filter(MaterialRecord.work_order_id == order_id)
        .order_by(MaterialRecord.id)
    )
    return [{
        "MaterialName": s(mat.material_name),
        "Model": s(mat.model),
        "Spec": s(mat.spec),
        "Quantity": r1(rec.quantity),
        "Unit": s(mat.unit),
        "dakoujing": mat.dakoujing,
        "CreatedTime": fmt_dt(rec.create_time, with_seconds=False),
    } for rec, mat in q.all()]


def by_no_rows(db: Session, work_order_no: str) -> list:
    """按工单号回显明细+主表(旧 GetOrderByWorkNo / GetOrderByWorkNo2)。"""
    q = (
        db.query(MaterialRecord, MaterialLibrary, WorkOrder)
        .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
        .join(WorkOrder, WorkOrder.id == MaterialRecord.work_order_id)
        .filter(WorkOrder.work_order_no == work_order_no)
        .order_by(MaterialRecord.id)
    )
    return [{
        "WorkOrderId": rec.work_order_id,
        "MaterialId": rec.material_id,
        "MaterialName": s(mat.material_name),
        "Model": s(mat.model),
        "Spec": s(mat.spec),
        "Quantity": r1(rec.quantity),
        "Qty": r1(rec.quantity),
        "Unit": s(mat.unit),
        "dakoujing": mat.dakoujing,
        "Creator": s(wo.creator),
        "banzu": s(wo.banzu),
        "lingliaotype": s(wo.lingliaotype),
        "beizhu": s(wo.beizhu),
        "editor": s(wo.editor),
        "CreatedTime": fmt_dt(wo.create_time),
        "EditTime": fmt_dt(wo.edittime),
    } for rec, mat, wo in q.all()]


def stock_rows(db: Session, user: User, page: int, size: int, mohu: str = ""):
    """选料库存(照旧 gdclkuService:按领用次数降序,再按型号/名称/规格/id)。"""
    use_count = func.count(MaterialRecord.id).label("use_count")
    q = (
        db.query(MaterialLibrary, use_count)
        .outerjoin(MaterialRecord, MaterialRecord.material_id == MaterialLibrary.id)
        .group_by(MaterialLibrary.id)
    )
    scope = scoped(db, user)
    if scope is not None:
        q = q.filter(MaterialLibrary.bmid.in_(scope))
    for kw in split_keywords(mohu):
        like = f"%{kw}%"
        q = q.filter(or_(
            MaterialLibrary.material_name.like(like),
            MaterialLibrary.spec.like(like),
            MaterialLibrary.model.like(like),
            MaterialLibrary.biaoji.like(like),
            MaterialLibrary.remark.like(like),
            MaterialLibrary.alias1.like(like),
            MaterialLibrary.alias2.like(like),
            MaterialLibrary.alias3.like(like),
        ))
    total = q.count()
    rows = (
        q.order_by(use_count.desc(), MaterialLibrary.model, MaterialLibrary.material_name,
                   MaterialLibrary.spec, MaterialLibrary.id)
        .offset((page - 1) * size).limit(size).all()
    )
    return ({
        "Id": m.id, "id": m.id, "MaterialName": s(m.material_name), "Model": s(m.model),
        "Spec": s(m.spec), "Remark": s(m.remark), "Unit": s(m.unit),
        "biaoji": s(m.biaoji), "dakoujing": m.dakoujing, "num": r1(m.num),
    } for m, _cnt in rows), total


def banzu_options(db: Session, user: User) -> list:
    q = db.query(Qiangxiurenyuan)
    scope = scoped(db, user)
    if scope is not None:
        q = q.filter(Qiangxiurenyuan.bmid.in_(scope))
    return [{"id": r.id, "name": s(r.name)} for r in q.order_by(Qiangxiurenyuan.name).all()]


# ==================== 导出:3 个统计 Sheet(照旧 ExportMaterialStatistics) ====================

def material_record_rows(db: Session, user: User, *, search_text: str = "", start_date: str = "",
                         end_date: str = "", dakoujing: str = "", lingliaotype: str = "") -> list:
    """导出统计的数据源(照旧 BuildMaterialRecordQuery,按新系统约定加部门子树收窄)。"""
    q = (
        db.query(MaterialRecord, MaterialLibrary, WorkOrder)
        .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
        .join(WorkOrder, WorkOrder.id == MaterialRecord.work_order_id)
    )
    scope = scoped(db, user)
    if scope is not None:
        q = q.filter(WorkOrder.bmid.in_(scope))
    if search_text:
        like = f"%{search_text.strip()}%"
        q = q.filter(or_(
            MaterialLibrary.material_name.like(like), MaterialLibrary.spec.like(like),
            MaterialLibrary.model.like(like), MaterialLibrary.alias1.like(like),
            MaterialLibrary.alias2.like(like), MaterialLibrary.alias3.like(like),
            WorkOrder.banzu.like(like),
        ))
    if dakoujing == "on":  # 旧导出口径:必须是 'on'
        q = q.filter(MaterialLibrary.dakoujing == "on")
    start = parse_date(start_date)
    end = parse_date(end_date, end=True)
    if start:
        q = q.filter(WorkOrder.create_time >= start)
    if end:
        q = q.filter(WorkOrder.create_time <= end)
    lt = (lingliaotype or "").strip()
    if lt and lt != FILTER_ALL:
        if lt == EMPTY_SENTINEL:
            q = q.filter(or_(WorkOrder.lingliaotype.is_(None), WorkOrder.lingliaotype == ""))
        else:
            q = q.filter(WorkOrder.lingliaotype == lt)
    return [{
        "MaterialName": s(mat.material_name), "Model": s(mat.model), "Spec": s(mat.spec),
        "Quantity": float(rec.quantity or 0), "dakoujing": mat.dakoujing,
        "WorkOrderNo": s(wo.work_order_no), "banzu": s(wo.banzu),
        "lingliaotype": s(wo.lingliaotype), "Creator": s(wo.creator),
        "CreateTime": fmt_dt(wo.create_time), "beizhu": s(wo.beizhu),
    } for rec, mat, wo in q.all()]


def _title_text(start_date: str, end_date: str, suffix: str) -> str:
    a = parse_date(start_date)
    b = parse_date(end_date)
    if a and b:
        return f"{a.year}年{a.month:02d}月{a.day:02d}日至{b.year}年{b.month:02d}月{b.day:02d}日 {suffix}"
    return suffix


def _style_sheet(ws, title: str, headers: list, widths: list):
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ncol = len(headers)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    c = ws.cell(row=1, column=1, value=title)
    c.font = Font(bold=True, size=14)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = Font(bold=True, size=11)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"
    return border


def _group_rows(records: list, with_group: bool) -> list:
    groups = {}
    for r in records:
        key = (
            (r["banzu"], r["lingliaotype"]) if with_group else ()
        ) + (r["MaterialName"], r["Model"], r["Spec"])
        g = groups.setdefault(key, {"qty": 0.0, "big": [], "all": []})
        g["qty"] += r["Quantity"]
        no = r["WorkOrderNo"]
        if no and no not in g["all"]:
            g["all"].append(no)
        if r["dakoujing"] == "on" and no and no not in g["big"]:
            g["big"].append(no)
    # 分组键顺序:班组/类别/材料名/型号/规格(无班组时只后三项)
    return [list(key) + [g["qty"], " / ".join(g["big"]), " / ".join(g["all"])]
            for key, g in sorted(groups.items())]


def build_statistics_excel(db: Session, user: User, params: dict) -> BytesIO:
    records = material_record_rows(db, user, **params)
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "材料出库统计"
    border = _style_sheet(
        ws1, _title_text(params.get("start_date", ""), params.get("end_date", ""), "材料出库统计"),
        ["材料名", "型号", "规格", "数量", "大口径工单号", "所有工单号"],
        [22, 16, 18, 12, 42, 52],
    )
    for i, row in enumerate(_group_rows(records, False), start=3):
        for j, v in enumerate(row, 1):
            c = ws1.cell(row=i, column=j, value=v)
            c.border = border
            c.alignment = Alignment(vertical="center", wrap_text=(j >= 5))
            if j == 4:
                c.number_format = "#,##0"

    ws2 = wb.create_sheet("班组领料统计")
    border2 = _style_sheet(
        ws2, _title_text(params.get("start_date", ""), params.get("end_date", ""), "班组领料统计"),
        ["班组", "领料类别", "材料名", "型号", "规格", "数量", "大口径工单号", "所有工单号"],
        [16, 24, 22, 16, 18, 12, 38, 48],
    )
    for i, row in enumerate(_group_rows(records, True), start=3):
        for j, v in enumerate(row, 1):
            c = ws2.cell(row=i, column=j, value=v)
            c.border = border2
            c.alignment = Alignment(vertical="center", wrap_text=(j >= 7))
            if j == 6:
                c.number_format = "#,##0"

    ws3 = wb.create_sheet("未领用工单")
    border3 = _style_sheet(
        ws3, _title_text(params.get("start_date", ""), params.get("end_date", ""), "未领用工单"),
        ["工单号", "领料类别", "班组", "创建人", "创建时间", "备注"],
        [18, 24, 16, 14, 22, 32],
    )
    unused = (
        order_query(db, user,
                    search_text=params.get("search_text", ""),
                    start_date=params.get("start_date", ""),
                    end_date=params.get("end_date", ""),
                    dakoujing=params.get("dakoujing", ""),
                    lingliaotype=params.get("lingliaotype", ""))
        .filter(~used_exists_expr())
        .order_by(WorkOrder.create_time.desc()).all()
    )
    for i, o in enumerate(unused, start=3):
        vals = [s(o.work_order_no), s(o.lingliaotype), s(o.banzu), s(o.creator),
                fmt_dt(o.create_time), s(o.beizhu)]
        for j, v in enumerate(vals, 1):
            c = ws3.cell(row=i, column=j, value=v)
            c.border = border3
            c.alignment = Alignment(vertical="center", wrap_text=True)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def excel_disposition(filename: str) -> str:
    return "attachment; filename*=UTF-8''" + quote(filename)
