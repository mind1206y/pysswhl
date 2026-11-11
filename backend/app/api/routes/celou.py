"""测漏成果汇总(照旧 CelouTbController 复刻),挂 /api/celou。

- 台账:24 列列表 + 全量合计行、部门数据权限、筛选(年度/月份/部门/队伍/管径/漏量/模糊/重复工单等)
- 导入导出:13 列 Excel 导入(事务)、21 列导出、模板下载
- 统计:同比环比、部门/管径/管材/队伍分布、管径/漏量年度均值
- 坐标分布:Leaflet + 本地高德离线瓦片(GCJ-02)热力图、三种权重、200 米半径统计
- 工单详情:外部工单系统 HTTP 查询,不可达时明确降级提示

权限:celou:view=入口 + 日常操作(查询/图表/导出/热力图);
     celou:manage=批量删除/Excel 导入/批量设为非预定(与工程、水费、车辆模块口径一致)。
"""

import math
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import (
    dept_name_map, get_current_user, require_permission,
)
from app.core.config import BASE_DIR, settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.celou import CelouTb, CLdui
from app.models.user import User
from app.services.celou_common import (
    build_query, calc_qjll, celou_params, chart_bar, chart_pie, chart_tb,
    dicts, footer, get_months, row_to_dict, sorted_query,
)
from app.services.celou_excel import (
    ImportError_, TEMPLATE_PATH, build_export, content_disposition,
    export_filename, import_workbook,
)
from app.services.workorder_external import fetch_workorder

router = APIRouter()


class IdsIn(BaseModel):
    ids: List[int]


class CoordUpdate(BaseModel):
    id: int
    jingdu: float
    weidu: float


