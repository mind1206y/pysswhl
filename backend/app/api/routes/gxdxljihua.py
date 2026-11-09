"""正式计划(gxdxljihua)接口:照旧 gxdxljihuaController 复刻。

- 列表:年度/类别/部门/主办/专管员多选/关键字 + 未完成/已完成/未关注/质保金/考核开关
- 关注/取消关注、添加进度(含图片)、项目备注/专管员/考核标记/质保金
- 进度看板(按月聚合/按日明细)
- 复制到待办计划申报、导出计划与年度进度

权限:plan:view(入口/查询/导出) + plan:manage(全部写操作)。
"""

import os
import uuid
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.plan import GxGxgz, GxJilu, GxJiluTupian, GxJindu, GxUserGxgz, JhSsdb, JhYyfq
from app.models.user import Department, User
from app.services.plan_common import (
    JHLB_OPTIONS, MIDDLE_CATEGORIES, STATUS_TODO, dept_options, official_query,
    official_rows, official_totals, plan_year, progress_maps, zgy_options,
)
from app.services.plan_excel import export_official, export_progress, to_bytes
from app.services.plan_common import get_lock, set_lock, LOCK_APPLY  # noqa: F401

router = APIRouter()
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "uploads", "plan")
ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
MAX_SIZE = 10 * 1024 * 1024


def _ids(value) -> list[int]:
    if isinstance(value, list):
        return [int(x) for x in value if str(x).strip()]
    return [int(x) for x in str(value or "").split(",") if x.strip()]


def _pct(value):
    return value if value not in (None, -1) else None


class IdsIn(BaseModel):
    ids: List[int]


class RemarkIn(BaseModel):
    id: int
    remark: str = ""


class ZgyIn(BaseModel):
    id: int
    zgy: str = ""


class KhbjIn(BaseModel):
    id: int


class ZbjIn(BaseModel):
    id: int
    zbj: Optional[float] = None
    zbjrq: Optional[str] = None


class CopyIn(BaseModel):
    ids: List[int]
    target: str = ""  # todo / apply;空则按权限自动判断


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    years = [r[0] for r in db.query(GxGxgz.nd).filter(GxGxgz.nd.isnot(None)).distinct().all()]
    years = sorted({int(y) for y in years if y}, reverse=True)
    cur_year = plan_year()
    if cur_year not in years:
        years.insert(0, cur_year)
    # 当前计划年度还没有正式计划时,默认落到最近有数据的年度,避免首屏空白
    default_year = cur_year if any(y == cur_year for y in years) and db.query(GxGxgz.id).filter(GxGxgz.nd == cur_year).first() else (years[1] if years and years[0] == cur_year and len(years) > 1 else cur_year)
    hosts = [r[0] for r in db.query(GxGxgz.zb).filter(GxGxgz.zb.isnot(None), GxGxgz.zb != "").distinct().all()]
    jindu = [
        j.to_dict() for j in db.query(GxJindu)
        .filter(GxJindu.value.isnot(None), GxJindu.value >= 10, GxJindu.value <= 100)
        .order_by(GxJindu.value).all()
    ]
    all_jindu = [j.to_dict() for j in db.query(GxJindu).order_by(GxJindu.value).all()]
    return {
        "years": years,
        "default_year": default_year,
        "departments": dept_options(db, current),
        "hosts": sorted(hosts),
        "zgys": zgy_options(db),
        "categories": JHLB_OPTIONS,
        "jindu": jindu,
        "all_jindu": all_jindu,
        "perms": {"view": True, "manage": True},
    }


@router.get("/list")
def list_plans(
    page: int = 1,
    size: int = 25,
    nd: Optional[int] = None,
    lb: str = "",
    mohu: str = "",
    zgy_list: str = "",
    bmid: Optional[int] = None,
    zb: str = "",
    px: bool = True,
    ck: bool = False,
    ywc: bool = False,
    GZck: bool = False,
    ifzbj: bool = False,
    khbj: bool = False,
    gxgzid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    if not nd and not mohu:
        nd = plan_year()
    if not lb:
        lb = "更新改造"
    q = official_query(
        db, current, nd=nd, lb=lb, mohu=mohu, zgy_list=zgy_list, bmid=bmid, zb=zb,
        px=px, unfinished=ck, finished=ywc, unfollowed=GZck, zbj_only=ifzbj,
        khbj_only=khbj, gxgzid=gxgzid,
    )
    total = q.count()
    plans = q.offset((page - 1) * size).limit(size).all()
    rows = official_rows(db, plans, current)
    totals = official_totals(db, q)
    footer = [{
        "bz": "合计",
        "jine": totals["footerJine"],
        "zongji": totals["footerZongji"],
        "numb": None,
    }]
    return {"rows": rows, "total": total, "footer": footer, **totals}


@router.post("/follow")
def follow(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    added = 0
    for gzid in data.ids:
        plan = db.get(GxGxgz, gzid)
        if plan is None:
            continue
        exists = db.query(GxUserGxgz.id).filter(
            GxUserGxgz.gxgzid == gzid, GxUserGxgz.userid == current.id
        ).first()
        if exists:
            continue
        db.add(GxUserGxgz(userid=current.id, gxgzid=gzid, username=current.username))
        added += 1
    db.commit()
    return {"ok": True, "added": added}


@router.post("/unfollow")
def unfollow(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请选择要取消关注的计划")
    follows = db.query(GxUserGxgz).filter(
        GxUserGxgz.gxgzid.in_(data.ids), GxUserGxgz.userid == current.id,
    ).all()
    for f in follows:
        jilus = db.query(GxJilu).filter(GxJilu.guanzhuid == f.id).all()
        jids = [j.id for j in jilus]
        if jids:
            db.query(GxJiluTupian).filter(GxJiluTupian.jiuid.in_(jids)).delete(synchronize_session=False)
            db.query(GxJilu).filter(GxJilu.id.in_(jids)).delete(synchronize_session=False)
        db.delete(f)
    db.commit()
    return {"ok": True, "removed": len(follows)}


@router.get("/progress/{gzid}")
def get_progress(
    gzid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    rows = (
        db.query(GxJilu, GxUserGxgz.username, GxJindu.leixing, GxJindu.value)
        .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
        .outerjoin(GxJindu, GxJilu.zhuangtaiid == GxJindu.id)
        .filter(GxUserGxgz.gxgzid == gzid)
        .order_by(GxJilu.riqi.asc(), GxJilu.id.asc())
        .all()
    )
    pic_map = {}
    if rows:
        jids = [r[0].id for r in rows]
        for p in db.query(GxJiluTupian).filter(GxJiluTupian.jiuid.in_(jids)).all():
            pic_map.setdefault(p.jiuid, []).append({"id": p.id, "url": p.url, "missing": bool(p.url and p.url.startswith("~"))})
    items = []
    for j, username, leixing, value in rows:
        items.append({
            "id": j.id,
            "miaoshu": j.miaoshu or "",
            "beizhu": j.beizhu or "",
            "leixing": leixing or "",
            "value": value,
            "riqi": j.riqi.strftime("%Y-%m-%d") if j.riqi else "",
            "caozuotime": j.caozuotime.strftime("%Y-%m-%d %H:%M:%S") if j.caozuotime else "",
            "fukuan": j.fukuan,
            "username": username or "",
            "tps": pic_map.get(j.id, []),
        })
    return {"rows": items, "total": len(items)}


@router.post("/progress")
def add_progress(
    gzid: int = Form(...),
    guanzhuid: int = Form(0),
    riqi: str = Form(""),
    zhuangtaiid: int = Form(0),
    miaoshu: str = Form(""),
    fukuan: float = Form(0),
    beizhu: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    plan = db.get(GxGxgz, gzid)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    follow = None
    if guanzhuid:
        follow = db.get(GxUserGxgz, guanzhuid)
        if follow is None or follow.gxgzid != gzid:
            raise HTTPException(status_code=400, detail="关注记录无效")
        if follow.userid != current.id and not current.is_superuser:
            raise HTTPException(status_code=403, detail="只能为自己的关注添加进度")
    else:
        follow = db.query(GxUserGxgz).filter(
            GxUserGxgz.gxgzid == gzid, GxUserGxgz.userid == current.id
        ).first()
        if follow is None:
            follow = GxUserGxgz(userid=current.id, gxgzid=gzid, username=current.username)
            db.add(follow)
            db.flush()
    jd = db.get(GxJindu, zhuangtaiid) if zhuangtaiid else None
    day = None
    if riqi:
        try:
            day = date.fromisoformat(riqi[:10])
        except ValueError:
            day = None
    record = GxJilu(
        miaoshu=miaoshu or "", beizhu=beizhu or "", riqi=day or date.today(),
        caozuotime=datetime.now(), guanzhuid=follow.id,
        zhuangtaiid=zhuangtaiid or None, fukuan=fukuan or 0,
    )
    db.add(record)
    db.flush()
    if jd and jd.leixing:
        plan.rongyu = jd.leixing
    for f in files or []:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED:
            continue
        content = f.file.read(MAX_SIZE + 1)
        if len(content) > MAX_SIZE:
            continue
        folder = os.path.join(UPLOAD_DIR, str(record.id))
        os.makedirs(folder, exist_ok=True)
        name = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(folder, name), "wb") as out:
            out.write(content)
        db.add(GxJiluTupian(url=f"{record.id}/{name}", jiuid=record.id))
    db.commit()
    return {"ok": True, "id": record.id}


@router.get("/photo/{pic_id}")
def get_photo(
    pic_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    pic = db.get(GxJiluTupian, pic_id)
    if pic is None or not pic.url:
        raise HTTPException(status_code=404, detail="附件不存在")
    if pic.url.startswith("~") or pic.url.startswith("http"):
        raise HTTPException(status_code=404, detail="附件文件缺失(旧系统物理文件未迁移)")
    path = os.path.join(UPLOAD_DIR, pic.url.replace("/", os.sep))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="附件文件缺失")
    return FileResponse(path)


@router.post("/remark")
def update_remark(
    data: RemarkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    plan = db.get(GxGxgz, data.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    plan.xmbz = data.remark
    db.commit()
    return {"ok": True}


@router.post("/zgy")
def update_zgy(
    data: ZgyIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    plan = db.get(GxGxgz, data.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    plan.zgy = (data.zgy or "").strip()
    db.commit()
    return {"ok": True}


@router.post("/khbj")
def toggle_khbj(
    data: KhbjIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    plan = db.get(GxGxgz, data.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    plan.khbj = not bool(plan.khbj)
    db.commit()
    return {"ok": True, "khbj": bool(plan.khbj)}


@router.post("/zbj")
def save_zbj(
    data: ZbjIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    plan = db.get(GxGxgz, data.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    if plan.zbjdjr and plan.zbjdjr != current.username:
        raise HTTPException(status_code=403, detail="非登记人无法修改")
    if data.zbj is None or not data.zbjrq:
        plan.zbjdjr = None
    else:
        plan.zbjdjr = current.username
    plan.zbj = data.zbj
    try:
        plan.zbjrq = date.fromisoformat(data.zbjrq[:10]) if data.zbjrq else None
    except ValueError:
        plan.zbjrq = None
    plan.zbjdjriqi = datetime.now()
    db.commit()
    return {"ok": True}


@router.post("/copy-to-todo")
def copy_to_todo(
    data: CopyIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请选择要复制的计划")
    names = dept_name_map(db)
    name_to_id = {v: k for k, v in names.items()}
    target = data.target
    if not target:
        target = "todo" if any(p.code == "jhssdb:manage" for r in current.roles for p in r.permissions) else "apply"
    count = 0
    for pid in data.ids:
        plan = db.get(GxGxgz, pid)
        if plan is None:
            continue
        if target == "todo":
            db.add(JhSsdb(
                xuhao=plan.xh, daibanname=plan.name or "", bz=plan.bz or "",
                bumenid=plan.bmid or 0, zb=name_to_id.get(plan.zb or ""),
                jhlb=plan.lb or "", niandu=plan_year(),
                jine=(plan.jine or 0) / 10000, lastop=current.username,
                kstimep=datetime.now(), opname=current.username, dbtimep=datetime.now(),
                zhuanguan=current.id, zhuanguan_name=current.username,
                zt=STATUS_TODO, fzr=plan.fzr or "",
            ))
        else:
            db.add(JhYyfq(
                zt="提交审核", fqtimep=datetime.now(), beginTime=datetime.now(),
                opid=current.id, opname=current.username, niandu=plan_year(),
                bmid=plan.bmid, lastop=current.username, bz=plan.bz or "",
                faqiname=plan.name or "", jine=(plan.jine or 0) / 10000,
                jhlb=plan.lb or "",
            ))
        count += 1
    db.commit()
    return {"ok": True, "copied": count, "target": target}


@router.get("/calendar")
def calendar(
    year: int,
    month: int,
    date_text: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    if date_text:
        from datetime import timedelta
        try:
            day = date.fromisoformat(date_text[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
        rows = (
            db.query(GxJilu, GxUserGxgz.gxgzid, GxGxgz.name, GxGxgz.xh, GxGxgz.lb,
                     GxGxgz.bm, GxJindu.leixing, GxUserGxgz.username)
            .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
            .join(GxGxgz, GxUserGxgz.gxgzid == GxGxgz.id)
            .outerjoin(GxJindu, GxJilu.zhuangtaiid == GxJindu.id)
            .filter(GxJilu.riqi >= day, GxJilu.riqi < day + timedelta(days=1))
            .order_by(GxJilu.riqi, GxJilu.id)
            .all()
        )
        items = [{
            "id": j.id, "gxgzid": gzid, "planName": name or "", "xh": xh or "",
            "lb": lb or "", "bm": bm or "", "leixing": lx or "",
            "miaoshu": j.miaoshu or "", "fukuan": j.fukuan,
            "caozuoren": uname or "",
            "caozuotime": j.caozuotime.strftime("%Y-%m-%d %H:%M:%S") if j.caozuotime else "",
        } for j, gzid, name, xh, lb, bm, lx, uname in rows]
        return {"success": True, "items": items}

    from datetime import timedelta
    begin = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)
    raw = (
        db.query(GxJilu.riqi, GxJindu.leixing)
        .outerjoin(GxJindu, GxJilu.zhuangtaiid == GxJindu.id)
        .filter(GxJilu.riqi.isnot(None), GxJilu.riqi >= begin, GxJilu.riqi < end)
        .all()
    )
    counters = {}
    for d, lx in raw:
        key = d.strftime("%Y-%m-%d") if d else ""
        if not key:
            continue
        item = counters.setdefault(key, {"count": 0, "summary": lx or ""})
        item["count"] += 1
        if not item["summary"]:
            item["summary"] = lx or ""
    return {"success": True, "dateMap": counters}


@router.get("/export")
def export_plan(
    nd: Optional[int] = None,
    lb: str = "",
    mohu: str = "",
    zgy_list: str = "",
    bmid: Optional[int] = None,
    zb: str = "",
    px: bool = True,
    ck: bool = False,
    ywc: bool = False,
    GZck: bool = False,
    ifzbj: bool = False,
    khbj: bool = False,
    gxgzid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    if not nd and not mohu:
        nd = plan_year()
    if not lb:
        lb = "更新改造"
    q = official_query(
        db, current, nd=nd, lb=lb, mohu=mohu, zgy_list=zgy_list, bmid=bmid, zb=zb,
        px=px, unfinished=ck, finished=ywc, unfollowed=GZck, zbj_only=ifzbj,
        khbj_only=khbj, gxgzid=gxgzid,
    )
    rows = official_rows(db, q.all(), current)
    data = export_official(rows, nd, lb)
    year_label = str(nd or (rows[0].get("nd") if rows else "") or "")
    fname = f"{year_label + '年度' if year_label else ''}{lb}正式计划.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@router.get("/export-progress")
def export_progress_excel(
    nd: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("plan:view")),
):
    nd = nd or plan_year()
    rows = (
        db.query(GxJilu, GxUserGxgz.gxgzid, GxGxgz.name, GxGxgz.nd, GxGxgz.bm,
                 GxGxgz.zb, GxGxgz.xmbz, GxJindu.leixing, GxUserGxgz.username)
        .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
        .join(GxGxgz, GxUserGxgz.gxgzid == GxGxgz.id)
        .outerjoin(GxJindu, GxJilu.zhuangtaiid == GxJindu.id)
        .filter(GxGxgz.nd == nd)
        .order_by(GxGxgz.name, GxJilu.riqi)
        .all()
    )
    items = [{
        "plan_name": name or "", "nd": plan_nd, "bm": bm or "", "zb": zb or "",
        "riqi": j.riqi.strftime("%Y-%m-%d") if j.riqi else "", "leixing": lx or "",
        "miaoshu": j.miaoshu or "", "fukuan": j.fukuan, "beizhu": j.beizhu or "",
        "username": uname or "",
        "caozuotime": j.caozuotime.strftime("%Y-%m-%d %H:%M") if j.caozuotime else "",
        "xmbz": xmbz or "",
    } for j, _gzid, name, plan_nd, bm, zb, xmbz, lx, uname in rows]
    data = export_progress(items)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''%E5%B9%B4%E5%BA%A6%E8%BF%9B%E5%BA%A6%E6%98%8E%E7%BB%86.xlsx"},
    )
