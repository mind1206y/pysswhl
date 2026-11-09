"""实施单表(jhssdb)接口:照旧 jhssdbController 复刻。

- 列表默认只看本人专管员计划,可切「所有专管员计划」
- 状态:专管员落实/售水待汇总/已回退/售水通过/删除
- 新增/编辑(保存或直接提交)、软删除、提交汇总、回退营业所、批量改主办/类别/小类
- 变更记录(字段级日志)、导出全部/当前页

权限:jhssdb:view(查询/导出) + jhssdb:manage(全部写操作)。
"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, require_permission
from app.db.session import get_db
from app.models.plan import GxGxgz, JhSsdb, JhYyfq
from app.models.user import Department, User
from app.services.plan_common import (
    JHLB_OPTIONS, LEIBIE_OPTIONS, STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED,
    STATUS_SUBMITTED, STATUS_TODO, YY_RETURNED, add_log, dept_options, fill_gxgz_defaults,
    has_perm, log_rows, parse_xuhao, plan_year, resolve_user_id, snapshot_ssdb, sort_ssdb_plans,
    ssdb_base_query, ssdb_rows, ssdb_totals, zgy_options,
)
from app.services import sms as sms_service
from app.services.plan_excel import export_plan_sheet, export_plan_workbook

router = APIRouter()

STATUS_OPTIONS = [
    {"value": STATUS_TODO, "label": "待处理计划"},
    {"value": STATUS_SUBMITTED, "label": "已提交计划"},
    {"value": STATUS_RETURNED, "label": "已回退营业所"},
    {"value": STATUS_APPROVED, "label": "已通过计划"},
    {"value": STATUS_DELETED, "label": "已删除"},
]


class SsdbIn(BaseModel):
    niandu: Optional[int] = None
    jhlb: str = ""
    ssbm: int
    zb: int
    zgy: str = ""
    leibie: str = ""
    xuhao: str = ""
    daibanname: str = ""
    jine: Optional[float] = None
    startjine: Optional[float] = None
    zongtouzi: Optional[float] = None
    kgny: str = ""
    jgny: str = ""
    xjxl: str = ""
    bz: str = ""
    pizhu: str = ""
    submit: bool = False


class IdsIn(BaseModel):
    ids: list[int]


class StatusIn(BaseModel):
    ids: list[int]
    zt: str
    iftel: bool = False
    pizhu: str = ""


class ZbIn(BaseModel):
    ids: list[int]
    bumid: int


class ValueIn(BaseModel):
    ids: list[int]
    value: str


class SmsIn(BaseModel):
    zgy: str
    nr: str


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    years = [r[0] for r in db.query(JhSsdb.niandu).filter(JhSsdb.niandu.isnot(None)).distinct().all()]
    years = sorted({int(y) for y in years if y}, reverse=True)
    cur_year = plan_year()
    if cur_year not in years:
        years.insert(0, cur_year)
    return {
        "years": years,
        "default_year": cur_year,
        "departments": dept_options(db, current),
        "hosts": dept_options(db, current, host_only=True),
        "zgys": zgy_options(db),
        "categories": JHLB_OPTIONS,
        "leibie": LEIBIE_OPTIONS,
        "statuses": STATUS_OPTIONS,
        "default_all_zgy": bool(current.is_superuser),
        "perms": {"view": True, "manage": True},
    }


@router.get("/list")
def list_rows(
    page: int = 1,
    size: int = 20,
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bumenid: Optional[int] = None,
    zb: Optional[int] = None,
    zt: str = "",
    all_zgy: bool = False,
    zgy: str = "",
    first_load: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    nd = nd or plan_year()
    default_zt = None
    if not zt and first_load:
        default_zt = STATUS_TODO
        zt = default_zt
    q = ssdb_base_query(
        db, nd=nd, jhlb=jhlb, zb=zb, bumenid=bumenid, mohu=mohu, zt=zt,
        zgy=zgy, all_zgy=all_zgy, username=current.username,
    )
    total = q.count()
    plans = (
        q.order_by(JhSsdb.dbtimep.desc(), JhSsdb.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    rows = ssdb_rows(db, plans)
    totals = ssdb_totals(q)
    cq = db.query(JhSsdb.jhlb, func.count(JhSsdb.id)).filter(
        JhSsdb.niandu == nd, JhSsdb.zt == STATUS_TODO,
    )
    if zgy:
        cq = cq.filter(JhSsdb.zhuanguan_name == zgy)
    elif not all_zgy:
        cq = cq.filter(JhSsdb.zhuanguan_name == current.username)
    counts = {k or "未知": v for k, v in cq.group_by(JhSsdb.jhlb).all()}
    return {
        "rows": rows, "total": total, "tj": totals["tongjijine"],
        "tjtz": round(totals["tongjitzy"], 2), "counts": counts,
        "default_zt": default_zt, "zt": zt, "nd": nd,
    }


@router.get("/item/{item_id}")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    row = db.get(JhSsdb, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {
        "id": row.id, "daibanname": row.daibanname or "", "bz": row.bz or "",
        "jine": row.jine, "jhlb": row.jhlb or "", "zhuanguan": row.zhuanguan_name or "",
        "Ezb": row.zb, "xuhao": row.xuhao or "", "bumenid": row.bumenid,
        "pizhu": row.pizhu or "", "leibie": row.leibie or "",
        "startjine": row.startjine, "zongtouzi": row.zongtouzi,
        "kgny": row.kgny or "", "jgny": row.jgny or "", "xjxl": row.xjxl or "",
        "niandu": row.niandu, "zt": row.zt or "", "opname": row.opname or "",
        "canHt": row.faqiid is not None,
    }


def _apply_form(row: JhSsdb, data: SsdbIn, db: Session) -> None:
    row.niandu = data.niandu or plan_year()
    row.jhlb = data.jhlb
    row.bumenid = data.ssbm
    row.zb = data.zb
    row.zhuanguan = resolve_user_id(db, data.zgy)
    row.zhuanguan_name = data.zgy
    row.leibie = data.leibie
    row.xuhao = data.xuhao
    row.nxuhao = parse_xuhao(data.xuhao)
    row.daibanname = (data.daibanname or "").strip()
    row.jine = data.jine
    row.startjine = data.startjine
    row.zongtouzi = data.zongtouzi
    row.kgny = data.kgny
    row.jgny = data.jgny
    row.xjxl = data.xjxl
    row.bz = (data.bz or "").strip()
    row.pizhu = data.pizhu
    host = db.get(Department, data.zb)
    row.fzr = (host.zg if host else "") or ""


def _validate(data: SsdbIn) -> Optional[str]:
    missing = []
    if not data.jhlb:
        missing.append("计划类别")
    if not data.ssbm:
        missing.append("所属部门")
    if not data.zb:
        missing.append("主办部门")
    if not data.zgy:
        missing.append("专管员")
    if not data.leibie:
        missing.append("小类别")
    return "、".join(missing) + "为空" if missing else None


def _duplicate(db: Session, *, name, jhlb, nd, bumenid, exclude_id=None):
    q = db.query(JhSsdb.id).filter(
        JhSsdb.daibanname == name, JhSsdb.jhlb == jhlb,
        JhSsdb.niandu == nd, JhSsdb.bumenid == bumenid,
        JhSsdb.zt.notin_([STATUS_DELETED, STATUS_RETURNED]),
    )
    if exclude_id:
        q = q.filter(JhSsdb.id != exclude_id)
    return q.first() is not None


@router.post("/create")
def create_row(
    data: SsdbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    missing = _validate(data)
    if missing:
        return {"ok": False, "message": f"添加失败！原因是{missing}。"}
    row = JhSsdb()
    _apply_form(row, data, db)
    row.zt = STATUS_SUBMITTED if data.submit else STATUS_TODO
    row.dbtimep = datetime.now()
    row.kstimep = datetime.now()
    row.opname = current.username
    row.lastop = current.username
    if _duplicate(db, name=row.daibanname, jhlb=row.jhlb, nd=row.niandu, bumenid=row.bumenid):
        return {"ok": False, "message": "发现重复计划名称！"}
    changes = fill_gxgz_defaults(row) if data.submit else []
    db.add(row)
    db.flush()
    add_log(db, row.id, "新增计划", "", row.daibanname, current.username)
    for field, old, new in changes:
        add_log(db, row.id, field, old, new, current.username)
    db.commit()
    return {"ok": True, "message": "已提交汇总" if data.submit else "添加成功", "id": row.id}


@router.post("/update/{item_id}")
def update_row(
    item_id: int,
    data: SsdbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    row = db.get(JhSsdb, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.zt in (STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED):
        return {"ok": False, "message": "无法更新！"}
    if not data.ssbm or not data.zb or not data.leibie:
        return {"ok": False, "message": "更新失败！原因是主办单位没选,或者所属部门没选,或者小类别没选。"}
    snapshot_ssdb(db, row)
    old_snap = {
        "序号": row.xuhao, "小类别": row.leibie, "计划类别": row.jhlb, "项目名称": row.daibanname,
        "项目说明": row.bz, "金额": row.jine, "年初金额": row.startjine, "本年计划投资": row.zongtouzi,
        "开工年月": row.kgny, "竣工年月": row.jgny, "新建/续建": row.xjxl,
        "专管员": row.zhuanguan_name, "所属部门": row.bumenid, "主办部门": row.zb,
        "负责人": row.fzr, "批注": row.pizhu, "状态": row.zt, "年度": row.niandu,
    }
    _apply_form(row, data, db)
    if data.submit:
        row.zt = STATUS_SUBMITTED
        fill_gxgz_defaults(row)
    row.lastop = current.username
    row.dbtimep = datetime.now()
    if _duplicate(db, name=row.daibanname, jhlb=row.jhlb, nd=row.niandu,
                  bumenid=row.bumenid, exclude_id=row.id):
        return {"ok": False, "message": "发现重复计划名称！"}
    names = dept_name_map(db)
    now_snap = {
        "序号": row.xuhao, "小类别": row.leibie, "计划类别": row.jhlb, "项目名称": row.daibanname,
        "项目说明": row.bz, "金额": row.jine, "年初金额": row.startjine, "本年计划投资": row.zongtouzi,
        "开工年月": row.kgny, "竣工年月": row.jgny, "新建/续建": row.xjxl,
        "专管员": row.zhuanguan_name, "所属部门": names.get(row.bumenid, ""),
        "主办部门": names.get(row.zb, ""), "负责人": row.fzr, "批注": row.pizhu,
        "状态": row.zt, "年度": row.niandu,
    }
    old_snap["所属部门"] = names.get(old_snap["所属部门"], "")
    old_snap["主办部门"] = names.get(old_snap["主办部门"], "")
    for field, ov in old_snap.items():
        add_log(db, row.id, field, ov, now_snap.get(field), current.username)
    db.commit()
    return {"ok": True, "message": "更新成功"}


@router.post("/delete")
def delete_rows(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        if row.zt in (STATUS_APPROVED, STATUS_DELETED):
            return {"ok": False, "message": "该状态无法删除"}
        add_log(db, row.id, "状态", row.zt, STATUS_DELETED, current.username)
        row.zt = STATUS_DELETED
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()
    return {"ok": True, "message": "删除成功"}


def _empty_fields(row: JhSsdb) -> str:
    fields = []
    if not row.zb:
        fields.append("主办部门")
    if not row.bumenid:
        fields.append("所属部门")
    if not row.zhuanguan_name:
        fields.append("专管员")
    if not (row.daibanname or "").strip():
        fields.append("项目名称")
    if not (row.bz or "").strip():
        fields.append("项目说明")
    if not (row.leibie or "").strip():
        fields.append("小类别")
    if row.jine is None:
        fields.append("金额")
    return ("、".join(fields) + "为空") if fields else ""


@router.post("/status")
def change_status(
    data: StatusIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    if not data.ids or not data.zt:
        return {"ok": False, "message": "请选择记录"}
    ok_count = 0
    fails = []
    sms_targets = []
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        label = f"ID:{row.id} " + (f"计划号:{row.xuhao} " if row.xuhao else "") + f"项目:{row.daibanname or ''}"
        snapshot_ssdb(db, row)
        if data.zt == STATUS_SUBMITTED:
            if row.zt in (STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED):
                return {"ok": False, "message": "无法操作该状态下的记录"}
            if row.zt == STATUS_SUBMITTED:
                fails.append(label + " 已是该状态")
                continue
            empty = _empty_fields(row)
            if empty:
                fails.append(label + " " + empty)
                continue
            changes = fill_gxgz_defaults(row)
            add_log(db, row.id, "状态", row.zt, STATUS_SUBMITTED, current.username)
            for field, old, new in changes:
                add_log(db, row.id, field, old, new, current.username)
            row.zt = STATUS_SUBMITTED
            ok_count += 1
        elif data.zt == STATUS_RETURNED:
            if row.zt in (STATUS_RETURNED, STATUS_DELETED, STATUS_APPROVED):
                fails.append(label + f" 当前状态({row.zt})无法回退")
                continue
            fq = db.get(JhYyfq, row.faqiid) if row.faqiid else None
            if fq is None:
                fails.append(label + " 计划填报人不是营业所，无上报记录，无法回退")
                continue
            add_log(db, row.id, "状态", row.zt, STATUS_RETURNED, current.username)
            row.zt = STATUS_RETURNED
            if data.pizhu:
                add_log(db, row.id, "批注", row.pizhu, data.pizhu, current.username)
                row.pizhu = data.pizhu
            fq.zt = YY_RETURNED
            fq.fqtimep = datetime.now()
            fq.lastop = current.username
            if (fq.opname or "").strip():
                sms_targets.append(fq.opname)
            ok_count += 1
        else:
            return {"ok": False, "message": "不支持的流转状态"}
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()

    sms_result = None
    if data.iftel and ok_count:
        if data.zt == STATUS_SUBMITTED:
            sms_result = sms_service.notify_summary(
                db, current.username, f"您有{current.username}提交的计划待汇总",
            )
        elif data.zt == STATUS_RETURNED:
            sms_result = sms_service.notify(
                db, current.username, sms_targets,
                "您有售水回退的年度计划待处理，请及时查看。", "年度计划汇总",
            )
        db.commit()

    if fails:
        prefix = f"成功{ok_count}条，" if ok_count else ""
        return {"ok": False, "message": prefix + f"{len(fails)}条没有操作成功：" + "；".join(fails), "sms": sms_result}
    return {"ok": True, "message": f"操作成功{ok_count}条", "sms": sms_result}


@router.post("/batch/zb")
def batch_zb(
    data: ZbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    host = db.get(Department, data.bumid)
    if host is None:
        return {"ok": False, "message": "主办部门不存在"}
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        if row.zt in (STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED):
            return {"ok": False, "message": "无法操作该状态下的记录"}
        add_log(db, row.id, "主办部门", row.zb, host.name, current.username)
        add_log(db, row.id, "负责人", row.fzr, host.zg or "", current.username)
        row.zb = host.id
        row.fzr = host.zg or ""
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()
    return {"ok": True, "message": "批量修改成功"}


@router.post("/batch/jhlb")
def batch_jhlb(
    data: ValueIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        if row.zt in (STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED):
            return {"ok": False, "message": "无法操作该状态下的记录"}
        add_log(db, row.id, "计划类别", row.jhlb, data.value, current.username)
        row.jhlb = data.value
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()
    return {"ok": True, "message": "批量修改成功"}


@router.post("/batch/leibie")
def batch_leibie(
    data: ValueIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:manage")),
):
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        if row.zt in (STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED):
            return {"ok": False, "message": "无法操作该状态下的记录"}
        add_log(db, row.id, "小类别", row.leibie, data.value, current.username)
        row.leibie = data.value
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()
    return {"ok": True, "message": "批量修改成功"}


@router.get("/logs/{item_id}")
def get_logs(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    rows = log_rows(db, item_id)
    return {"rows": rows, "total": len(rows)}


@router.post("/sms")
def send_manual_sms(
    data: SmsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    """照旧 jhssdb/SendMsm:按专管员姓名发提醒短信。"""
    content = (data.nr or "").strip()
    if not content:
        return {"ok": False, "message": "请输入短信内容"}
    mobile, real_name = sms_service.find_phone(db, data.zgy)
    if not mobile:
        return {"ok": False, "message": f"未找到「{data.zgy}」的手机号，无法发送"}
    result = sms_service.send_sms(
        db, current.username, mobile, f"{current.username}给您发消息：{content}",
        "年度计划汇总", real_name or data.zgy,
    )
    db.commit()
    if not result.get("ok"):
        return {"ok": False, "message": f"发送失败：{result.get('status') or result.get('message') or '未知错误'}"}
    return {"ok": True, "message": "已成功发送！"}


def _export_query(
    db, current, *, nd, mohu, jhlb, bumenid, zb, zt, all_zgy, zgy,
):
    return ssdb_base_query(
        db, nd=nd or plan_year(), jhlb=jhlb, zb=zb, bumenid=bumenid, mohu=mohu,
        zt=zt, zgy=zgy, all_zgy=all_zgy, username=current.username,
    )


@router.get("/export")
def export_all(
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bumenid: Optional[int] = None,
    zb: Optional[int] = None,
    zt: str = "",
    all_zgy: bool = False,
    zgy: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    year = nd or plan_year()
    q = _export_query(db, current, nd=year, mohu=mohu, jhlb=jhlb, bumenid=bumenid,
                      zb=zb, zt=zt, all_zgy=all_zgy, zgy=zgy)
    plans = sort_ssdb_plans(db, q.all())
    by_cat = {}
    for p in plans:
        lb = p.jhlb if p.jhlb in ("更新改造", "大修理", "科技项目", "长期待摊", "管道工程", "中期更新", "中期大修") else "更新改造"
        by_cat.setdefault(lb, []).append(p)
    rows_by_cat = {lb: ssdb_rows(db, items) for lb, items in by_cat.items()}
    data = export_plan_workbook(rows_by_cat, year)
    fname = f"{year}年度售水事业部更新改造、大修理、科技项目计划.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@router.get("/export-page")
def export_page(
    ids: str,
    lb: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhssdb:view")),
):
    id_list = [int(x) for x in (ids or "").split(",") if x.strip()]
    plans = db.query(JhSsdb).filter(JhSsdb.id.in_(id_list)).all() if id_list else []
    plans = sort_ssdb_plans(db, plans)
    category = lb or (plans[0].jhlb if plans and plans[0].jhlb else "更新改造")
    year = plans[0].niandu if plans and plans[0].niandu else plan_year()
    data = export_plan_sheet(ssdb_rows(db, plans), year, category)
    fname = f"{year}年度售水事业部计划（当前类别）.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )
