"""稽查系统(照旧 jcxtController 1:1 复刻)。

- 列表:日期口径 5 种 + 违章/举报类别 + 管径/管材 + 大管/逃逸/农村开关 +
  提交状态开关(tijiao) + 模糊,部门子树数据权限,合计 footer
- 添加/编辑:工单号查重、四字段查重、违章日期必填且不得超前、施工挖破必选管径、
  有举报人必选举报类别、处理日期派生办结天数/逃逸/已完结,仅本人可改(超管例外)
- 提交/撤回:暂存↔待审核(提交限本人,撤回不限本人,已审核通过不可撤回)
- 图片:上传/删除/短令牌访问(历史 url 指向旧服务器,缺文件返回透明占位图)
- 关联稽查单:guanlian/qxgl(写 jc_jcxx.jcdanid 与 jcdan.jcxxid)
- 图表 Getpie:8 种指标,按部门/类别/管径聚合
- 导入:稽查报表.xls(空工单号 break、四字段重复 break)
- 导出:32 列全量 / 自选列 / 同安奖励名单 / 模板下载
- 自选导出列:selcol/delcol/allsele(jc_printcolum,userid -> users.id)

权限:jcxt:view 模块入口 + 全部功能(旧系统菜单控制,无细分权限)。
"""

import io
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

CENTER = Alignment(horizontal="center", vertical="center")
BORDER = Border(*[Side(style="thin")] * 4)
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.db.session import get_db
from app.models.jcxt import JcJcxx, JcPrintcolum, JcTupian
from app.models.user import Department, User
from app.services import jcxt_excel, workorder_external
from app.services.jcxt_common import (
    DANJIA, EXPORT_FIELDS, GUANCAI, GUANJING, JUBAOLEIBIE, NONGCUN, RQSX,
    WZLEIBIE, XINXILAIYUAN, ZHIXINGQK_JCXT, ZHUIJIAOBM, ZHUANGTAI_FILTER,
    apply_jcxx_filters, computer_gj, get_date_range, jcxx_footer, jcxx_row,
    load_pics, order_jcxx, parse_date, reward_base_query, visible_dept_ids,
    _num,
)

router = APIRouter()

TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fccf00c30f0003050100f9e2fe6e0000000049454e44ae426082"
)
ALLOWED_EXTS = {".jpg", ".jpeg"}
IMAGE_TOKEN_MINUTES = 180


# ==================== 请求模型 ====================
class JcxxIn(BaseModel):
    gongdanhao: Optional[str] = None
    weizhangriqi: Optional[str] = None
    chuliriqi: Optional[str] = None
    weizhangren: Optional[str] = None
    weizhangdianhua: Optional[str] = None
    weizhangdizhi: Optional[str] = None
    weizhangneirong: Optional[str] = None
    wzleibie: Optional[str] = None
    guanjing: Optional[str] = None
    guancai: Optional[str] = None
    nongcunjicha: Optional[str] = None
    jubaoren: Optional[str] = None
    jubaoleibie: Optional[str] = None
    zhuijiaobm: Optional[str] = None
    zhuijiaoshuiliang: Optional[int] = None
    zhuijiaoshuifei: Optional[Decimal] = None
    zhuijiaogongliaofei: Optional[Decimal] = None
    peibiaofei: Optional[Decimal] = None
    danjia: Optional[Decimal] = None
    beizhu: Optional[str] = None
    spzt: Optional[str] = None          # 编辑时透传(用于拦截已审核)
    caozuoname: Optional[str] = None    # 编辑时透传(用于本人校验)
    ssbmid: Optional[int] = None        # 新增时可选部门(超管)


class SubmitIn(BaseModel):
    ids: str


class LinkIn(BaseModel):
    id: int    # jcdan.id
    jcid: int  # jc_jcxx.id


def _dept_filter(db: Session, user: User, bmid: Optional[int]) -> Optional[set]:
    """旧 cj 前缀 -> 子树 id 集合。bmid 为前端选择的部门,叠加在本人作用域之上。"""
    scope = dept_scope_ids(db, user)
    if bmid:
        ids = {bmid}
        while True:
            children = (
                db.query(Department.id)
                .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids))
                .all()
            )
            if not children:
                break
            ids |= {c[0] for c in children}
        if scope is not None:
            ids &= scope
        return ids
    return scope


def _list_query(db, user, params: dict):
    start, end = get_date_range(params.get("filterType") or "custom",
                                params.get("selectedMonth"),
                                params.get("rq"), params.get("rqend"))
    q = db.query(JcJcxx)
    q = apply_jcxx_filters(
        q,
        rq=start, rqend=end, lb=params.get("rqsx") or "违章日期",
        lbid=params.get("lbid") or "", jblb=params.get("jblb") or "",
        guanjing=params.get("guanjing") or "",
        mohu=params.get("sousou") or "",
        dg=bool(params.get("dg")), taoyi=bool(params.get("taoyi")),
        nongcun=bool(params.get("nongcun")),
        tijiao=None if params.get("tijiao") is None else bool(params.get("tijiao")),
        dept_ids=_dept_filter(db, user, params.get("bmid")),
    )
    return q, end


def _row_dicts(db, q, page: int, size: int, px: bool):
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = order_jcxx(q, px).offset((page - 1) * size).limit(size).all()
    pics = load_pics(db, [r.id for r in rows])
    return [jcxx_row(db, r, dept_names, pics) for r in rows]


def _own_dept(db: Session, user: User) -> Optional[int]:
    if user.departments:
        return user.departments[0].id
    return None


def _validate_record(db: Session, data: JcxxIn, exclude_id: Optional[int],
                     expect_owner: Optional[str], user: User):
    """照旧 add/Editgz 的全部校验,返回错误文本或 None。"""
    gd = (data.gongdanhao or "").strip() or None
    if gd:
        dup = db.query(JcJcxx.id).filter(JcJcxx.gongdanhao == gd)
        if exclude_id:
            dup = dup.filter(JcJcxx.id != exclude_id)
        if dup.first():
            return "工单号重复,无法保存"
    wzrq = parse_date(data.weizhangriqi)
    if data.weizhangriqi and wzrq and wzrq.date() > datetime.now().date():
        return "违章日期大于当前日期!"
    if not data.weizhangriqi:
        return "违章日期没有选"
    if data.weizhangriqi:
        cf = db.query(JcJcxx.id).filter(
            JcJcxx.weizhangriqi == wzrq,
            JcJcxx.weizhangren == (data.weizhangren or None),
            JcJcxx.weizhangneirong == (data.weizhangneirong or None),
            JcJcxx.weizhangdizhi == (data.weizhangdizhi or None),
        )
        if exclude_id:
            cf = cf.filter(JcJcxx.id != exclude_id)
        if cf.first():
            return "重复记录,无法保存"
    if data.jubaoren and not data.jubaoleibie:
        return "没有选举报类别"
    if data.wzleibie == "施工挖破水管" and not data.guanjing:
        return "没有选管径"
    clr = parse_date(data.chuliriqi)
    if clr and clr.date() > datetime.now().date():
        return "处理日期大于当前日期!"
    if expect_owner is not None and not user.is_superuser \
            and expect_owner != user.username:
        return "无法编辑非自己录入的信息!"
    return None


def _apply_derived(data: dict):
    """照旧 add/Editgz 尾部:办结天数/逃逸/已完结/intguanjing。"""
    wzrq = parse_date(data.get("weizhangriqi"))
    clr = parse_date(data.get("chuliriqi"))
    if wzrq and clr:
        if wzrq > clr:
            return "违章日期大于处理日期"
        data["banjietianshu"] = (clr.date() - wzrq.date()).days
    if clr:
        sf = data.get("zhuijiaoshuifei")
        glf = data.get("zhuijiaogongliaofei")
        if (sf is None or sf <= 0) and (glf is None or glf <= 0):
            data["zhixingqingkuang"] = "逃逸"
        else:
            data["zhixingqingkuang"] = None
        data["zhuangtai"] = "已完结"
    else:
        data["zhuangtai"] = None
    data["intguanjing"] = computer_gj(data.get("guanjing"))
    return None


