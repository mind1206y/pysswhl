"""清理报告 / 资产报废单(照旧 baofeizcController 1:1 复刻)。

- 主表 = 报废单,报废明细复用 zc_cw.baofeidanid(旧系统没有独立明细表)
- 关键字搜的是已挂单的资产明细字段;单据按登记日期倒序;有明细禁止删除
- 「添加资产设备」候选 = 本部门未报废资产 ∪ 已挂本单资产,每单最多 10 条
- 图片两段式上传改为「上传即落盘 + 保存单据时同步关联」,避免旧 TempData 丢图
- 清理报告 Excel 按单导出(纸质签章栏)
"""

import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, require_permission
from app.db.session import get_db
from app.models.finance import ZcBaofeidan, ZcBaofeitp, ZcCw
from app.models.user import User
from app.services.finance_common import (
    TRANSPARENT_PNG, baofei_query, baofei_rows, candidate_query, default_bmid,
    dept_options, display_name, finance_scope_ids, gdzc_rows, image_path, image_url,
    read_image, save_upload, user_dept_id,
)
from app.services.finance_excel import baofei_report_excel, content_disposition

router = APIRouter()
PERM = "baofeizc:view"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMAGE_EXT = {".jpg", ".jpeg", ".png"}


class DanIn(BaseModel):
    riqi: Optional[date] = None
    bmid: Optional[int] = None
    zaiyao: Optional[str] = ""
    images: list[str] = []


class MxIn(BaseModel):
    id: int
    bfid: Optional[int] = None


class ImageIn(BaseModel):
    dizhi: str


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    year = date.today().year
    return {
        "departments": dept_options(db, current),
        "default_start": f"{year}-01-01",
        "default_end": f"{year}-12-31",
        "default_bmid": default_bmid(current),
    }


@router.get("")
def list_dan(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    dept_id: Optional[int] = None,
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    q = baofei_query(db, current, keyword=keyword, dept_id=dept_id, start=start, end=end)
    total = q.count()
    rows = (q.order_by(ZcBaofeidan.czriqi.desc(), ZcBaofeidan.id.desc())
            .offset((page - 1) * size).limit(size).all())
    return {"total": total, "items": baofei_rows(db, current, rows)}


@router.get("/candidates")
def candidates(
    bfid: int = 0,
    keyword: str = "",
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """添加资产设备弹窗的候选列表(照旧 Getmx)。"""
    q = candidate_query(db, current, bfid=bfid, keyword=keyword)
    total = q.count()
    rows = (q.order_by(ZcCw.baofeicztime.desc(), ZcCw.baofeiqk.desc(),
                       ZcCw.nd.desc(), ZcCw.qyrq.asc())
            .offset((page - 1) * size).limit(size).all())
    items = gdzc_rows(db, rows)
    for item in items:
        item["can_add"] = item["baofeidanid"] is None
    return {"total": total, "items": items}


@router.get("/export/{bfid}")
def export_report(
    bfid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    dan = db.get(ZcBaofeidan, bfid)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    rows = gdzc_rows(db, db.query(ZcCw).filter(ZcCw.baofeidanid == bfid)
                     .order_by(ZcCw.baofeicztime, ZcCw.id).all())
    names = dept_name_map(db)
    bm = names.get(user_dept_id(current) or 0, "") or names.get(dan.bmid or 0, "")
    buf = baofei_report_excel(rows, bm, bfid)
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition(
                        f"清理报告（{datetime.now():%Y%m%d%H%M%S}）.xlsx")})


@router.get("/image")
def image_proxy(token: str = ""):
    """图片短令牌代理。旧 /Upload 图片多数已缺失,缺图返回 1×1 透明 PNG。"""
    data, media = read_image(token)
    if data is None:
        return Response(content=TRANSPARENT_PNG, media_type="image/png")
    return Response(content=data, media_type=media)


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    current: User = Depends(require_permission(PERM)),
):
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in IMAGE_EXT:
        raise HTTPException(status_code=400, detail="只支持 jpg / jpeg / png 图片")
    data = await file.read()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")
    dizhi = save_upload(data, uuid.uuid4().hex + ext)
    return {"dizhi": dizhi, "url": image_url(dizhi, current.id)}


@router.post("/delete-image")
def delete_image(
    data: ImageIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    for p in db.query(ZcBaofeitp).filter(ZcBaofeitp.dizhi == data.dizhi).all():
        db.delete(p)
    db.commit()
    path = image_path(data.dizhi)
    if path and path.is_file():
        path.unlink()
    return {"ok": True}


def _sync_images(db, bfid: int, images: list[str]):
    keep = {d for d in images if d}
    for p in db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid == bfid).all():
        if p.dizhi not in keep:
            db.delete(p)
    existing = {p.dizhi for p in db.query(ZcBaofeitp).filter(
        ZcBaofeitp.bfdid == bfid, ZcBaofeitp.dizhi.in_(keep)).all()} if keep else set()
    for d in images:
        if d and d not in existing:
            db.add(ZcBaofeitp(dizhi=d, bfdid=bfid))


