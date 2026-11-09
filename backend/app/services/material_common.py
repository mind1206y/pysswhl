"""工单材料库公共逻辑(照旧 MaterialLibraryController 查询口径)。

- 关键字分词:空格/中英文逗号拆开,逐词 AND 命中
  材料名称/型号类别/规格/拼音首字母/备注/别名1~3
- 部门过滤:指定 bmid 用它(非超管自动与本人部门子树求交),
  未指定时按本人部门子树(照旧 bb_bumen.cj 前缀语义,超管看全部)
- 大口径:dakoujing 非空即勾选口径(旧系统开关存 'on')
- 进出库记录:入库(in_stock_record) + 工单领料出库(material_record,数量取负)
  两个来源各自倒序各取 pageIndex*pageSize 条,合并排序后内存分页(照旧,避免全表超时)
"""

from datetime import datetime, timedelta
from typing import List, Optional

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.material import InStockRecord, MaterialImage, MaterialLibrary, MaterialRecord
from app.models.user import User


def split_keywords(mohu: str) -> List[str]:
    """照旧:按空格/中英文逗号分词,去空。"""
    if not mohu:
        return []
    return [k for k in (t.strip() for t in mohu.replace("，", ",").replace(" ", ",").split(",")) if k]


def _scoped(db: Session, user: User, requested_bmid: Optional[int]):
    """返回(None=不限定)或部门 id 集合;指定 bmid 时收窄为该部门。"""
    scope = dept_scope_ids(db, user)
    if requested_bmid and requested_bmid > 0:
        if scope is not None:
            return {requested_bmid} if requested_bmid in scope else {-1}
        return {requested_bmid}
    return scope


def stock_query(db: Session, user: User, dakoujing: str = "", bmid: Optional[int] = None,
                keywords: Optional[List[str]] = None):
    q = db.query(MaterialLibrary)
    scope = _scoped(db, user, bmid)
    if scope is not None:
        q = q.filter(MaterialLibrary.bmid.in_(scope))
    if dakoujing:
        q = q.filter(MaterialLibrary.dakoujing.isnot(None), MaterialLibrary.dakoujing != "")
    for k in keywords or []:
        like = f"%{k}%"
        q = q.filter(
            MaterialLibrary.material_name.like(like)
            | MaterialLibrary.model.like(like)
            | MaterialLibrary.spec.like(like)
            | MaterialLibrary.biaoji.like(like)
            | MaterialLibrary.remark.like(like)
            | MaterialLibrary.alias1.like(like)
            | MaterialLibrary.alias2.like(like)
            | MaterialLibrary.alias3.like(like)
        )
    return q


def images_for_materials(db: Session, material_ids: List[int], user_id: int = 0) -> dict:
    """材料 id -> [{id, FilePath, ThumbPath}],按图片 id 升序(照旧)。

    FilePath/ThumbPath 返回短令牌 URL:<img> 带不了 Authorization,
    照测漏/维修图片同一套 celou_tile/repair_image 令牌方案。
    """
    from app.core.security import create_short_token

    if not material_ids:
        return {}
    imgs = (
        db.query(MaterialImage)
        .filter(MaterialImage.material_id.in_(material_ids))
        .order_by(MaterialImage.id)
        .all()
    )
    out: dict = {}
    for img in imgs:
        t1 = create_short_token("material_image", {"iid": img.id, "sub": str(user_id)},
                                minutes=180)
        t2 = create_short_token("material_image", {"iid": img.id, "sub": str(user_id), "thumb": 1},
                                minutes=180)
        out.setdefault(img.material_id, []).append({
            "id": img.id,
            "Id": img.id,
            "FileName": img.file_name or "",
            "FilePath": f"/api/materials/image?token={t1}",
            "ThumbPath": f"/api/materials/image?token={t2}",
        })
    return out


def build_stock_rows(db: Session, materials: List[MaterialLibrary], user_id: int = 0) -> list:
    img_map = images_for_materials(db, [m.id for m in materials], user_id=user_id)
    rows = []
    for m in materials:
        d = m.to_dict()
        d["Images"] = img_map.get(m.id, [])
        rows.append(d)
    return rows


