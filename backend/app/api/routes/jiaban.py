"""维抢修加班 Jiaban(照旧 JiabanController + Views/Jiaban/Index.cshtml 1:1 复刻)。

路由挂 /api/jiaban。旧系统无角色判断、仅菜单控制访问,新系统按约定:
- jiaban:view  模块入口 + 全部日常操作(记录/人员/工单带出/导出/附件);
  删除类操作按旧逻辑限制:加班记录与附件只能删本人录入的(username/operator_name)

复用已有能力,不重造:
- 工单历史记录取 gongdancailiao(app/models/workorder.py,已迁移 19689 行,勿重导)
- 外部工单详情/现场图片走 app/services/workorder_external.py(与 jcxt/gongdan/workorder 同源),
  内网不可达时降级为空数据/透明占位图
- 附件下载走短令牌(⛔登录令牌不放 URL);旧服务器附件文件本机缺失,下载 404 兜底

1:1 差异说明:
- 旧 lei(bit 可空)在新库为 1/0/NULL;筛选口径 address=lei=1、nonaddress=lei=0或NULL
- 时间冲突检测照旧:开始 < 他人结束 且 结束 > 他人开始;结束<=开始按跨天 +1 天
- 导出条件由前端传当前筛选(旧页面即如此,非 TempData)
"""

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.jiaban import Jiaban, JiabanAttachment, JiabanRenyuan
from app.models.user import User
from app.models.workorder import GongdanCailiao
from app.services import workorder_external
from app.services.jiaban_excel import (
    build_by_address, build_by_name, build_for_overtime, build_summary,
)
from app.services.workorder_common import excel_disposition

router = APIRouter()

ATT_TOKEN_MINUTES = 180
FLOW_TIMEOUT = 3  # 工单号失焦即触发,短超时避免卡录入
ATT_MAX_SIZE = 50 * 1024 * 1024  # 照旧 50MB
ATT_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"}
ATT_SUBDIR = "JiabanAttachments"
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fccf00c30f0003050100f9e2fe6e0000000049454e44ae426082"
)


# ==================== 请求体 ====================
class RenyuanIn(BaseModel):
    id: Optional[int] = None
    name: str = ""
    bmlb: str = ""
    danjia: float = 0
    gonghao: Optional[str] = None


class JiabanIn(BaseModel):
    id: Optional[int] = None
    nameids: Optional[str] = None          # 新增:逗号分隔多选
    nameid: Optional[int] = None           # 编辑:单选
    gongdanNo: str = ""
    riqi: str = ""
    dizhi: str = ""
    neirong: str = ""
    kssj: str = ""
    jssj: str = ""
    shijian: float = 0
    beishu: float = 0
    zongshu: float = 0
    lei: bool = False


class IdIn(BaseModel):
    id: int


