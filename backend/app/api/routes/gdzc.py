"""固定资产(照旧 gdzcController / cwService 1:1 复刻)。

- 列表按「盘点年度」快照查询(必选,默认最大年度),部门/类别/启用年度多选、
  到期资产、关键字、升序;合计是筛选后全量的 SUM(原值)/SUM(净值)
- 行内「盘点确认/取消」「备注记录」,备注登记人/时间随新备注一起写(修旧 Editxz 判断旧值的 bug)
- 报废单详情弹窗(GetDetail)、固定资产明细表 / 盘点表两个 Excel 导出
- 「导入盘点文件」旧入口在 userman 页且 cwController 无鉴权,这里并入本页并加权限
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.finance import ZcBaofeidan, ZcBaofeitp, ZcCw, ZcLb
from app.models.user import User
from app.services.finance_common import (
    dept_name_map, dept_options, display_name, gdzc_query, gdzc_rows, gdzc_totals,
    image_url,
)
from app.services.finance_excel import (
    content_disposition, gdzc_detail_excel, gdzc_pandian_excel, parse_pandian_excel,
)

router = APIRouter()
PERM = "gdzc:view"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RemarkIn(BaseModel):
    id: int
    beizhu: Optional[str] = ""


class CheckIn(BaseModel):
    id: int
    checked: bool


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    years = [r[0] for r in (db.query(ZcCw.nd).filter(ZcCw.nd.isnot(None))
                            .distinct().order_by(ZcCw.nd.asc()).all()) if r[0]]
    cats = [{"id": c.id, "name": c.lb or ""}
            for c in db.query(ZcLb).order_by(ZcLb.id).all()]
    return {
        "years": years,
        "default_year": years[-1] if years else None,
        "categories": cats,
        "departments": dept_options(db, current),
    }


@router.get("/qy-years")
def qy_years(
    nd: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """照旧 GetQyNdList:该盘点年度下出现过的启用年份,降序去重。"""
    q = db.query(func.year(ZcCw.qyrq)).filter(ZcCw.nd == nd, ZcCw.qyrq.isnot(None))
    from app.services.finance_common import finance_scope_ids
    scope = finance_scope_ids(db, current)
    if scope is not None:
        q = q.filter(ZcCw.bmid.in_(scope))
    years = sorted({int(r[0]) for r in q.distinct().all() if r[0]}, reverse=True)
    return {"years": years}


def _filtered(db, user, *, page=1, size=30, nd="", keyword="", dept_id=None,
              categories="", qy_years="", expired=False, asc=False):
    q = gdzc_query(db, user, nd=nd, keyword=keyword, dept_id=dept_id,
                   categories=categories, qy_years=qy_years, expired=expired)
    total = q.count()
    sum_yz, sum_jz = gdzc_totals(q)
    order = (ZcCw.qyrq.asc(), ZcCw.id.asc()) if asc else (ZcCw.qyrq.desc(), ZcCw.id.desc())
    rows = q.order_by(*order).offset((page - 1) * size).limit(size).all()
    return q, total, sum_yz, sum_jz, rows


@router.get("")
def list_assets(
    page: int = 1,
    size: int = 30,
    nd: str = "",
    keyword: str = "",
    dept_id: Optional[int] = None,
    categories: str = "",
    qy_years: str = "",
    expired: bool = False,
    asc: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    _q, total, sum_yz, sum_jz, rows = _filtered(
        db, current, page=page, size=size, nd=nd, keyword=keyword, dept_id=dept_id,
        categories=categories, qy_years=qy_years, expired=expired, asc=asc)
    return {"total": total, "sum_yz": sum_yz, "sum_jz": sum_jz,
            "items": gdzc_rows(db, rows)}


@router.post("/remark")
def save_remark(
    data: RemarkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    row = db.get(ZcCw, data.id)
    if row is None:
        raise HTTPException(status_code=404, detail="资产记录不存在")
    text = (data.beizhu or "").strip()
    row.beizhu = text or None
    if text:
        row.bzdate = datetime.now().replace(microsecond=0)
        row.beizhuren = display_name(current)
    else:
        row.bzdate = None
        row.beizhuren = None
    db.commit()
    return {"ok": True}


@router.post("/check")
def check_asset(
    data: CheckIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """盘点确认/取消:照旧同时覆盖 bzdate / beizhuren(最近操作人)。"""
    row = db.get(ZcCw, data.id)
    if row is None:
        raise HTTPException(status_code=404, detail="资产记录不存在")
    row.pandian = "盘点" if data.checked else None
    row.bzdate = datetime.now().replace(microsecond=0)
    row.beizhuren = display_name(current)
    db.commit()
    return {"ok": True}


@router.get("/baofei/{bfid}")
def baofei_detail(
    bfid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """报废单详情(旧 GetDetail):单头 + 挂在本单上的资产明细 + 图片短令牌。"""
    dan = db.get(ZcBaofeidan, bfid)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    pics = db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid == bfid).order_by(ZcBaofeitp.id).all()
    names = dept_name_map(db)
    from app.services.finance_common import gdzc_rows
    assets = db.query(ZcCw).filter(ZcCw.baofeidanid == bfid).order_by(ZcCw.id).all()
    return {
        "danju": {
            "riqi": dan.riqi.strftime("%Y-%m-%d") if dan.riqi else "",
            "zhaiyao": dan.zaiyao or "", "bumen": names.get(dan.bmid) or "",
            "dengjiren": dan.caozuo or "",
            "dengjiriqi": dan.czriqi.strftime("%Y-%m-%d") if dan.czriqi else "",
            "pics": [image_url(p.dizhi, current.id) for p in pics if p.dizhi],
        },
        "mingxi": gdzc_rows(db, assets),
    }


def _export_params(nd, keyword, dept_id, categories, qy_years, expired, asc):
    return dict(nd=nd, keyword=keyword, dept_id=dept_id, categories=categories,
                qy_years=qy_years, expired=expired, asc=asc)


@router.get("/export")
def export_detail(
    nd: str = "", keyword: str = "", dept_id: Optional[int] = None,
    categories: str = "", qy_years: str = "", expired: bool = False, asc: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """导出=当前筛选全量(修旧 TempData 隐式状态导致的导出与页面不一致)。"""
    q, _t, _a, _b, _p = _filtered(
        db, current, page=1, size=1, **_export_params(
            nd, keyword, dept_id, categories, qy_years, expired, asc))
    rows = q.order_by(ZcCw.qyrq.desc(), ZcCw.id.desc()).all()
    names = dept_name_map(db)
    dept_name = names.get(dept_id, "") if dept_id else "全部部门"
    buf = gdzc_detail_excel(gdzc_rows(db, rows), nd or "", dept_name)
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition(
                        f"{datetime.now():%Y%m%d}固定资产明细表.xlsx")})


@router.get("/pandian-export")
def export_pandian(
    nd: str = "", keyword: str = "", dept_id: Optional[int] = None,
    categories: str = "", qy_years: str = "", expired: bool = False, asc: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    q, _t, _a, _b, _p = _filtered(
        db, current, page=1, size=1, **_export_params(
            nd, keyword, dept_id, categories, qy_years, expired, asc))
    rows = q.order_by(ZcCw.qyrq.asc(), ZcCw.id.asc()).all()
    names = dept_name_map(db)
    dept_name = names.get(dept_id, "") if dept_id else "全部部门"
    buf = gdzc_pandian_excel(gdzc_rows(db, rows), nd or "", dept_name)
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition(
                        f"{nd or ''}年度{dept_name}固定资产盘点表.xlsx")})


@router.post("/import")
async def import_pandian(
    file: UploadFile = File(...),
    bmid: int = Form(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """导入盘点表 Excel(旧 cw/ExportExcel)。照旧按 (nd, zccode) 去重,重复行跳过。"""
    from app.services.finance_common import finance_scope_ids
    scope = finance_scope_ids(db, current)
    if scope is not None and bmid not in scope:
        raise HTTPException(status_code=403, detail="没有该部门的导入权限")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 20MB")
    cats = {c.lb: c.id for c in db.query(ZcLb).all() if c.lb}
    try:
        rows = parse_pandian_excel(content, file.filename or "盘点表.xls", cats)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not rows:
        raise HTTPException(status_code=400, detail="盘点表没有数据行")

    existing = {(r[0], r[1]) for r in (
        db.query(ZcCw.nd, ZcCw.zccode).filter(ZcCw.zccode.isnot(None)).all())}
    added = 0
    for r in rows:
        key = (r["nd"], r["zccode"])
        if key in existing:
            continue
        existing.add(key)
        db.add(ZcCw(**r, bmid=bmid))
        added += 1
    db.commit()
    return {"ok": True, "added": added, "total": len(rows),
            "skipped": len(rows) - added, "bmid": bmid}
