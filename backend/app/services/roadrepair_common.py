"""路面修复管理通用服务(照旧 RoadRepairController.GetList/GetListlm 筛选口径)。

口径说明:
- 主列表关键字模糊匹配 地址/维修原因/备注;状态/单位精确;开挖日期范围
- 排序仅支持 total(旧系统 sort=total)与默认 id,默认倒序
- 价格字典:company 为空视为「通用」;按单位取价格选项时,公路局只取公路局专属价,
  其它单位取「本单位专属价 + 通用价」(照旧 GetPriceOptionsByCompany)
- 自动填充单价:同类型先取单位专属价,再退回通用价(照旧 GetPricelm)
"""

from datetime import datetime
from typing import Optional

from app.models.road_repair import (
    Qiangxiurenyuan,
    RoadPrice,
    RoadRepair,
    RoadRepairAttachment,
)

COMPANIES = ["大市政", "湖里市政", "思明市政", "公路局"]
PROGRESS_OPTIONS = ["新建", "已报账", "已付款", "已完账"]
PROGRESS_COLORS = {
    "已报账": "#2563eb",
    "已付款": "#2e7d32",
    "已完账": "#b45309",
    "新建": "#6b7280",
}


def _parse_date(value: str, end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def repair_query(
    db,
    keyword: str = "",
    progress: str = "",
    company: str = "",
    start: str = "",
    end: str = "",
):
    q = db.query(RoadRepair)
    if keyword:
        q = q.filter(
            RoadRepair.address.contains(keyword)
            | RoadRepair.reason.contains(keyword)
            | RoadRepair.remark.contains(keyword)
        )
    if progress:
        q = q.filter(RoadRepair.current_progress == progress)
    if company:
        q = q.filter(RoadRepair.company == company)
    dt_start = _parse_date(start)
    # dig_date 旧库为 date 类型,结束日期取当天(含当日)
    dt_end = _parse_date(end, end_of_day=True)
    if dt_start:
        q = q.filter(RoadRepair.dig_date >= dt_start)
    if dt_end:
        q = q.filter(RoadRepair.dig_date <= dt_end)
    return q


def sort_repair_query(q, sort: str, order: str):
    desc = (order or "desc").lower() != "asc"
    col = RoadRepair.total if sort == "total" else RoadRepair.id
    return q.order_by(col.desc() if desc else col.asc())


def attachment_count_subquery(db):
    from sqlalchemy import func

    return (
        db.query(func.count(RoadRepairAttachment.id))
        .filter(RoadRepairAttachment.repair_id == RoadRepair.id)
        .scalar_subquery()
    )


def price_options(db, company: str = ""):
    """照旧 GetPriceOptionsByCompany:公路局只取公路局价,其它单位含通用价。"""
    q = db.query(RoadPrice)
    if company == "公路局":
        q = q.filter(RoadPrice.company == "公路局")
    elif company:
        q = q.filter((RoadPrice.company == company) | (RoadPrice.company.is_(None)))
    rows = q.order_by(RoadPrice.road_type.asc(), RoadPrice.company.asc()).all()
    options = []
    for p in rows:
        comp = p.company or "通用"
        options.append(
            {
                "id": p.id,
                "road_type": p.road_type or "",
                "company": comp,
                "price": float(p.price or 0),
                "display": f"{p.road_type} / {comp} / {p.price}",
            }
        )
    return options


def match_price(db, company: str, road_type: str) -> Optional[float]:
    """照旧 GetPricelm:同类型中单位专属价优先,退回通用价。"""
    rows = (
        db.query(RoadPrice)
        .filter(
            RoadPrice.road_type == road_type,
            (RoadPrice.company == company) | (RoadPrice.company.is_(None)),
        )
        .all()
    )
    if not rows:
        return None
    specific = [r for r in rows if r.company == company]
    chosen = specific[0] if specific else rows[0]
    return float(chosen.price) if chosen.price is not None else None


def banzu_options(db):
    rows = db.query(Qiangxiurenyuan).order_by(Qiangxiurenyuan.id.asc()).all()
    return [r.name for r in rows if r.name]