# ==================== 列表 / 字典 ====================
@router.get("")
def list_jcxx(
    page: int = 1,
    size: int = 30,
    filterType: str = "custom",
    selectedMonth: str = "",
    rq: str = "",
    rqend: str = "",
    rqsx: str = "",
    lbid: str = "",
    jblb: str = "",
    guanjing: str = "",
    sousou: str = "",
    bmid: Optional[int] = None,
    px: bool = False,
    dg: bool = False,
    taoyi: bool = False,
    nongcun: bool = False,
    tijiao: Optional[bool] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    params = dict(filterType=filterType, selectedMonth=selectedMonth, rq=rq,
                  rqend=rqend, rqsx=rqsx, lbid=lbid, jblb=jblb,
                  guanjing=guanjing, sousou=sousou, bmid=bmid, px=px, dg=dg,
                  taoyi=taoyi, nongcun=nongcun, tijiao=tijiao)
    q, _end = _list_query(db, current, params)
    total = q.count()
    items = _row_dicts(db, q, page, size, px)
    return {"total": total, "items": items, "footer": jcxx_footer(q)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    own = {d.name for d in current.departments}
    # 旧系统:同安营业所/售水事业部用户显示「奖励导出」按钮
    show_jl = bool(own & {"同安营业所", "售水事业部"}) or current.is_superuser
    return {
        "departments": departments,
        "wzleibie": WZLEIBIE,
        "jubaoleibie": JUBAOLEIBIE,
        "zhuijiaobm": ZHUIJIAOBM,
        "zhuangtai": ZHUANGTAI_FILTER,
        "zhixingqingkuang": ZHIXINGQK_JCXT,
        "xinxilaiyuan": XINXILAIYUAN,
        "nongcunjicha": NONGCUN,
        "guancai": GUANCAI,
        "guanjing": GUANJING,
        "danjia": DANJIA,
        "rqsx": RQSX,
        "export_fields": [{"ziduan": z, "bt": b} for z, b in EXPORT_FIELDS],
        "export_cols": [
            p.printcolum for p in db.query(JcPrintcolum)
            .filter(JcPrintcolum.userid == current.id).all()
        ],
        "default_bmid": _own_dept(db, current),
        "show_jl": show_jl,
        "perms": {"view": True},
    }


# ==================== 详情 / 添加 / 编辑 / 删除 ====================
@router.get("/detail/{row_id}")
def show_edit_info(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    pics = load_pics(db, [row.id])
    item = jcxx_row(db, row, {}, pics)
    item["usne"] = current.username
    return item


@router.post("")
def add_jcxx(
    data: JcxxIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    err = _validate_record(db, data, None, None, current)
    if err:
        raise HTTPException(status_code=400, detail=err)
    payload = data.model_dump(exclude={"spzt", "caozuoname", "ssbmid"})
    payload["weizhangriqi"] = data.weizhangriqi
    payload["chuliriqi"] = data.chuliriqi
    payload["gongdanhao"] = (data.gongdanhao or "").strip() or None
    err = _apply_derived(payload)
    if err:
        raise HTTPException(status_code=400, detail=err)
    payload.update({
        "spzt": "暂存",
        "caozuoriqi": datetime.now(),
        "zuihougengxin": datetime.now(),
        "caozuoname": current.username,
        "ssbmid": _own_dept(db, current),
    })
    row = JcJcxx(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@router.put("/{row_id}")
def edit_jcxx(
    row_id: int,
    data: JcxxIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if data.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="记录已审核无法修改!")
    err = _validate_record(db, data, row.id, data.caozuoname or row.caozuoname, current)
    if err:
        raise HTTPException(status_code=400, detail=err)
    payload = data.model_dump(exclude={"spzt", "caozuoname", "ssbmid"})
    payload["gongdanhao"] = (data.gongdanhao or "").strip() or None
    err = _apply_derived(payload)
    if err:
        raise HTTPException(status_code=400, detail=err)
    payload["zuihougengxin"] = datetime.now()
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


@router.delete("/{row_id}")
def delete_jcxx(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="记录已审核无法删除!")
    if not current.is_superuser and (row.caozuoname or "") != (current.username or ""):
        raise HTTPException(status_code=403, detail="不能删除非自己建的单")
    for p in db.query(JcTupian).filter(JcTupian.jcxxid == row.id).all():
        path = _image_path(p.url)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        db.delete(p)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ==================== 图片 ====================
def _image_path(url: str) -> Path:
    raw = (url or "").replace("\\", "/").lstrip("/")
    if raw.lower().startswith("upload/"):
        raw = raw[len("upload/"):]
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / raw).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="图片路径不合法")
    return path


@router.post("/{row_id}/images")
def upload_image(
    row_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="记录已审核,不能再传图")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="不是图片(仅支持 jpg)")
    now = datetime.now()
    target = (Path(settings.UPLOAD_DIR) / "jcImages" / str(now.year)
              / str(now.month) / str(now.day))
    target.mkdir(parents=True, exist_ok=True)
    stored = f"{now.strftime('%Y%m%d%H%M%S')}_{row_id}{ext}"
    (target / stored).write_bytes(file.file.read())
    url = f"/Upload/jcImages/{now.year}/{now.month}/{now.day}/{stored}"
    pic = JcTupian(url=url, jcxxid=row.id)
    row.zuihougengxin = now
    db.add(pic)
    db.commit()
    db.refresh(pic)
    return {"ok": True, "id": pic.id, "url": url}


@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    pic = db.get(JcTupian, image_id)
    if pic is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    row = db.get(JcJcxx, pic.jcxxid) if pic.jcxxid else None
    if row is not None and row.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="记录已审核,图片不能删除")
    path = _image_path(pic.url)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    db.delete(pic)
    db.commit()
    return {"ok": True}


@router.post("/images/{image_id}/token")
def image_token(
    image_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    pic = db.get(JcTupian, image_id)
    if pic is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    token = create_short_token(
        "jcxt_image", {"iid": image_id, "sub": str(current.id)},
        minutes=IMAGE_TOKEN_MINUTES,
    )
    return {"token": token, "url": f"/api/jcxt/image?token={token}",
            "expires_minutes": IMAGE_TOKEN_MINUTES}


@router.get("/image")
def image_file(token: str = "", db: Session = Depends(get_db)):
    import jwt as pyjwt

    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "jcxt_image")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    pic = db.get(JcTupian, int(payload.get("iid", 0)))
    if pic is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _image_path(pic.url)
    if not path.exists():
        # 历史图片在旧生产服务器 /Upload/jcImages/,未拷入前返回透明占位图
        return Response(content=TRANSPARENT_PNG, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


# ==================== 提交 / 撤回 ====================
@router.post("/submit/{row_id}")
def submit_one(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="该记录已审核通过,无需再次提交")
    if not current.is_superuser and (row.caozuoname or "") != (current.username or ""):
        raise HTTPException(status_code=403, detail="不能提交非本人建单的记录")
    row.spzt = "待审核"
    row.spdate = datetime.now()
    row.spren = current.username
    db.commit()
    return {"ok": True}


@router.post("/submit-rows")
def submit_rows(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="错误")
    ok = passed = not_mine = missing = 0
    for s in data.ids.split(","):
        try:
            rid = int(s)
        except ValueError:
            continue
        if rid <= 0:
            continue
        row = db.get(JcJcxx, rid)
        if row is None:
            missing += 1
            continue
        if row.spzt == "审核通过":
            passed += 1
            continue
        if not current.is_superuser and (row.caozuoname or "") != (current.username or ""):
            not_mine += 1
            continue
        row.spzt = "待审核"
        row.spdate = datetime.now()
        row.spren = current.username
        ok += 1
    db.commit()
    if ok > 0:
        return {"ok": True, "ok_count": ok, "passed": passed, "not_mine": not_mine}
    if passed and not_mine:
        raise HTTPException(status_code=400,
                            detail=f"{passed} 条已审核通过、{not_mine} 条非本人建单,均不能提交")
    if not_mine:
        raise HTTPException(status_code=400,
                            detail=f"选中的 {not_mine} 条记录不是本人建单,不能提交")
    if passed:
        raise HTTPException(status_code=400,
                            detail=f"选中的 {passed} 条记录已审核通过,无需再次提交")
    if missing:
        raise HTTPException(status_code=400, detail="选中的记录已不存在,请刷新后重试")
    raise HTTPException(status_code=400, detail="没有可提交的记录")


@router.post("/recall/{row_id}")
def recall_one(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.spzt == "审核通过":
        raise HTTPException(status_code=400, detail="该记录已审核通过,不能撤回")
    row.spzt = "暂存"
    row.spren = None
    row.spdate = None
    db.commit()
    return {"ok": True}


@router.post("/recall-rows")
def recall_rows(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="错误")
    ok = passed = missing = 0
    for s in data.ids.split(","):
        try:
            rid = int(s)
        except ValueError:
            continue
        if rid <= 0:
            continue
        row = db.get(JcJcxx, rid)
        if row is None:
            missing += 1
            continue
        if row.spzt == "审核通过":
            passed += 1
            continue
        row.spzt = "暂存"
        row.spren = None
        row.spdate = None
        ok += 1
    db.commit()
    if ok > 0:
        return {"ok": True, "ok_count": ok, "passed": passed}
    if passed:
        raise HTTPException(status_code=400,
                            detail=f"选中的 {passed} 条记录已审核通过,不能撤回")
    if missing:
        raise HTTPException(status_code=400, detail="选中的记录已不存在,请刷新后重试")
    raise HTTPException(status_code=400, detail="没有可撤回的记录")


# ==================== 关联稽查单 ====================
@router.post("/link-jcdan")
def link_jcdan(
    data: LinkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    from app.models.jcxt import Jcdan

    jcxx = db.get(JcJcxx, data.jcid)
    jd = db.get(Jcdan, data.id)
    other = db.query(Jcdan).filter(
        Jcdan.jcxxid == data.jcid, Jcdan.id != data.id).first()
    if other is not None:
        other.jcxxid = None
    if jd is None:
        raise HTTPException(status_code=404, detail="稽查单不存在")
    jd.jcxxid = data.jcid
    if jcxx is not None:
        jcxx.zuihougengxin = datetime.now()
        jcxx.jcdanid = data.id
        db.commit()
        return {"ok": True}
    raise HTTPException(status_code=404, detail="稽查信息不存在")


@router.post("/unlink-jcdan")
def unlink_jcdan(
    data: LinkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    from app.models.jcxt import Jcdan

    jd = db.get(Jcdan, data.id)
    jcxx = db.get(JcJcxx, data.jcid)
    if jd is None:
        raise HTTPException(status_code=404, detail="稽查单不存在")
    jd.jcxxid = None
    if jcxx is not None:
        jcxx.zuihougengxin = datetime.now()
        jcxx.jcdanid = None
        db.commit()
        return {"ok": True}
    raise HTTPException(status_code=404, detail="稽查信息不存在")


# ==================== 自动补全 / 工单信息 ====================
@router.get("/weizhangren")
def weizhangren_suggest(
    query: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    if not query:
        return []
    rows = (
        db.query(JcJcxx.weizhangren)
        .filter(JcJcxx.weizhangren.contains(query), JcJcxx.weizhangren.isnot(None))
        .distinct()
        .limit(20)
        .all()
    )
    return [{"duixiang": r[0]} for r in rows if r[0]]


@router.get("/gongdan-info")
def gongdan_info(
    gongdanhao: str = "",
    current: User = Depends(require_permission("jcxt:view")),
):
    """工单详情(溯源旧 jcxtController.GetGongdanInfo + WorkOrderNoService)。

    返回 data 同时含旧表单字段 ksriqi/dizhi 与详情抽屉所需原始字段。
    """
    if not gongdanhao:
        return {"success": False, "message": "工单号不能为空"}
    res = workorder_external.fetch_workorder(gongdanhao)
    if not res["success"]:
        return {"success": False, "message": res["msg"]}
    # 与 /api/workorder/external/info 共用同一份字段规范化,避免两处口径漂移
    return {"success": True, "data": workorder_external.workorder_detail(res["data"] or {})}


@router.get("/gongdan-images")
def gongdan_images(
    flow_id: int = 0,
    gongdanhao: str = "",
    current: User = Depends(require_permission("jcxt:view")),
):
    """工单现场图片列表(溯源旧 ImageProxy.GetWorkOrderImages)。

    每张图返回短令牌代理地址,浏览器不直连内网图片服务器。
    """
    target = flow_id or gongdanhao
    res = workorder_external.fetch_workorder_images(target)
    if not res["success"]:
        return {"success": False, "message": res["msg"], "images": []}
    images = []
    for item in res["images"]:
        token_url = ""
        if item["url"]:
            token = create_short_token(
                "jcxt_wo_image", {"url": item["url"], "sub": str(current.id)},
                minutes=IMAGE_TOKEN_MINUTES,
            )
            token_url = f"/api/jcxt/gongdan-image?token={token}"
        images.append({
            "kind": item["kind"],
            "label": item["label"],
            "token_url": token_url,
        })
    return {"success": True, "images": images}


@router.get("/gongdan-image")
def gongdan_image(token: str = ""):
    """工单图片代理(溯源旧 ImageProxy.GetImage),仅白名单域名。"""
    import jwt as pyjwt

    if not token:
        raise HTTPException(status_code=401, detail="缺少图片令牌")
    try:
        payload = decode_short_token(token, "jcxt_wo_image")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="图片令牌无效或已过期")
    try:
        data, content_type = workorder_external.fetch_image(payload.get("url", ""))
    except Exception:
        return Response(content=TRANSPARENT_PNG, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600"})


# ==================== 图表(照旧 Getpie) ====================
@router.get("/pie")
def get_pie(
    rq: int,
    leib: int,
    yue: str = "0",
    bmid: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    rows = db.query(JcJcxx).filter(
        func.year(JcJcxx.chuliriqi) == rq,
        or_(JcJcxx.zhuijiaoshuifei.isnot(None), JcJcxx.zhuijiaogongliaofei.isnot(None)),
        or_(JcJcxx.zhuijiaogongliaofei >= 0, JcJcxx.zhuijiaoshuifei >= 0),
        JcJcxx.spzt != "暂存",
    ).all()
    # 月份多选:空/0/解析失败 => 全年
    sel = sorted({int(m) for m in (yue or "").split(",")
                  if m.strip().isdigit() and 1 <= int(m) <= 12})
    jc = [r for r in rows if sel and r.chuliriqi and r.chuliriqi.month in sel] \
        if sel else rows
    bar_months = sel or list(range(1, 13))
    zong_jc = jc if sel else rows

    dept_names = {d.id: d.name for d in db.query(Department).all()}
    bums = []

    def by_dept(getter):
        groups = {}
        for r in jc:
            groups.setdefault(r.ssbmid, Decimal("0"))
            v = getter(r)
            if v is not None:
                groups[r.ssbmid] += Decimal(str(v))
        for k, v in groups.items():
            bums.append({"name": dept_names.get(k, ""), "value": float(v)})

    if leib == 8:  # 管径统计(施工挖破水管)
        groups: dict = {}
        for r in jc:
            if r.intguanjing and r.wzleibie == "施工挖破水管":
                groups[r.intguanjing] = groups.get(r.intguanjing, 0) + 1
        for k in sorted(groups):
            bums.append({"name": str(k), "value": groups[k]})
    elif leib in (1, 5, 6):
        by_dept(lambda r: (lambda sf, glf:
                           (sf or 0) + (glf or 0) if leib == 1
                           else (sf if leib == 5 else glf))(
            _num(r.zhuijiaoshuifei), _num(r.zhuijiaogongliaofei)))
    elif leib == 2:
        groups: dict = {}
        for r in jc:
            groups[r.ssbmid] = groups.get(r.ssbmid, 0) + 1
        for k, v in groups.items():
            bums.append({"name": dept_names.get(k, ""), "value": v})
    elif leib == 7:
        by_dept(lambda r: r.zhuijiaoshuiliang)
    elif leib in (3, 4):
        groups: dict = {}
        for r in jc:
            key = r.wzleibie
            if not key:
                continue
            cur = groups.setdefault(key, {"count": 0, "sum": Decimal("0")})
            cur["count"] += 1
            if leib == 4:
                cur["sum"] += _num(r.zhuijiaoshuifei) + _num(r.zhuijiaogongliaofei)
        for k, v in groups.items():
            bums.append({"name": k, "value": v["count"] if leib == 3 else float(v["sum"])})

    bums.sort(key=lambda x: x["value"])

    # 柱状图(勾月份按所选月份,全年 12 个月;合计按 zong 口径)
    def month_series(getter):
        out = []
        for m in bar_months:
            vals = [getter(r) for r in rows
                    if r.chuliriqi and r.chuliriqi.month == m
                    and (bmid == 0 or r.ssbmid == bmid)]
            total = sum((Decimal(str(v)) if v is not None else Decimal("0"))
                        for v in vals)
            out.append({"month": f"{m}月", "value": float(total)})
        zvals = [getter(r) for r in zong_jc if bmid == 0 or r.ssbmid == bmid]
        zong = sum((Decimal(str(v)) if v is not None else Decimal("0")) for v in zvals)
        return out, float(zong)

    monthly = {"year": rq, "zong": 0, "monthly_data": []}
    if leib == 5:
        md, zong = month_series(lambda r: r.zhuijiaoshuifei)
        monthly.update(monthly_data=md, zong=zong)
    elif leib == 6:
        md, zong = month_series(lambda r: r.zhuijiaogongliaofei)
        monthly.update(monthly_data=md, zong=zong)
    elif leib == 1:
        md, zong = month_series(
            lambda r: (_num(r.zhuijiaoshuifei) + _num(r.zhuijiaogongliaofei)))
        monthly.update(monthly_data=md, zong=zong)
    elif leib == 2:
        out = []
        for m in bar_months:
            n = len([r for r in rows if r.chuliriqi and r.chuliriqi.month == m
                     and (bmid == 0 or r.ssbmid == bmid)])
            out.append({"month": f"{m}月", "value": n})
        zong = len([r for r in zong_jc if bmid == 0 or r.ssbmid == bmid])
        monthly.update(monthly_data=out, zong=zong)
    elif leib == 7:
        md, zong = month_series(lambda r: r.zhuijiaoshuiliang)
        monthly.update(monthly_data=md, zong=zong)

    return {
        "category_statistics": {"categories2": bums},
        "monthly_statistics": monthly,
    }


# ==================== 导出列配置 ====================
@router.get("/export-columns")
def export_columns(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    cols = [p.printcolum for p in db.query(JcPrintcolum)
            .filter(JcPrintcolum.userid == current.id).all()]
    return {"items": cols}


@router.post("/export-columns/{colname}")
def select_column(
    colname: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    exists = db.query(JcPrintcolum).filter(
        JcPrintcolum.userid == current.id, JcPrintcolum.printcolum == colname).first()
    if exists:
        return {"ok": False, "detail": "no"}
    db.add(JcPrintcolum(userid=current.id, printcolum=colname))
    db.commit()
    return {"ok": True}


@router.delete("/export-columns/{colname}")
def delete_column(
    colname: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    row = db.query(JcPrintcolum).filter(
        JcPrintcolum.userid == current.id, JcPrintcolum.printcolum == colname).first()
    if row:
        db.delete(row)
        db.commit()
        return {"ok": True}
    return {"ok": False, "detail": "no"}


class AllSeleIn(BaseModel):
    cid: list[str]
    ck: bool


@router.post("/export-columns-all")
def select_all_columns(
    data: AllSeleIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    db.query(JcPrintcolum).filter(JcPrintcolum.userid == current.id).delete()
    if data.ck:
        for c in data.cid:
            db.add(JcPrintcolum(userid=current.id, printcolum=c))
    db.commit()
    return {"ok": True}


# ==================== 导出 ====================
def _export_rows(db, current, params: dict):
    q, end = _list_query(db, current, params)
    return q, order_jcxx(q, bool(params.get("px"))).all(), end


@router.get("/export/all")
def export_all(
    filterType: str = "custom",
    selectedMonth: str = "",
    rq: str = "",
    rqend: str = "",
    rqsx: str = "",
    lbid: str = "",
    jblb: str = "",
    guanjing: str = "",
    sousou: str = "",
    bmid: Optional[int] = None,
    px: bool = False,
    dg: bool = False,
    taoyi: bool = False,
    nongcun: bool = False,
    tijiao: Optional[bool] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    params = dict(filterType=filterType, selectedMonth=selectedMonth, rq=rq,
                  rqend=rqend, rqsx=rqsx, lbid=lbid, jblb=jblb,
                  guanjing=guanjing, sousou=sousou, bmid=bmid, px=px, dg=dg,
                  taoyi=taoyi, nongcun=nongcun, tijiao=tijiao)
    q, rows, _end = _export_rows(db, current, params)
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    wb = jcxt_excel.build_export_all(rows, dept_names, rqsx or "按违章日期筛选")
    buf = BytesIO()
    wb.save(buf)
    own_name = current.departments[0].name if current.departments else "稽查"
    filename = f"{own_name}{rqend}稽查信息明细表.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/export/me")
def export_me(
    filterType: str = "custom",
    selectedMonth: str = "",
    rq: str = "",
    rqend: str = "",
    rqsx: str = "",
    lbid: str = "",
    jblb: str = "",
    guanjing: str = "",
    sousou: str = "",
    bmid: Optional[int] = None,
    px: bool = False,
    dg: bool = False,
    taoyi: bool = False,
    nongcun: bool = False,
    tijiao: Optional[bool] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    cols = [p.printcolum for p in db.query(JcPrintcolum)
            .filter(JcPrintcolum.userid == current.id).all()]
    if not cols:
        raise HTTPException(status_code=400, detail="没有选字段")
    params = dict(filterType=filterType, selectedMonth=selectedMonth, rq=rq,
                  rqend=rqend, rqsx=rqsx, lbid=lbid, jblb=jblb,
                  guanjing=guanjing, sousou=sousou, bmid=bmid, px=px, dg=dg,
                  taoyi=taoyi, nongcun=nongcun, tijiao=tijiao)
    q, rows, _end = _export_rows(db, current, params)
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    wb = jcxt_excel.build_export_forme(rows, dept_names, cols)
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''%E7%A8%BD%E6%9F%A5%E4%BF%A1%E6%81%AF.xlsx"},
    )


@router.get("/export/reward")
def export_reward(
    rqend: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    """同安奖励名单(照旧 tazhuijiaojiangli,日期取当前筛选的结束日期)。"""
    riqi = parse_date(rqend, end_inclusive=True) or datetime.now()
    rows = reward_base_query(db, riqi.date()).all()
    wb = jcxt_excel.build_tongan_reward(rows, riqi.date())
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''%E5%90%8C%E5%AE%89%E5%A5%96%E5%8A%B1%E5%90%8D%E5%8D%95.xlsx"},
    )


@router.get("/template")
def download_template():
    """稽查报表导入模板(列序照旧 writeExcel 解析口径)。"""
    headers = ["工单号", "违章日期", "处理日期", "违章单位", "违章地址", "违章内容",
               "追缴水量", "追缴水费", "追缴工料费", "违章类别"]
    wb = Workbook()
    ws = wb.active
    ws.title = "稽查报表"
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
        cell.border = BORDER
    _w = [16, 12, 12, 22, 26, 30, 10, 10, 12, 14]
    for i, w in enumerate(_w, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 "attachment; filename*=UTF-8''%E7%A8%BD%E6%9F%A5%E6%8A%A5%E8%A1%A8.xlsx"},
    )


# ==================== 导入(照旧 UploadExcel/writeExcel) ====================
@router.post("/import")
def import_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jcxt:view")),
):
    fname = file.filename or ""
    if "稽查报表" not in fname or not fname.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="wrongfile")
    data = file.file.read()
    oknum, nonum, records = jcxt_excel.parse_report_import(
        data, fname, current.username, _own_dept(db, current))
    # 照旧:空工单号 break(records 截断);四字段重复 break
    for rec in records:
        dup = db.query(JcJcxx.id).filter(
            JcJcxx.weizhangriqi == rec["weizhangriqi"],
            JcJcxx.weizhangren == rec["weizhangren"],
            JcJcxx.weizhangneirong == rec["weizhangneirong"],
            JcJcxx.weizhangdizhi == rec["weizhangdizhi"],
        ).first()
        if dup is not None:
            nonum += 1
            break
        clr = rec.get("chuliriqi")
        if clr and (rec.get("zhuijiaoshuifei") is None or rec["zhuijiaoshuifei"] <= 0) \
                and (rec.get("zhuijiaogongliaofei") is None
                     or rec["zhuijiaogongliaofei"] <= 0):
            rec["zhixingqingkuang"] = "逃逸"
        if clr:
            rec["zhuangtai"] = "已完结"
        db.add(JcJcxx(**rec))
        oknum += 1
    db.commit()
    return {"ok": True, "oknum": oknum, "nonum": nonum,
            "message": f"成功上传{oknum}条记录,失败{nonum}条记录"}