# ==================== 公共辅助 ====================
def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime((s or "").strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _parse_time(s: str) -> Optional[timedelta]:
    parts = (s or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return timedelta(hours=h, minutes=m)


def _build_times(riqi: str, kssj: str, jssj: str):
    """旧 AddJiaban/UpdateJiaban 的时间解析:失败 err 非空,成功返回 (date, start, end)。"""
    date = _parse_date(riqi)
    if date is None:
        return None, None, None, "日期格式不正确"
    ks, js = _parse_time(kssj), _parse_time(jssj)
    if ks is None or js is None:
        return None, None, None, "时间格式不正确"
    start = date + ks
    end = date + js
    if end <= start:  # 照旧:结束<=开始按跨天 +1 天
        end += timedelta(days=1)
    return date, start, end, ""


def _base_query(db: Session, start: Optional[datetime], end: Optional[datetime],
                mohu: str, bmlb: str, leiType: str):
    """旧 GetRecords/GetJiabanRecords 的联表 + 过滤(列表与导出口径一致)。"""
    q = (db.query(Jiaban, JiabanRenyuan)
         .outerjoin(JiabanRenyuan, Jiaban.nameid == JiabanRenyuan.id))
    if start is not None:
        q = q.filter(Jiaban.riqi >= start)
    if end is not None:
        q = q.filter(Jiaban.riqi <= end)
    kw = (mohu or "").strip()
    if kw:
        q = q.filter(or_(JiabanRenyuan.name.like(f"%{kw}%"),
                         Jiaban.gongdanNo.like(f"%{kw}%"),
                         Jiaban.dizhi.like(f"%{kw}%")))
    arr = [x.strip() for x in (bmlb or "").split(",") if x.strip()]
    if arr:  # 照旧:传"全部"或空=不过滤
        q = q.filter(JiabanRenyuan.bmlb.in_(arr))
    if leiType and leiType != "all":
        if leiType == "address":
            q = q.filter(Jiaban.lei == 1)
        elif leiType == "nonaddress":
            q = q.filter(or_(Jiaban.lei == 0, Jiaban.lei.is_(None)))
    return q


def _range_params(startDate: str, endDate: str):
    """startDate 全天起、endDate 当天 23:59:59(照旧)。"""
    start = _parse_date(startDate)
    end = _parse_date(endDate)
    if end is not None:
        end = end + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def _row_dict(j: Jiaban, r: Optional[JiabanRenyuan]) -> dict:
    return {
        "ID": j.id,
        "nameid": j.nameid,
        "name": (r.name if r else "") or "",
        "bm": (r.bmlb if r else "") or "",
        "riqi": j.riqi.strftime("%Y-%m-%d") if j.riqi else "",
        "gongdanNo": j.gongdanNo or "",
        "kjshijian": j.kjshijian or "",
        "dizhi": j.dizhi or "",
        "neirong": j.neirong or "",
        "shijian": float(j.shijian or 0),
        "beishu": float(j.beishu or 0),
        "zongshu": float(j.zongshu or 0),
        "lei": None if j.lei is None else bool(j.lei),
        "username": j.username or "",
        "createtime": j.createtime.strftime("%Y-%m-%d %H:%M:%S") if j.createtime else "",
        "kstime": j.kstime.strftime("%Y-%m-%d %H:%M:%S") if j.kstime else "",
        "jstime": j.jstime.strftime("%Y-%m-%d %H:%M:%S") if j.jstime else "",
    }


def _export_rows(db: Session, startDate, endDate, mohu, bmlb, leiType) -> list[dict]:
    """旧 GetJiabanRecords:4 个导出共用(排序照旧 kstime → gongdanNo)。"""
    start, end = _range_params(startDate, endDate)
    q = _base_query(db, start, end, mohu, bmlb, leiType)
    rows = []
    for j, r in q.order_by(Jiaban.kstime.asc(), Jiaban.gongdanNo.asc()).all():
        d = _row_dict(j, r)
        d["gonghao"] = (r.gonghao if r else "") or ""
        d["danjia"] = float(r.danjia or 0) if r else 0
        rows.append(d)
    return rows


def _file_response(buf, filename: str) -> Response:
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


# ==================== 列表 ====================
@router.get("/records")
def records(
    startDate: str = "", endDate: str = "", mohu: str = "",
    bmlb: str = "", leiType: str = "all",
    page: int = 1, rows: int = 25,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetRecords:分页 + 全量筛选合计(总时长/总时间数)。"""
    start, end = _range_params(startDate, endDate)
    q = _base_query(db, start, end, mohu, bmlb, leiType)
    total = q.count()
    total_shijian = q.with_entities(
        func.coalesce(func.sum(Jiaban.shijian), 0)).scalar()
    total_zongshu = q.with_entities(
        func.coalesce(func.sum(Jiaban.zongshu), 0)).scalar()
    pairs = (
        q.order_by(JiabanRenyuan.bmlb.asc(), JiabanRenyuan.name.asc(),
                   Jiaban.kstime.asc(), Jiaban.gongdanNo.asc(), Jiaban.id.desc())
        .offset((max(page, 1) - 1) * max(rows, 1)).limit(max(rows, 1)).all()
    )
    return {
        "total": total,
        "rows": [_row_dict(j, r) for j, r in pairs],
        "totalShijian": round(float(total_shijian or 0), 2),
        "totalZongshu": round(float(total_zongshu or 0), 2),
    }


# ==================== 加班人员 ====================
@router.get("/renyuan")
def renyuan_list(
    search: str = "", page: int = 1, rows: int = 10,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetJiabanRenyuan:分页 + 姓名/部门/工号模糊搜索。"""
    q = db.query(JiabanRenyuan)
    kw = (search or "").strip()
    if kw:
        q = q.filter(or_(JiabanRenyuan.name.like(f"%{kw}%"),
                         JiabanRenyuan.bmlb.like(f"%{kw}%"),
                         JiabanRenyuan.gonghao.like(f"%{kw}%")))
    total = q.count()
    items = (q.order_by(JiabanRenyuan.bmlb.asc(), JiabanRenyuan.name.asc())
             .offset((max(page, 1) - 1) * max(rows, 1)).limit(max(rows, 1)).all())
    return {
        "total": total,
        "rows": [{
            "id": r.id, "name": r.name, "bmlb": r.bmlb,
            "danjia": float(r.danjia or 0), "gonghao": r.gonghao or "",
        } for r in items],
    }


@router.get("/renyuan-list")
def renyuan_dropdown(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetJiabanRenyuanList:人员下拉(按姓名排序)。"""
    items = db.query(JiabanRenyuan).order_by(JiabanRenyuan.name.asc()).all()
    return [{"id": r.id, "name": r.name, "bmlb": r.bmlb, "gonghao": r.gonghao or ""}
            for r in items]


@router.get("/bmlb-options")
def bmlb_options(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetBmlbOptions:去重部门类别,升序。"""
    rows = (db.query(JiabanRenyuan.bmlb).distinct()
            .filter(JiabanRenyuan.bmlb.isnot(None), JiabanRenyuan.bmlb != "")
            .order_by(JiabanRenyuan.bmlb.asc()).all())
    return [{"id": r[0], "text": r[0]} for r in rows]


@router.post("/renyuan/add")
def renyuan_add(
    data: RenyuanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 AddJiabanRenyuan:姓名全局查重(不区分大小写)。"""
    name, bmlb = (data.name or "").strip(), (data.bmlb or "").strip()
    if not name or not bmlb:
        raise HTTPException(status_code=400, detail="姓名和部门类别不能为空")
    exists = (db.query(JiabanRenyuan)
              .filter(func.lower(JiabanRenyuan.name) == name.lower()).first())
    if exists:
        raise HTTPException(status_code=400, detail="该姓名已存在，请勿重复添加")
    db.add(JiabanRenyuan(name=name, bmlb=bmlb, danjia=data.danjia,
                         gonghao=(data.gonghao or "").strip() or None))
    db.commit()
    return {"success": True}


@router.post("/renyuan/update")
def renyuan_update(
    data: RenyuanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    item = db.get(JiabanRenyuan, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    name, bmlb = (data.name or "").strip(), (data.bmlb or "").strip()
    if not name or not bmlb:
        raise HTTPException(status_code=400, detail="姓名和部门类别不能为空")
    exists = (db.query(JiabanRenyuan)
              .filter(func.lower(JiabanRenyuan.name) == name.lower(),
                      JiabanRenyuan.id != item.id).first())
    if exists:
        raise HTTPException(status_code=400, detail="该姓名已存在，不能重复")
    item.name = name
    item.bmlb = bmlb
    item.danjia = data.danjia
    item.gonghao = (data.gonghao or "").strip() or None
    db.commit()
    return {"success": True}


@router.post("/renyuan/delete")
def renyuan_delete(
    data: IdIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """照旧物理删除(其名下加班记录的姓名列随联表置空)。"""
    item = db.get(JiabanRenyuan, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    db.delete(item)
    db.commit()
    return {"success": True}


# ==================== 工单号带出 ====================
@router.get("/gongdan-info")
def gongdan_info(
    gongdanNo: str = "", nameid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetGongdanInfo:外部工单 + 查重 + gongdancailiao 工单历史记录。"""
    no = (gongdanNo or "").strip()
    if not no:
        return {"success": False, "msg": "工单号不能为空"}
    res = workorder_external.fetch_workorder(no, timeout=FLOW_TIMEOUT)
    data = res.get("data") if res.get("success") else None
    if not data:
        return {"success": False, "msg": res.get("msg") or "工单不存在"}

    duplicate = False
    duplicate_msg = ""
    if nameid:
        exists = (db.query(Jiaban.id)
                  .filter(Jiaban.gongdanNo == no, Jiaban.nameid == nameid).first())
        if exists:
            duplicate = True
            duplicate_msg = "此工单号已为此人员录入，请勿重复添加"

    recs = (db.query(GongdanCailiao)
            .filter(GongdanCailiao.gongdanhao == no)
            .order_by(GongdanCailiao.ksriqi.desc()).all())
    records = [{
        "ksriqi": r.ksriqi.strftime("%Y-%m-%d %H:%M:%S") if r.ksriqi else "",
        "jsriqi": r.jsriqi.strftime("%Y-%m-%d %H:%M:%S") if r.jsriqi else "",
        "shijian": r.shijian,
        "gongdanhao": r.gongdanhao or "",
        "qiangxiurenyuan": r.qiangxiurenyuan or "",
        "djren": r.djren or "",
        "djriqi": r.djriqi.strftime("%Y-%m-%d %H:%M:%S") if r.djriqi else "",
        "beizhu": r.beizhu or "",
    } for r in recs]

    return {
        "success": True,
        "dizhi": data.get("AddressStr") or "",
        "riqi": data.get("CreateTime") or "",
        "neirong": data.get("Problem") or "",
        "jsriqi": data.get("updateTime") or "",
        "duplicate": duplicate,
        "duplicateMsg": duplicate_msg,
        "records": records,
    }


@router.get("/by-no")
def by_no(
    gongdanNo: str = "",
    current: User = Depends(require_permission("jiaban:view")),
):
    """工单详情抽屉 —— 与 /api/gongdan/by-no 同上游同结构(success/data),换权限码。"""
    if not (gongdanNo or "").strip():
        return {"success": False, "message": "工单号不能为空"}
    res = workorder_external.fetch_workorder(gongdanNo)
    if not res["success"]:
        return {"success": False, "message": res["msg"]}
    return {"success": True, "data": workorder_external.workorder_detail(res["data"] or {})}


@router.get("/images")
def images(
    flow_id: str = "",
    current: User = Depends(require_permission("jiaban:view")),
):
    """现场图片列表(3 槽位 + 短令牌代理,照 /api/gongdan/images)。"""
    res = workorder_external.fetch_workorder_images(flow_id)
    if not res["success"]:
        return {"success": False, "message": res["msg"], "images": []}
    out = []
    for img in res["images"]:
        token = ""
        if img.get("url"):
            token = create_short_token(
                "jiaban_wo_image", {"url": img["url"], "sub": str(current.id)},
                minutes=ATT_TOKEN_MINUTES,
            )
        out.append({
            "kind": img.get("kind"), "label": img.get("label"),
            "token_url": f"/api/jiaban/image?token={token}" if token else "",
        })
    return {"success": True, "images": out}


@router.get("/image")
def image_proxy(token: str = ""):
    """现场图片代理(短令牌),内网不可达返回 1×1 透明占位图。"""
    try:
        payload = decode_short_token(token, "jiaban_wo_image")
    except Exception:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    try:
        data, content_type = workorder_external.fetch_image(payload.get("url", ""))
    except Exception:
        return Response(content=TRANSPARENT_PNG, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


# ==================== 新增 / 编辑 / 删除 ====================
def _conflict_errors(db: Session, nameid: int, start: datetime, end: datetime,
                     exclude_id: Optional[int] = None) -> list[str]:
    """旧冲突口径:开始 < 已有结束 且 结束 > 已有开始(kstime/jstime 为空的记录跳过)。"""
    q = (db.query(Jiaban)
         .filter(Jiaban.nameid == nameid,
                 Jiaban.kstime.isnot(None), Jiaban.jstime.isnot(None),
                 Jiaban.kstime < end, Jiaban.jstime > start))
    if exclude_id:
        q = q.filter(Jiaban.id != exclude_id)
    return [f"与工单【{j.gongdanNo}】时间冲突" for j in q.all()]


@router.post("/add")
def add(
    data: JiabanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 AddJiaban:多人员循环写入,冲突者跳过,一次性提交。"""
    id_list = []
    for part in (data.nameids or "").split(","):
        part = part.strip()
        if part:
            try:
                id_list.append(int(part))
            except ValueError:
                raise HTTPException(status_code=400, detail="人员参数不合法")
    if not id_list:
        raise HTTPException(status_code=400, detail="请选择人员")
    date, start, end, err = _build_times(data.riqi, data.kssj, data.jssj)
    if err:
        raise HTTPException(status_code=400, detail=err)

    errors: list[str] = []
    success_count = 0
    for nameid in id_list:
        person = db.get(JiabanRenyuan, nameid)
        if person is None:
            errors.append(f"人员ID【{nameid}】不存在")
            continue
        conflicts = _conflict_errors(db, nameid, start, end)
        if conflicts:
            errors.append(f"【{person.name}】{conflicts[0]}")
            continue
        db.add(Jiaban(
            nameid=nameid, riqi=date, gongdanNo=(data.gongdanNo or "").strip(),
            kjshijian=f"{data.kssj.strip()}-{data.jssj.strip()}",
            dizhi=data.dizhi or "", neirong=data.neirong or "",
            shijian=data.shijian, beishu=data.beishu, zongshu=data.zongshu,
            username=current.username, createtime=datetime.now(),
            kstime=start, jstime=end, lei=1 if data.lei else 0,
        ))
        success_count += 1
    db.commit()
    return {
        "success": success_count > 0,
        "msg": f"成功{success_count}条，失败{len(errors)}条",
        "successCount": success_count,
        "failCount": len(errors),
        "errors": errors,
    }


@router.post("/update")
def update(
    data: JiabanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 UpdateJiaban:单人员;编辑后录入人变为当前用户(照旧赋 username)。"""
    item = db.get(Jiaban, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    if not data.nameid:
        raise HTTPException(status_code=400, detail="请选择人员")
    date, start, end, err = _build_times(data.riqi, data.kssj, data.jssj)
    if err:
        raise HTTPException(status_code=400, detail=err)
    conflicts = _conflict_errors(db, data.nameid, start, end, exclude_id=item.id)
    if conflicts:
        return {"success": False, "msg": conflicts[0]}

    item.nameid = data.nameid
    item.gongdanNo = (data.gongdanNo or "").strip()
    item.riqi = date
    item.dizhi = data.dizhi or ""
    item.neirong = data.neirong or ""
    item.kjshijian = f"{data.kssj.strip()}-{data.jssj.strip()}"
    item.shijian = data.shijian
    item.beishu = data.beishu
    item.zongshu = data.zongshu
    item.username = current.username
    item.kstime = start
    item.jstime = end
    item.lei = 1 if data.lei else 0
    db.commit()
    return {"success": True}


@router.post("/delete")
def delete(
    data: IdIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 DeleteJiaban:只能删自己录入的记录。"""
    item = db.get(Jiaban, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    if item.username != current.username:
        return {"success": False, "msg": "只能删除自己录入的记录"}
    db.delete(item)
    db.commit()
    return {"success": True}


# ==================== 4 个导出 ====================
@router.get("/export")
def export_excel(
    startDate: str = "", endDate: str = "", mohu: str = "",
    bmlb: str = "", remark: str = "", leiType: str = "all",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 ExportExcelNpoi:按姓名分 Sheet 的加班审批表(带备注/截止日期)。"""
    rows = _export_rows(db, startDate, endDate, mohu, bmlb, leiType)
    if not rows:
        return {"success": False, "msg": "没有符合条件的数据可导出"}
    end_date = _parse_date(endDate)
    buf = build_by_name(rows, remark, end_date)
    return _file_response(buf, f"加班记录_按姓名_{datetime.now():%Y%m%d%H%M%S}.xlsx")


@router.get("/export-by-address")
def export_by_address(
    startDate: str = "", endDate: str = "", mohu: str = "",
    bmlb: str = "", remark: str = "", leiType: str = "all",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 ExportByAddress:按工单号分 Sheet 的加班审批表。"""
    rows = _export_rows(db, startDate, endDate, mohu, bmlb, leiType)
    if not rows:
        return {"success": False, "msg": "没有符合条件的数据可导出"}
    buf = build_by_address(rows, remark)
    return _file_response(buf, f"加班审批表_{datetime.now():%Y%m%d%H%M%S}.xlsx")


@router.get("/export-summary")
def export_summary(
    startDate: str = "", endDate: str = "", mohu: str = "",
    bmlb: str = "", leiType: str = "all",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 ExportSummaryExcelNpoi:按人员汇总的加班工资报销表(人民币大写)。"""
    rows = _export_rows(db, startDate, endDate, mohu, bmlb, leiType)
    if not rows:
        return {"success": False, "msg": "没有符合条件的数据可导出"}
    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r["nameid"], r["name"], r["danjia"], r["bm"])
        g = groups.setdefault(key, {
            "name": r["name"] or "未知", "danjia": r["danjia"],
            "totalHours": 0.0, "bmlb": r["bm"] or "",
        })
        g["totalHours"] += r["zongshu"]
    items = sorted(groups.values(), key=lambda g: (g["bmlb"], g["name"]))
    if (bmlb or "").strip() and bmlb.strip() != "全部":
        show_dept = bmlb.replace(",", "、")
    else:
        show_dept = "全部部门"
    buf = build_summary(items, show_dept, current.username)
    return _file_response(buf, f"加班工资汇总表_{datetime.now():%Y%m%d%H%M%S}.xlsx")


@router.get("/export-for-overtime")
def export_for_overtime(
    startDate: str = "", endDate: str = "", mohu: str = "",
    bmlb: str = "", leiType: str = "all",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 ExportForOvertimeApply:14 列格式匹配加班申请"批量导入"模板。"""
    rows = [r for r in _export_rows(db, startDate, endDate, mohu, bmlb, leiType)
            if r["gonghao"] and r["name"] and r["kstime"] and r["jstime"]]
    if not rows:
        return {"success": False, "msg": "没有符合条件的数据可导出"}
    buf = build_for_overtime(rows)
    return _file_response(buf, f"维抢修加班_导出_{datetime.now():%Y%m%d%H%M%S}.xlsx")


# ==================== 附件管理 ====================
def _att_root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def _att_path(rel: str) -> Path:
    """兼容新旧两种相对路径:新 uuid 路径直接拼;旧 '~/Uploads/...' 剥掉前缀。"""
    raw = (rel or "").replace("\\", "/").strip()
    if raw.startswith("~/Uploads/"):
        raw = raw[len("~/Uploads/"):]
    raw = raw.lstrip("/")
    base = _att_root()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="附件路径不合法")
    return path


def _size_str(size) -> str:
    n = int(size or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _att_token(file_id: int, current: User) -> str:
    return create_short_token(
        "jiaban_attach", {"fid": file_id, "sub": str(current.id)},
        minutes=ATT_TOKEN_MINUTES,
    )


@router.get("/attachments")
def attachments(
    year: Optional[int] = None, month: Optional[int] = None,
    page: int = 1, rows: int = 25,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 GetAttachments:按年月筛选,上传时间倒序。"""
    q = db.query(JiabanAttachment)
    if year and month:
        start = datetime(year, month, 1)
        nxt = datetime(year + (month // 12), (month % 12) + 1, 1)
        q = q.filter(JiabanAttachment.jiabanDate >= start,
                     JiabanAttachment.jiabanDate < nxt)
    total = q.count()
    items = (q.order_by(JiabanAttachment.uploadTime.desc())
             .offset((max(page, 1) - 1) * max(rows, 1)).limit(max(rows, 1)).all())
    return {
        "total": total,
        "rows": [{
            "id": a.id,
            "jiabanDate": a.jiabanDate.strftime("%Y-%m") if a.jiabanDate else "",
            "file_name": a.file_name or "",
            "fileSize": a.fileSize or 0,
            "fileSizeStr": _size_str(a.fileSize),
            "uploadTime": a.uploadTime.strftime("%Y-%m-%d %H:%M:%S") if a.uploadTime else "",
            "operator_name": a.operator_name or "",
            "canDelete": a.operator_name == current.username or current.is_superuser,
            "downloadUrl": f"/api/jiaban/attachments/download?token={_att_token(a.id, current)}",
        } for a in items],
    }


@router.post("/attachments/upload")
def attachments_upload(
    year: int, month: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 UploadAttachment:白名单 pdf/图片,单文件 ≤ 50MB,按年月归档。"""
    content = file.file.read()
    ext = Path(file.filename or "").suffix.lower()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > ATT_MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过50MB")
    if ext not in ATT_ALLOWED_EXTS:
        raise HTTPException(status_code=400,
                            detail="只允许上传PDF和图片文件（pdf/jpg/jpeg/png/gif/bmp）")
    target_dir = _att_root() / ATT_SUBDIR / f"{year}" / f"{month:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (target_dir / stored).write_bytes(content)
    rel = f"{ATT_SUBDIR}/{year}/{month:02d}/{stored}"
    db.add(JiabanAttachment(
        jiabanDate=datetime(year, month, 1),
        file_name=Path(file.filename or stored).name,
        filePath=rel, fileSize=len(content),
        uploadTime=datetime.now(), operator_name=current.username,
    ))
    db.commit()
    return {"success": True, "msg": "上传成功", "fileName": Path(file.filename or "").name}


@router.post("/attachments/delete")
def attachments_delete(
    data: IdIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiaban:view")),
):
    """旧 DeleteAttachment:只能删自己上传的附件;同时删磁盘文件(缺失不报错)。"""
    item = db.get(JiabanAttachment, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    if item.operator_name != current.username and not current.is_superuser:
        return {"success": False, "msg": "只能删除自己上传的附件"}
    try:
        _att_path(item.filePath).unlink(missing_ok=True)
    except HTTPException:
        pass
    db.delete(item)
    db.commit()
    return {"success": True}


@router.get("/attachments/download")
def attachments_download(
    token: str = "",
    inline: int = 0,
    db: Session = Depends(get_db),
):
    """短令牌下载:window.open 无法带 Authorization,令牌 180 分钟有效(照 workorder)。

    inline=1 时按扩展名返回真实 Content-Type 且不强制下载,供前端图片浏览窗 <img> 使用。
    """
    try:
        payload = decode_short_token(token, "jiaban_attach")
    except Exception:
        raise HTTPException(status_code=401, detail="下载令牌无效或已过期")
    item = db.get(JiabanAttachment, int(payload.get("fid") or 0))
    if item is None:
        return {"success": False, "msg": "文件不存在"}
    path = _att_path(item.filePath)
    if not path.is_file():
        return {"success": False, "msg": "文件已被删除"}
    filename = quote(item.file_name or "附件")
    if inline:
        ext = path.suffix.lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".gif": "image/gif", ".bmp": "image/bmp",
                 ".pdf": "application/pdf"}.get(ext, "application/octet-stream")
        return FileResponse(
            path, media_type=media,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
        )
    return FileResponse(
        path, media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
