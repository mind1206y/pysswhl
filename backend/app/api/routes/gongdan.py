"""工单信息录入 Gongdan(照旧 GongdanController + Views/Gongdan/Index.cshtml 1:1 复刻)。

路由挂 /api/gongdan。旧页面无任何角色判断、仅由菜单控制访问,新系统按项目约定:
- gongdan:view   模块入口 + 查询/导出/新增/编辑/字典删选项/抢修班组增删改/工单号带出/详情抽屉
- gongdan:manage 物理删除工单材料记录(不可恢复),超管自动拥有;后端独立校验 403

复用已有能力,不重造:
- 主表 gongdancailiao(app/models/workorder.py)已由 import_workorder.py 迁移 19689 行,勿重导
- 抢修班组 qiangxiurenyuan(app/models/road_repair.py)与工单领料模块共用
- 领料明细取 work_order + material_record + material_library(材料库已迁移)
- 外部工单详情/现场图片走 app/services/workorder_external.py(与 jcxt、workorder 同源),
  内网不可达时降级为空数据/透明占位图

差异(统一在新系统约定内):
- 部门范围用 dept_scope_ids 子树(旧 bb_bumen.cj 前缀),bmid 精确筛选放在分页前(旧服务放在分页后)
- 导出改为前端传当前筛选条件(旧依赖 TempData 缓存上次查询)
- 日期控件用 el-date-picker(datetime)替代旧 datebox + 自绘时:分格子,提交值同为 yyyy-MM-dd HH:mm:ss
- 标题显示当前可见记录数(旧 startExcelProgress 想写 #biaoti 但元素不存在,属死代码)
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.gongdan import Gongdan, GongdanCaizhiDict, GongdanNeirongDict
from app.models.road_repair import Qiangxiurenyuan
from app.models.user import Department, User
from app.models.workorder import GongdanCailiao
from app.services import workorder_external
from app.services.gongdan_common import (
    DN_OPTIONS, TINGSHUI_OPTIONS, SearchParams, build_query, date_bounds,
    dict_options, material_text, order_detail_rows, parse_dt,
    parse_pipe_size, row_dict, s, scoped, upsert_dict,
)
from app.services.gongdan_excel import build_export
from app.services.workorder_common import excel_disposition

router = APIRouter()

IMAGE_TOKEN_MINUTES = 180
FLOW_TIMEOUT = 3  # 工单号失焦即触发,短超时避免卡录入
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fccf00c30f0003050100f9e2fe6e0000000049454e44ae426082"
)


# ==================== 请求体 ====================
class GongdanIn(BaseModel):
    id: Optional[int] = None
    gongdanhao: str = ""
    neirong: str = ""
    ksriqi: str = ""
    jsriqi: str = ""
    shijian: Optional[int] = None
    tingshui: str = ""
    dizhi: str = ""
    caizhi: str = ""
    guanjing: str = ""
    shuiliang: Optional[int] = None
    cailiao: str = ""
    shuliang: str = ""
    qiangxiurenyuan: str = ""
    beizhu: str = ""
    bmid: Optional[int] = None


class DictDeleteIn(BaseModel):
    value: str = ""


class QiangxiuIn(BaseModel):
    id: Optional[int] = None
    name: str = ""


# ==================== 公共辅助 ====================
def _has_manage(current: User) -> bool:
    if current.is_superuser:
        return True
    return "gongdan:manage" in {p.code for role in current.roles for p in role.permissions}


def _default_bmid(db: Session, current: User, requested: Optional[int]) -> Optional[int]:
    """新增记录归属部门:多部门用户可在本人部门内自选,越界兜底第一个,超管自由选。"""
    scope = dept_scope_ids(db, current)
    if scope is None:
        if requested:
            return requested
        return current.departments[0].id if current.departments else None
    if requested and requested in scope:
        return requested
    return min(scope)


def _params(rq: str, rqend: str, mohu: str, minPipe, maxPipe,
            anbjriqi: str, cf: str, fcf: str, bmid) -> SearchParams:
    return SearchParams(rq=rq, rqend=rqend, mohu=mohu, minPipe=minPipe,
                        maxPipe=maxPipe, anbjriqi=anbjriqi, cf=cf, fcf=fcf, bmid=bmid)


def _ensure_visible(db: Session, current: User, item: GongdanCailiao):
    scope = scoped(db, current)
    if scope is not None and item.bmid not in scope:
        raise HTTPException(status_code=403, detail="无权操作其它部门的工单记录")


def _ensure_qx_visible(db: Session, current: User, item: Qiangxiurenyuan):
    scope = scoped(db, current)
    if scope is not None and item.bmid not in scope:
        raise HTTPException(status_code=403, detail="无权操作其它部门的抢修班组")


# ==================== 字典 / 初始化 ====================
@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    scope = scoped(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    names = dept_name_map(db)
    qx = db.query(Qiangxiurenyuan)
    if scope is not None:
        qx = qx.filter(Qiangxiurenyuan.bmid.in_(scope))
    ksd, jsd = date_bounds(SearchParams())
    total = db.query(GongdanCailiao)
    if scope is not None:
        total = total.filter(GongdanCailiao.bmid.in_(scope))
    return {
        "departments": [{"id": d.id, "bm": names.get(d.id, d.name)}
                        for d in dq.order_by(Department.id).all()],
        "banzu": [{"id": r.id, "name": s(r.name)}
                  for r in qx.order_by(Qiangxiurenyuan.name).all()],
        "guanjing": DN_OPTIONS,
        "tingshui": TINGSHUI_OPTIONS,
        "defaultRq": ksd.strftime("%Y-%m-%d"),
        "defaultRqend": jsd.strftime("%Y-%m-%d"),
        "recordCount": total.count(),
        "perms": {"view": True, "manage": _has_manage(current)},
    }


@router.get("/departments")
def departments(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    """旧 GetDepartments(按名称排序),保留独立接口便于 1:1 对照。"""
    scope = scoped(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    names = dept_name_map(db)
    out = [{"id": d.id, "bm": names.get(d.id, d.name)} for d in dq.all()]
    return sorted(out, key=lambda d: d["bm"])


@router.get("/count")
def count(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    """旧 GetGongdanCount:返回热线工单本地镜像表计数(⛔不与 flow 工单混用)。"""
    return {"count": db.query(Gongdan).count()}


# ==================== 列表 / 导出 ====================
@router.get("/list")
def list_rows(
    page: int = 1, rows: int = 30, size: int = 0,
    rq: str = "", rqend: str = "", mohu: str = "",
    minPipe: Optional[int] = None, maxPipe: Optional[int] = None,
    anbjriqi: str = "", cf: str = "", fcf: str = "", bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    p = _params(rq, rqend, mohu, minPipe, maxPipe, anbjriqi, cf, fcf, bmid)
    q = build_query(db, current, p)
    total = q.count()
    page_size = size if size else rows
    data = (
        q.order_by(GongdanCailiao.ksriqi.desc(), GongdanCailiao.id.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1)).limit(max(page_size, 1)).all()
    )
    return {"rows": [row_dict(r) for r in data], "total": total}


@router.get("/export")
def export_excel(
    rq: str = "", rqend: str = "", mohu: str = "",
    minPipe: Optional[int] = None, maxPipe: Optional[int] = None,
    anbjriqi: str = "", cf: str = "", fcf: str = "", bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    """导出当前筛选全量 20 列(旧导出依赖 TempData 里的上次查询条件)。"""
    p = _params(rq, rqend, mohu, minPipe, maxPipe, anbjriqi, cf, fcf, bmid)
    data = build_query(db, current, p).order_by(
        GongdanCailiao.ksriqi.desc(), GongdanCailiao.id.desc()
    ).all()
    buf = build_export([row_dict(r) for r in data])
    filename = f"工单材料数据_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": excel_disposition(filename)},
    )


# ==================== 下拉字典 ====================
@router.get("/neirong")
def search_neirong(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    return dict_options(db, GongdanNeirongDict, GongdanNeirongDict.neirong, q)


@router.post("/neirong/delete")
def delete_neirong(
    data: DictDeleteIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    if not (data.value or "").strip():
        raise HTTPException(status_code=400, detail="工作内容不能为空")
    row = db.query(GongdanNeirongDict).filter(
        GongdanNeirongDict.neirong == data.value.strip()).first()
    if row:
        db.delete(row)
        db.commit()
    return {"success": True}


@router.get("/caizhi")
def search_caizhi(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    # 旧 SearchCaizhi 首行固定插入空项
    return dict_options(db, GongdanCaizhiDict, GongdanCaizhiDict.caizhi, q,
                        blank_first=True)


@router.post("/caizhi/delete")
def delete_caizhi(
    data: DictDeleteIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    if not (data.value or "").strip():
        raise HTTPException(status_code=400, detail="材质不能为空")
    row = db.query(GongdanCaizhiDict).filter(
        GongdanCaizhiDict.caizhi == data.value.strip()).first()
    if row:
        db.delete(row)
        db.commit()
    return {"success": True}


# ==================== 抢修班组名单 ====================
@router.get("/qiangxiu")
def qiangxiu_list(
    search: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    q = db.query(Qiangxiurenyuan)
    scope = scoped(db, current)
    if scope is not None:
        q = q.filter(Qiangxiurenyuan.bmid.in_(scope))
    if (search or "").strip():
        q = q.filter(Qiangxiurenyuan.name.like(f"%{search.strip()}%"))
    return [{"id": r.id, "name": s(r.name)}
            for r in q.order_by(Qiangxiurenyuan.name).all()]


@router.post("/qiangxiu/add")
def qiangxiu_add(
    data: QiangxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    exists = db.query(Qiangxiurenyuan).filter(
        Qiangxiurenyuan.name == name).first()
    if exists:
        raise HTTPException(status_code=400, detail="该名称已存在，请勿重复添加")
    db.add(Qiangxiurenyuan(name=name, bmid=_default_bmid(db, current, None)))
    db.commit()
    return {"success": True}


@router.post("/qiangxiu/edit")
def qiangxiu_edit(
    data: QiangxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    item = db.get(Qiangxiurenyuan, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    _ensure_qx_visible(db, current, item)
    exists = (db.query(Qiangxiurenyuan)
              .filter(Qiangxiurenyuan.name == name, Qiangxiurenyuan.id != item.id)
              .first())
    if exists:
        raise HTTPException(status_code=400, detail="该名称已存在，不能重复")
    item.name = name
    db.commit()
    return {"success": True}


@router.post("/qiangxiu/delete")
def qiangxiu_delete(
    data: QiangxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    item = db.get(Qiangxiurenyuan, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    _ensure_qx_visible(db, current, item)
    db.delete(item)
    db.commit()
    return {"success": True}


# ==================== 工单号带出 / 领料明细 / 详情抽屉 ====================
@router.get("/gongdan-info")
def gongdan_info(
    gongdanhao: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    """旧 GetGongdanInfo:内网 flow 工单 + 本库领料材料文本 + 工单号查重。"""
    no = (gongdanhao or "").strip()
    if not no:
        return {"success": False, "message": "工单号不能为空"}
    has_used = db.query(GongdanCailiao.id).filter(
        GongdanCailiao.gongdanhao == no).first() is not None
    wst = material_text(db, no)
    res = workorder_external.fetch_workorder(no, timeout=FLOW_TIMEOUT)
    data = res.get("data") if res.get("success") else None
    if not data:
        return {
            "success": True, "hasUsed": has_used,
            "data": {"ksriqi": "", "jsriqi": "", "dizhi": "", "neirong": "",
                     "cailiao": wst},
            "message": "主表未找到该工单，但材料表存在记录",
        }
    return {
        "success": True, "hasUsed": has_used,
        "data": {
            "guanjing": s(data.get("LeakageType")),
            "ksriqi": s(data.get("CreateTime")),
            "jsriqi": s(data.get("updateTime")),
            "dizhi": s(data.get("AddressStr")),
            "neirong": s(data.get("Problem")),
            "cailiao": wst,
        },
    }


@router.get("/order-details")
def order_details(
    gdId: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    """旧 GetOrderDetails:返回数组(7 列)。"""
    return order_detail_rows(db, (gdId or "").strip())


@router.get("/by-no")
def by_no(
    gongdanNo: str = "",
    current: User = Depends(require_permission("gongdan:view")),
):
    """工单详情抽屉 —— 与 /api/workorder/external/info 同一上游、同一返回结构。

    照抄 workorder 的字段约定(success/message/data);差别只在权限码用
    gongdan:view,让只有录入权限的用户也能看工单详情,不必有 workorder:view。
    """
    if not (gongdanNo or "").strip():
        return {"success": False, "message": "工单号不能为空"}
    res = workorder_external.fetch_workorder(gongdanNo)
    if not res["success"]:
        return {"success": False, "message": res["msg"]}
    return {"success": True, "data": workorder_external.workorder_detail(res["data"] or {})}


@router.get("/images")
def images(
    flow_id: str = "", gongdanNo: str = "", flowId: str = "",
    current: User = Depends(require_permission("gongdan:view")),
):
    """现场图片列表 —— 照 /api/workorder/external/images:固定 3 槽位 + 短令牌代理。

    参数名与 workorder 一致用 flow_id;flowId 仅兼容旧调用。
    """
    res = workorder_external.fetch_workorder_images(flow_id or flowId or gongdanNo)
    if not res["success"]:
        return {"success": False, "message": res["msg"], "images": []}
    out = []
    for img in res["images"]:
        token = ""
        if img.get("url"):
            token = create_short_token(
                "gongdan_wo_image", {"url": img["url"], "sub": str(current.id)},
                minutes=IMAGE_TOKEN_MINUTES,
            )
        out.append({
            "kind": img.get("kind"), "label": img.get("label"),
            "token_url": f"/api/gongdan/image?token={token}" if token else "",
        })
    return {"success": True, "images": out}


@router.get("/image")
def image_proxy(token: str = ""):
    """现场图片代理(短令牌),内网不可达返回 1×1 透明占位图。"""
    try:
        payload = decode_short_token(token, "gongdan_wo_image")
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
def _apply_form(item: GongdanCailiao, data: GongdanIn):
    item.gongdanhao = (data.gongdanhao or "").strip()
    item.neirong = data.neirong or ""
    item.ksriqi = parse_dt(data.ksriqi)
    item.jsriqi = parse_dt(data.jsriqi)
    item.shijian = data.shijian
    item.dizhi = data.dizhi or ""
    item.caizhi = data.caizhi or ""
    item.guanjing = data.guanjing or ""
    item.shuiliang = data.shuiliang
    item.cailiao = data.cailiao or ""
    item.shuliang = data.shuliang or ""
    item.qiangxiurenyuan = data.qiangxiurenyuan or ""
    item.tingshui = data.tingshui or ""
    item.beizhu = data.beizhu or ""
    item.pipesize = parse_pipe_size(item.guanjing)


def _validate(data: GongdanIn):
    if not (data.gongdanhao or "").strip():
        raise HTTPException(status_code=400, detail="工单号为必填字段")
    if not (data.neirong or "").strip():
        raise HTTPException(status_code=400, detail="工作内容为必填字段")
    if not parse_dt(data.ksriqi):
        raise HTTPException(status_code=400, detail="开始日期为必填字段")
    if not parse_dt(data.jsriqi):
        raise HTTPException(status_code=400, detail="结束日期为必填字段")


@router.post("/add")
def add(
    data: GongdanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    _validate(data)
    item = GongdanCailiao()
    _apply_form(item, data)
    item.bmid = _default_bmid(db, current, data.bmid)
    item.djriqi = datetime.now()
    item.zuihouriqi = datetime.now()
    item.djren = current.username
    db.add(item)
    db.flush()
    upsert_dict(db, GongdanNeirongDict, GongdanNeirongDict.neirong, item.neirong)
    upsert_dict(db, GongdanCaizhiDict, GongdanCaizhiDict.caizhi, item.caizhi)
    db.commit()
    return {"success": True, "id": item.id}


@router.post("/update")
def update(
    data: GongdanIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:view")),
):
    _validate(data)
    item = db.get(GongdanCailiao, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    _ensure_visible(db, current, item)
    old_neirong = item.neirong
    old_caizhi = item.caizhi
    has_used = (db.query(GongdanCailiao.id)
                .filter(GongdanCailiao.gongdanhao == (data.gongdanhao or "").strip(),
                        GongdanCailiao.id != item.id).first() is not None)
    _apply_form(item, data)
    item.zuihouriqi = datetime.now()
    item.djren = current.username
    db.flush()
    if (old_neirong or "") != (item.neirong or ""):
        upsert_dict(db, GongdanNeirongDict, GongdanNeirongDict.neirong, item.neirong)
    if (old_caizhi or "") != (item.caizhi or ""):
        upsert_dict(db, GongdanCaizhiDict, GongdanCaizhiDict.caizhi, item.caizhi)
    db.commit()
    return {
        "success": True, "hasUsed": has_used,
        "message": "已更新！但其他记录也有该工单号。" if has_used else "更新成功",
    }


@router.post("/del")
def delete(
    data: QiangxiuIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("gongdan:manage")),
):
    """旧 Del 是物理删除;新系统单独用 gongdan:manage 守(超管自动拥有)。"""
    item = db.get(GongdanCailiao, data.id or 0)
    if item is None:
        raise HTTPException(status_code=400, detail="记录不存在")
    _ensure_visible(db, current, item)
    db.delete(item)
    db.commit()
    return {"success": True, "message": "ok"}