# ==================== 列表 / 字典 ====================
@router.get("")
def list_celou(
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    q = build_query(db, p, user)
    total = q.count()
    foot = footer(q)
    rows = sorted_query(q, bool(p.get("showDuplicate"))).offset(
        (p["page"] - 1) * p["rows"]).limit(p["rows"]).all()
    names = dept_name_map(db)
    return {
        "rows": [row_to_dict(r, names) for r in rows],
        "total": total,
        "footer": [foot],
        "page": p["page"], "size": p["rows"],
    }


@router.get("/dicts")
def celou_dicts(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    return dicts(db, user)


@router.get("/months")
def celou_months(
    nd: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    return get_months(db, nd)


@router.get("/usernames")
def celou_usernames(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    return [{"username": r[0]} for r in db.query(CelouTb.username)
            .filter(CelouTb.username.isnot(None), CelouTb.username != "")
            .distinct().order_by(CelouTb.username).all()]


# ==================== 管理操作 ====================
@router.post("/delete")
def delete_celou(
    data: IdsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="出现未知错误")
    rows = db.query(CelouTb).filter(CelouTb.id.in_(data.ids)).all()
    if not user.is_superuser and any(r.username != user.username for r in rows):
        raise HTTPException(status_code=403, detail="删除失败，非本人上传的记录无法删除！")
    for r in rows:
        db.delete(r)
    db.commit()
    return {"ok": True, "deleted": len(rows)}


@router.post("/batch-non-yuding")
def batch_non_yuding(
    data: IdsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:manage")),
):
    n = db.query(CelouTb).filter(CelouTb.id.in_(data.ids)).update(
        {CelouTb.yudingliang: False}, synchronize_session=False)
    db.commit()
    return {"ok": True, "updated": n}


@router.post("/update-coord")
def update_coord(
    data: CoordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:manage")),
):
    """表格内联编辑单条记录的经度/纬度,并记录修改人与修改时间。"""
    r = db.query(CelouTb).filter(CelouTb.id == data.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="记录不存在")
    r.zuobiao_jingdu = data.jingdu
    r.zuobiao_weidu = data.weidu
    r.xgusername = (user.username or user.real_name or "") or None
    r.xgdatetime = datetime.now()
    db.commit()
    return {
        "ok": True,
        "id": r.id,
        "jingdu": float(r.zuobiao_jingdu),
        "weidu": float(r.zuobiao_weidu),
        "xgusername": r.xgusername or "",
        "xgdatetime": r.xgdatetime.isoformat(sep=" ", timespec="seconds") if r.xgdatetime else None,
    }


@router.post("/upload")
async def upload_celou(
    upcost: UploadFile = File(...),
    cldw: str = Form(""),
    nd: int = Form(0),
    yf: int = Form(0),
    yudingliang: int = Form(0),
    zuobiao_leibie: str = Form("高德火星坐标"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:manage")),
):
    data = await upcost.read()
    try:
        result = import_workbook(
            db, data, upcost.filename or "", user=user.username or user.real_name or "",
            duiwu=cldw.strip(), nian=nd, yue=yf,
            yudingliang=bool(yudingliang), zuobiao_leibie=zuobiao_leibie,
        )
    except ImportError_ as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **result}


@router.get("/template")
def download_template(user: User = Depends(require_permission("celou:view"))):
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=404, detail="模板文件缺失")
    return Response(
        content=TEMPLATE_PATH.read_bytes(),
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": content_disposition("测漏成果表.xls")},
    )


@router.get("/export")
def export_celou(
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    q = sorted_query(build_query(db, p, user))
    rows = q.all()
    payload = build_export(rows, p.get("nd") or 0, dept_name_map(db))
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(export_filename(p.get("nd") or 0))},
    )


# ==================== 统计图表 ====================
@router.get("/charts/tb")
def chart_tb_data(
    n: int = 0,
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    return chart_tb(db, p, user, n or p.get("nd") or 0)


@router.get("/charts/pie")
def chart_pie_data(
    kind: str = Query("bumen"),
    n: int = 0,
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    if kind not in ("bumen", "guanjing", "guancai", "duiwu"):
        raise HTTPException(status_code=400, detail="未知统计维度")
    return chart_pie(db, p, user, kind, n or p.get("nd") or 0)


@router.get("/charts/bar")
def chart_bar_data(
    kind: str = Query("guanjing"),
    value: float = Query(0),
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    if kind not in ("guanjing", "louliang"):
        raise HTTPException(status_code=400, detail="未知统计维度")
    if not value:
        raise HTTPException(status_code=400, detail=f"请选择{'管径' if kind == 'guanjing' else '漏量上限'}")
    return chart_bar(db, p, user, kind, value)


# ==================== 热力图(Leaflet + 本地高德离线瓦片) ====================
def _tile_root() -> Path:
    """瓦片根目录:优先 .env 配置,其次项目内 assets/tiles,最后旧系统目录。"""
    cfg = (settings.CELOU_TILE_DIR or "").strip()
    if cfg:
        return Path(cfg)
    local = BASE_DIR / "assets" / "tiles"
    if local.is_dir():
        return local
    return Path("E:/sswhl/sswhl/Content/Tiles")


# 缺失瓦片返回 1x1 透明 PNG,避免 Leaflet 报 404(照旧 TileController.EmptyPng)
_EMPTY_PNG = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41,
    0x54, 0x78, 0x9C, 0x63, 0x00, 0x00, 0x00, 0x02,
    0x00, 0x01, 0xE5, 0x27, 0xDE, 0xFC, 0x00, 0x00,
    0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42,
    0x60, 0x82,
])


def _percentile(values, q: float) -> float:
    """照旧 CelouTbController.Percentile:排序后取 ceil(q*(n-1)) 位置。"""
    if not values:
        return 1.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, math.ceil(q * (len(s) - 1))))
    return float(s[idx]) or 1.0


def _heat_points(rows, weight: str):
    """照旧 GetHeatmapData:95 分位归一化 + 0.001 度网格数量聚合分档。"""
    pts = [(r, float(r.zuobiao_jingdu), float(r.zuobiao_weidu))
           for r in rows if r.zuobiao_jingdu is not None and r.zuobiao_weidu is not None]
    if not pts:
        return []
    p95_dia = max(_percentile([float(r.gjsmall) for r, _l, _a in pts if r.gjsmall], .95), 1.0)
    p95_flow = max(_percentile([float(r.louliang) for r, _l, _a in pts
                                if r.louliang is not None], .95), 1.0)

    if weight == "count":
        grid = Counter((math.floor(lng / 0.001) * 0.001,
                        math.floor(lat / 0.001) * 0.001) for _r, lng, lat in pts)
        vals = sorted(grid.values())
        n = len(vals)
        p50, p75 = vals[int(n * .50)], vals[int(n * .75)]
        p90, p95 = vals[int(n * .90)], vals[int(n * .95)]
        return [
            {"lng": round(lng, 6), "lat": round(lat, 6),
             "intensity": max(0.2, 0.25 if c <= p50 else 0.45 if c <= p75
                              else 0.65 if c <= p90 else 0.85 if c <= p95 else 1.0),
             "count": c, "louliang": 0, "didian": "", "gongdan": "", "gjsmall": None}
            for (lng, lat), c in grid.items()
        ]

    out = []
    for r, lng, lat in pts:
        if weight == "flow" and r.louliang is not None:
            intensity = math.log10(float(r.louliang) + 1) / math.log10(p95_flow + 1)
        elif weight == "diameter" and r.gjsmall:
            intensity = min(float(r.gjsmall), p95_dia) / p95_dia
        else:
            continue
        out.append({
            "lng": lng, "lat": lat,
            "intensity": round(max(0.2, min(1.0, intensity)), 4),
            "count": 1, "louliang": float(r.louliang or 0),
            "gongdan": r.gongdan or "", "didian": r.didian or "", "gjsmall": r.gjsmall,
        })
    return out


@router.post("/heatmap/tile-token")
def heatmap_tile_token(user: User = Depends(require_permission("celou:view"))):
    """为 <img> 瓦片请求签发短令牌(Leaflet 无法带 Authorization 头)。"""
    return {
        "token": create_short_token("celou_tile", {"uid": user.id}, minutes=180),
        "available": _tile_root().is_dir(),
    }


@router.get("/tiles")
def tile_file(z: int, x: int, y: int, token: str = ""):
    """本地高德离线瓦片;缺图返回透明占位,与旧 TileController 行为一致。"""
    try:
        decode_short_token(token, "celou_tile")
    except Exception:
        raise HTTPException(status_code=403, detail="瓦片令牌无效或已过期")
    root = _tile_root()
    path = root / f"{z}" / f"{x}" / f"{y}.png"
    data = path.read_bytes() if path.is_file() else _EMPTY_PNG
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/heatmap/points")
def heatmap_points(
    weight: str = Query("count"),
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    rows = build_query(db, p, user).all()
    return {"total": len(rows), "points": _heat_points(rows, weight)}


@router.get("/heatmap/stats")
def heatmap_stats(
    lng: float, lat: float, radius: float = 200,
    p: dict = Depends(celou_params),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("celou:view")),
):
    rows = build_query(db, p, user).all()
    hits = []
    for r in rows:
        if r.zuobiao_jingdu is None or r.zuobiao_weidu is None:
            continue
        dlat = math.radians(float(r.zuobiao_weidu) - lat)
        dlon = math.radians(float(r.zuobiao_jingdu) - lng)
        a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat))
             * math.cos(math.radians(float(r.zuobiao_weidu))) * math.sin(dlon / 2) ** 2)
        dist = 6371000 * 2 * math.asin(min(1.0, math.sqrt(a)))
        if dist <= radius:
            hits.append((dist, r))
    hits.sort(key=lambda x: x[0])
    dias = [r.gjsmall for _d, r in hits if r.gjsmall]
    return {
        "count": len(hits),
        "totalFlow": round(sum(float(r.louliang or 0) for _d, r in hits), 2),
        "avgDiameter": round(sum(dias) / len(dias), 2) if dias else 0,
        "maxDiameter": max(dias) if dias else 0,
        "radius": radius,
        "details": [{"didian": r.didian, "louliang": float(r.louliang or 0),
                     "guanjing": r.guanjing, "gjsmall": r.gjsmall,
                     "jingdu": float(r.zuobiao_jingdu), "weidu": float(r.zuobiao_weidu),
                     "distance": round(d, 1)}
                    for d, r in hits[:10]],
    }


# ==================== 工单详情(外部系统) ====================
@router.get("/workorder")
def workorder(
    no: str = Query(...),
    user: User = Depends(require_permission("celou:view")),
):
    """外部工单系统查询(溯源旧站 ImageProxy.GetByNo);不可达时明确降级。"""
    return fetch_workorder(no)