# ==================== 进出库记录 ====================
def in_out_records(db: Session, user: User, page: int, size: int,
                   bmid: Optional[int] = None, direction: str = "",
                   start_date: str = "", end_date: str = "", mohu: str = ""):
    """返回 (page_rows, total),口径与旧 GetInOutRecords 一致。"""
    dt_start = None
    dt_end = None
    if start_date:
        try:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            pass
    if end_date:
        try:
            dt_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            pass
    keywords = split_keywords(mohu)
    scope = _scoped(db, user, bmid)
    take_count = page * size

    in_total = 0
    in_list: list = []
    if direction in ("", "入库"):
        q = (
            db.query(InStockRecord, MaterialLibrary)
            .join(MaterialLibrary, InStockRecord.material_id == MaterialLibrary.id)
        )
        if scope is not None:
            q = q.filter(MaterialLibrary.bmid.in_(scope))
        if dt_start:
            q = q.filter(InStockRecord.in_stock_time >= dt_start)
        if dt_end:
            q = q.filter(InStockRecord.in_stock_time < dt_end)
        for k in keywords:
            like = f"%{k}%"
            q = q.filter(
                MaterialLibrary.material_name.like(like)
                | MaterialLibrary.model.like(like)
                | MaterialLibrary.spec.like(like)
                | MaterialLibrary.alias1.like(like)
                | MaterialLibrary.alias2.like(like)
                | MaterialLibrary.alias3.like(like)
                | InStockRecord.remark.like(like)
            )
        in_total = q.count()
        for rec, mat in (
            q.order_by(InStockRecord.in_stock_time.desc()).limit(take_count).all()
        ):
            in_list.append({
                "Id": rec.id,
                "MaterialName": mat.material_name or "",
                "Model": mat.model or "",
                "Spec": mat.spec or "",
                "dakoujing": mat.dakoujing,
                "Quantity": round(float(rec.quantity or 0), 1),
                "Unit": mat.unit or "",
                "RecordTime": rec.in_stock_time.strftime("%Y-%m-%d %H:%M:%S") if rec.in_stock_time else None,
                "Remark": rec.remark or "",
                "Operator": rec.operator or "",
                "Direction": rec.lei or "入库",
                "RefNo": ("领料" + str(rec.lingliao_detail_id)) if rec.lingliao_detail_id else "",
            })

    out_total = 0
    out_list: list = []
    if direction in ("", "出库"):
        from app.models.material import WorkOrder

        q = (
            db.query(MaterialRecord, MaterialLibrary, WorkOrder)
            .join(MaterialLibrary, MaterialRecord.material_id == MaterialLibrary.id)
            .join(WorkOrder, MaterialRecord.work_order_id == WorkOrder.id)
        )
        if scope is not None:
            q = q.filter(MaterialLibrary.bmid.in_(scope))
        if dt_start:
            q = q.filter(WorkOrder.create_time >= dt_start)
        if dt_end:
            q = q.filter(WorkOrder.create_time < dt_end)
        for k in keywords:
            like = f"%{k}%"
            q = q.filter(
                MaterialLibrary.material_name.like(like)
                | MaterialLibrary.model.like(like)
                | MaterialLibrary.spec.like(like)
                | MaterialLibrary.alias1.like(like)
                | MaterialLibrary.alias2.like(like)
                | MaterialLibrary.alias3.like(like)
                | WorkOrder.remark.like(like)
            )
        out_total = q.count()
        for rec, mat, wo in (
            q.order_by(MaterialRecord.create_time.desc()).limit(take_count).all()
        ):
            out_list.append({
                "Id": rec.id,
                "MaterialName": mat.material_name or "",
                "Model": mat.model or "",
                "Spec": mat.spec or "",
                "dakoujing": mat.dakoujing,
                "Quantity": -round(float(rec.quantity or 0), 1),
                "Unit": mat.unit or "",
                "RecordTime": rec.create_time.strftime("%Y-%m-%d %H:%M:%S") if rec.create_time else None,
                "Remark": (wo.remark if wo else "") or "",
                "Operator": (wo.creator if wo else "") or "",
                "Direction": "出库",
                "RefNo": (wo.work_order_no if wo else "") or "",
            })

    merged = sorted(
        in_list + out_list,
        key=lambda r: r["RecordTime"] or "",
        reverse=True,
    )
    total = in_total + out_total if direction == "" else (in_total if direction == "入库" else out_total)
    start = (page - 1) * size
    return merged[start:start + size], total


def excel_disposition(filename: str) -> str:
    from urllib.parse import quote

    return f"attachment; filename*=UTF-8''{quote(filename)}"


def build_stock_check_excel(materials: List[MaterialLibrary]) -> bytes:
    """盘点表(照旧 ExportStockCheck 10 列)。"""
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "盘点表"
    headers = ["材料名称", "别名1", "别名2", "型号类别", "规格", "库存数量", "盘点数量", "差异", "单位", "备注"]
    ws.append(headers)
    for m in sorted(materials, key=lambda x: (x.material_name or "", x.spec or "")):
        ws.append([
            m.material_name or "",
            m.alias1 or "",
            m.alias2 or "",
            m.model or "",
            m.spec or "",
            round(float(m.num or 0), 1),
            "",
            "",
            m.unit or "",
            m.remark or "",
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_in_out_excel(records: List[dict]) -> bytes:
    """进出库记录导出(照旧 ExportInOutRecords 8 列)。"""
    from io import BytesIO

    wb = Workbook()
    ws = wb.active
    ws.title = "进出库记录"
    ws.append(["材料名称", "规格", "单位", "数量", "操作人", "时间", "类型", "备注"])
    for r in sorted(records, key=lambda x: x["RecordTime"] or ""):
        ws.append([
            r["MaterialName"],
            r["Spec"],
            r["Unit"],
            f"{float(r['Quantity']):.1f}",
            r["Operator"],
            r["RecordTime"] or "",
            r["Direction"],
            r["Remark"],
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