def _check_bmid(db, current, bmid):
    scope = finance_scope_ids(db, current)
    if scope is not None and (bmid is None or bmid not in scope):
        raise HTTPException(status_code=403, detail="没有该部门的操作权限")


@router.post("")
def create_dan(
    data: DanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    bmid = data.bmid or default_bmid(current)
    _check_bmid(db, current, bmid)
    dan = ZcBaofeidan(
        riqi=data.riqi, bmid=bmid, zaiyao=(data.zaiyao or "").strip() or None,
        caozuo=display_name(current), czriqi=datetime.now().replace(microsecond=0),
    )
    db.add(dan)
    db.flush()
    _sync_images(db, dan.id, data.images)
    db.commit()
    return {"ok": True, "id": dan.id}


@router.put("/{bfid}")
def update_dan(
    bfid: int,
    data: DanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    dan = db.get(ZcBaofeidan, bfid)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    bmid = data.bmid or dan.bmid
    _check_bmid(db, current, bmid)
    dan.riqi = data.riqi
    dan.bmid = bmid
    dan.zaiyao = (data.zaiyao or "").strip() or None
    # 照旧 Edit 会刷新登记人/登记日期,但不清空其它字段
    dan.caozuo = display_name(current)
    dan.czriqi = datetime.now().replace(microsecond=0)
    _sync_images(db, bfid, data.images)
    db.commit()
    return {"ok": True}


@router.delete("/{bfid}")
def delete_dan(
    bfid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    dan = db.get(ZcBaofeidan, bfid)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    count = db.query(func.count(ZcCw.id)).filter(ZcCw.baofeidanid == bfid).scalar() or 0
    if count:
        raise HTTPException(status_code=400, detail="该单有记录，无法删除")
    pics = db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid == bfid).all()
    for p in pics:
        path = image_path(p.dizhi)
        if path and path.is_file():
            path.unlink()
        db.delete(p)
    db.delete(dan)
    db.commit()
    return {"ok": True}


@router.get("/{bfid}/mx")
def list_mx(
    bfid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """主表展开的子表(照旧 getmxb,按报废操作时间升序)。"""
    rows = db.query(ZcCw).filter(ZcCw.baofeidanid == bfid).order_by(
        ZcCw.baofeicztime.asc(), ZcCw.id.asc()).all()
    return {"total": len(rows), "items": gdzc_rows(db, rows)}


@router.get("/{bfid}")
def get_dan(
    bfid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    dan = db.get(ZcBaofeidan, bfid)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    pics = db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid == bfid).order_by(ZcBaofeitp.id).all()
    return {**dan.to_dict(),
            "images": [{"dizhi": p.dizhi, "url": image_url(p.dizhi, current.id)}
                       for p in pics]}


@router.post("/mx/add")
def add_mx(
    data: MxIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """加入报废:按 zccode 取最新盘点年度行挂单,其它年度行同步标「已报废」。"""
    src = db.get(ZcCw, data.id)
    if src is None:
        raise HTTPException(status_code=404, detail="资产记录不存在")
    dan = db.get(ZcBaofeidan, data.bfid or 0)
    if dan is None:
        raise HTTPException(status_code=404, detail="报废单不存在")
    latest = (db.query(ZcCw).filter(ZcCw.zccode == src.zccode)
              .order_by(ZcCw.nd.desc(), ZcCw.id.desc()).first())
    if latest is None:
        raise HTTPException(status_code=404, detail="未找到资产记录")
    # 补旧代码被注释掉的跨部门校验
    scope = finance_scope_ids(db, current)
    if scope is not None and latest.bmid not in scope:
        raise HTTPException(status_code=403, detail="不能报废其它部门的资产")
    count = db.query(func.count(ZcCw.id)).filter(
        ZcCw.baofeidanid == dan.id).scalar() or 0
    if count > 9:
        raise HTTPException(status_code=400, detail="一张报废单不能超过10条数据。")
    now = datetime.now().replace(microsecond=0)
    latest.baofeidanid = dan.id
    latest.baofeiqk = "已报废"
    latest.baofeicztime = now
    for other in db.query(ZcCw).filter(
            ZcCw.zccode == src.zccode, ZcCw.id != latest.id).all():
        other.baofeiqk = "已报废"
        other.baofeicztime = now
    db.commit()
    return {"ok": True}


@router.post("/mx/delete")
def delete_mx(
    data: MxIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    """取消报废:当前行清挂单,同 zccode 其它年度行清报废标记。"""
    row = db.get(ZcCw, data.id)
    if row is None:
        raise HTTPException(status_code=404, detail="资产记录不存在")
    row.baofeidanid = None
    row.baofeiqk = None
    row.baofeicztime = None
    for other in db.query(ZcCw).filter(
            ZcCw.zccode == row.zccode, ZcCw.id != row.id).all():
        other.baofeiqk = None
        other.baofeicztime = None
        if other.baofeidanid == row.id:   # 兜底:清掉历史脏数据
            other.baofeidanid = None
    db.commit()
    return {"ok": True}
