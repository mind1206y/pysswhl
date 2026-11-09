"""实施汇总(jhsshz)接口:照旧 jhsshzController 复刻。

- 汇总列表:默认「售水待汇总」,通过/回退营业所/回退专管员/收回通过/删除
- 编序号:大修理勾选保留/本部大修理 1.N/其余按类别+部门重排
- 复制到正式计划(gx_gxgz):仅 jhsshz:admin
- 锁定营业所计划 / 锁定已通过计划;模板导入/导出

权限:jhsshz:view(查询/导出) + jhsshz:manage(日常写操作) + jhsshz:admin(复制正式/锁定)。
"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, require_permission
from app.db.session import get_db
from app.models.plan import GxGxgz, GxJindu, GxUserGxgz, JhSsdb, JhYyfq
from app.models.user import Department, User
from app.services import sms as sms_service
from app.services.plan_common import (
    DEPT_SW_BENBU, JHLB_OPTIONS, LEIBIE_OPTIONS, LOCK_APPLY, LOCK_SUMMARY,
    STATUS_APPROVED, STATUS_DELETED, STATUS_RETURNED, STATUS_SUBMITTED, STATUS_TODO,
    YY_RETURNED, add_log, dept_options, fill_gxgz_defaults, get_lock, has_perm,
    log_rows, parse_xuhao, plan_year, resolve_user_id, set_lock, snapshot_ssdb,
    sort_ssdb_plans, ssdb_base_query, ssdb_rows, ssdb_totals, zgy_options,
)
from app.services.plan_excel import export_plan_sheet, export_plan_workbook, read_sheet, template_ssdb

router = APIRouter()

STATUS_OPTIONS = [
    {"value": STATUS_SUBMITTED, "label": "售水待汇总"},
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
    approve: bool = False


class IdsIn(BaseModel):
    ids: list[int]


class StatusIn(BaseModel):
    ids: list[int]
    zt: str
    iftel: bool = False
    pizhu: str = ""


class ValueIn(BaseModel):
    ids: list[int]
    value: str


class ZbIn(BaseModel):
    ids: list[int]
    bumid: int


class RenumberIn(BaseModel):
    ids: list[int] = []
    skipBenbu: bool = False


class CopyIn(BaseModel):
    nd: int
    lb: str


class LockIn(BaseModel):
    key: str
    value: bool


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


def _duplicate(db: Session, *, name, jhlb, nd, bumenid, exclude_id=None):
    q = db.query(JhSsdb.id).filter(
        JhSsdb.daibanname == name, JhSsdb.jhlb == jhlb,
        JhSsdb.niandu == nd, JhSsdb.bumenid == bumenid,
        JhSsdb.zt != STATUS_DELETED,
    )
    if exclude_id:
        q = q.filter(JhSsdb.id != exclude_id)
    return q.first() is not None


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
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
        "locks": {"apply": get_lock(db, LOCK_APPLY), "summary": get_lock(db, LOCK_SUMMARY)},
        "perms": {
            "view": True,
            "manage": True,
            "admin": has_perm(current, "jhsshz:admin"),
        },
    }


@router.get("/list")
def list_rows(
    page: int = 1,
    size: int = 30,
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bumenid: Optional[int] = None,
    zb: Optional[int] = None,
    zgy: str = "",
    zt: str = "",
    px: bool = False,
    first_load: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    nd = nd or plan_year()
    lb = jhlb or "更新改造"
    default_zt = None
    if not zt and first_load:
        cnt = db.query(func.count(JhSsdb.id)).filter(
            JhSsdb.niandu == nd, JhSsdb.zt == STATUS_SUBMITTED,
            JhSsdb.jhlb.in_(["更新改造", "大修理"]),
        ).scalar() or 0
        default_zt = STATUS_SUBMITTED if cnt > 0 else STATUS_APPROVED
        zt = default_zt
    if not zt:
        zt = STATUS_SUBMITTED
    q = ssdb_base_query(
        db, nd=nd, jhlb=lb, zb=zb, bumenid=bumenid, mohu=mohu, zt=zt,
        zgy=zgy, all_zgy=True, exclude_deleted=False,
    )
    total = q.count()
    if px:
        if lb in ("中期更新", "中期大修"):
            plans = q.order_by(JhSsdb.nxuhao.is_(None), JhSsdb.nxuhao,
                               JhSsdb.dbtimep.desc()).offset((page - 1) * size).limit(size).all()
        else:
            plans = q.order_by(JhSsdb.bumenid.is_(None), JhSsdb.bumenid,
                               JhSsdb.nxuhao.is_(None), JhSsdb.nxuhao,
                               JhSsdb.dbtimep.desc()).offset((page - 1) * size).limit(size).all()
    else:
        plans = q.order_by(JhSsdb.dbtimep.desc(), JhSsdb.id.desc()).offset((page - 1) * size).limit(size).all()
    rows = ssdb_rows(db, plans)
    totals = ssdb_totals(q)
    # 上一年同条件金额(合计行批注列展示)
    last_q = ssdb_base_query(
        db, nd=nd - 1, jhlb=lb, zb=zb, bumenid=bumenid, mohu=mohu, zt=zt,
        zgy=zgy, all_zgy=True, exclude_deleted=False,
    )
    last_sum = sum(float(p.jine or 0) for p in last_q.all())
    footer = [{
        "bz": "合计（万元）：",
        "jine": round(totals["tongjijine"], 2),
        "pizhu": f"上一年：{round(last_sum, 2)}",
        "zongtouzi": round(totals["tongjizongtouzi"], 2),
        "startjine": round(totals["tongjinianchu"], 2),
        "tzty": round(totals["tongjitzy"], 2),
    }]
    cq = db.query(JhSsdb.jhlb, func.count(JhSsdb.id)).filter(
        JhSsdb.niandu == nd, JhSsdb.zt == STATUS_SUBMITTED,
    )
    counts = {k or "未知": v for k, v in cq.group_by(JhSsdb.jhlb).all()}
    return {
        "rows": rows, "total": total, "tj": round(totals["tongjijine"], 2),
        "tjtz": round(totals["tongjitzy"], 2), "footer": footer,
        "counts": counts, "default_zt": default_zt,
    }


@router.get("/item/{item_id}")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    row = db.get(JhSsdb, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {
        "id": row.id, "daibanname": row.daibanname or "", "bz": row.bz or "",
        "jine": row.jine, "jhlb": row.jhlb or "", "zhuanguan": row.zhuanguan_name or "",
        "zb": row.zb, "xuhao": row.xuhao or "", "bumenid": row.bumenid,
        "pizhu": row.pizhu or "", "leibie": row.leibie or "", "zt": row.zt or "",
        "startjine": row.startjine, "zongtouzi": row.zongtouzi,
        "kgny": row.kgny or "", "jgny": row.jgny or "", "xjxl": row.xjxl or "",
        "niandu": row.niandu, "opname": row.opname or "",
        "canHt": row.faqiid is not None,
    }


@router.post("/create")
def create_row(
    data: SsdbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
):
    if not data.ssbm or not data.zb or not data.zgy:
        return {"ok": False, "message": "添加失败！原因是主办单位没选,或者所属部门没选,或者专管员没选。"}
    row = JhSsdb()
    _apply_form(row, data, db)
    row.zt = STATUS_SUBMITTED
    row.dbtimep = datetime.now()
    row.kstimep = datetime.now()
    row.opname = current.username
    row.lastop = current.username
    if _duplicate(db, name=row.daibanname, jhlb=row.jhlb, nd=row.niandu, bumenid=row.bumenid):
        return {"ok": False, "message": "发现重复计划名称！"}
    changes = fill_gxgz_defaults(row)
    db.add(row)
    db.flush()
    add_log(db, row.id, "新增计划", "", row.daibanname, current.username)
    for field, old, new in changes:
        add_log(db, row.id, field, old, new, current.username)
    db.commit()
    return {"ok": True, "message": "添加成功", "id": row.id}


@router.post("/update/{item_id}")
def update_row(
    item_id: int,
    data: SsdbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
):
    row = db.get(JhSsdb, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.zt in (STATUS_DELETED, STATUS_RETURNED):
        return {"ok": False, "message": "已删除或已回退的记录无法更新"}
    if get_lock(db, LOCK_SUMMARY) and row.zt == STATUS_APPROVED:
        return {"ok": False, "message": "已开启「锁定已通过计划」：售水通过的计划无法修改"}
    if not data.ssbm or not data.zb:
        return {"ok": False, "message": "更新失败！原因是主办单位没选,或者所属部门没选。"}
    names = dept_name_map(db)
    snapshot_ssdb(db, row)
    old_snap = {
        "序号": row.xuhao, "小类别": row.leibie, "计划类别": row.jhlb, "项目名称": row.daibanname,
        "项目说明": row.bz, "金额": row.jine, "年初金额": row.startjine, "本年计划投资": row.zongtouzi,
        "开工年月": row.kgny, "竣工年月": row.jgny, "新建/续建": row.xjxl,
        "专管员": row.zhuanguan_name, "所属部门": names.get(row.bumenid, ""),
        "主办部门": names.get(row.zb, ""), "负责人": row.fzr, "批注": row.pizhu,
        "状态": row.zt, "年度": row.niandu,
    }
    _apply_form(row, data, db)
    if data.approve:
        fill_gxgz_defaults(row)
    row.lastop = current.username
    row.dbtimep = datetime.now()
    if _duplicate(db, name=row.daibanname, jhlb=row.jhlb, nd=row.niandu,
                  bumenid=row.bumenid, exclude_id=row.id):
        return {"ok": False, "message": "发现重复计划名称！"}
    now_snap = {
        "序号": row.xuhao, "小类别": row.leibie, "计划类别": row.jhlb, "项目名称": row.daibanname,
        "项目说明": row.bz, "金额": row.jine, "年初金额": row.startjine, "本年计划投资": row.zongtouzi,
        "开工年月": row.kgny, "竣工年月": row.jgny, "新建/续建": row.xjxl,
        "专管员": row.zhuanguan_name, "所属部门": names.get(row.bumenid, ""),
        "主办部门": names.get(row.zb, ""), "负责人": row.fzr, "批注": row.pizhu,
        "状态": row.zt, "年度": row.niandu,
    }
    for field, ov in old_snap.items():
        add_log(db, row.id, field, ov, now_snap.get(field), current.username)
    db.commit()
    if data.approve:
        return {"ok": True, "message": "已保存并通过", "approve": True, "id": row.id}
    return {"ok": True, "message": "更新成功"}


@router.post("/delete")
def delete_rows(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
):
    for item_id in data.ids:
        row = db.get(JhSsdb, item_id)
        if row is None:
            continue
        if row.zt == STATUS_DELETED:
            db.delete(row)
            db.flush()
            continue
        if row.zt == STATUS_APPROVED:
            return {"ok": False, "message": "删除失败，该状态无法删除！"}
        add_log(db, row.id, "状态", row.zt, STATUS_DELETED, current.username)
        row.zt = STATUS_DELETED
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()
    return {"ok": True, "message": "删除成功"}


@router.post("/status")
def change_status(
    data: StatusIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
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
        if data.zt == STATUS_APPROVED:
            if row.zt == STATUS_APPROVED:
                fails.append(label + " 已是通过计划")
                continue
            if row.zt in (STATUS_RETURNED, STATUS_DELETED):
                fails.append(label + f" 当前状态({row.zt})无法通过")
                continue
            add_log(db, row.id, "状态", row.zt, STATUS_APPROVED, current.username)
            row.zt = STATUS_APPROVED
            for field, old, new in fill_gxgz_defaults(row):
                add_log(db, row.id, field, old, new, current.username)
            ok_count += 1
        elif data.zt == STATUS_SUBMITTED:
            if row.zt in (STATUS_RETURNED, STATUS_DELETED):
                fails.append(label + f" 当前状态({row.zt})无法操作")
                continue
            add_log(db, row.id, "状态", row.zt, STATUS_SUBMITTED, current.username)
            row.zt = STATUS_SUBMITTED
            for field, old, new in fill_gxgz_defaults(row):
                add_log(db, row.id, field, old, new, current.username)
            ok_count += 1
        elif data.zt == STATUS_RETURNED:
            if row.zt in (STATUS_RETURNED, STATUS_DELETED):
                fails.append(label + f" 当前状态({row.zt})无法回退")
                continue
            if get_lock(db, LOCK_SUMMARY) and row.zt == STATUS_APPROVED:
                fails.append(label + " 已开启「锁定已通过计划」，通过的计划无法回退营业所")
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
        elif data.zt == STATUS_TODO:
            if row.zt in (STATUS_RETURNED, STATUS_DELETED, STATUS_TODO):
                fails.append(label + f" 当前状态({row.zt})无法回退专管员")
                continue
            add_log(db, row.id, "状态", row.zt, STATUS_TODO, current.username)
            row.zt = STATUS_TODO
            if (row.zhuanguan_name or "").strip():
                sms_targets.append(row.zhuanguan_name)
            ok_count += 1
        else:
            return {"ok": False, "message": "不支持的流转状态"}
        row.lastop = current.username
        row.dbtimep = datetime.now()
    db.commit()

    sms_result = None
    if data.iftel and ok_count:
        if data.zt == STATUS_RETURNED:
            sms_result = sms_service.notify(
                db, current.username, sms_targets,
                "您有售水回退的年度计划待处理，请及时查看。", "年度计划汇总",
            )
        elif data.zt == STATUS_TODO:
            sms_result = sms_service.notify(
                db, current.username, sms_targets,
                f"您有{current.username}回退的计划待处理。", "年度计划报送",
            )
        db.commit()

    if fails:
        prefix = f"成功{ok_count}条，" if ok_count else ""
        return {"ok": False, "message": prefix + f"{len(fails)}条没有操作成功：" + "；".join(fails), "sms": sms_result}
    return {"ok": True, "message": f"操作成功{ok_count}条", "sms": sms_result}


@router.post("/batch/leibie")
def batch_leibie(
    data: ValueIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
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


@router.post("/batch/zb")
def batch_zb(
    data: ZbIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
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
    current: User = Depends(require_permission("jhsshz:manage")),
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


@router.get("/renumber/check")
def check_renumber(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    names = dept_name_map(db)
    plans = db.query(JhSsdb).filter(
        JhSsdb.niandu == plan_year(), JhSsdb.zt == STATUS_APPROVED, JhSsdb.jhlb == "大修理",
    ).all()
    benbu_ids = [did for did, name in names.items() if name == DEPT_SW_BENBU]
    rows = [p for p in plans if p.bumenid in benbu_ids]
    all_filled = bool(rows) and all((p.xuhao or "").strip() for p in rows)
    return {"allFilled": all_filled, "count": len(rows)}


@router.post("/renumber")
def renumber(
    data: RenumberIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
):
    names = dept_name_map(db)
    dept_meta = {d.id: d for d in db.query(Department).all()}
    benbu_ids = {did for did, name in names.items() if name == DEPT_SW_BENBU}
    year = plan_year()
    selected = db.query(JhSsdb).filter(JhSsdb.id.in_(data.ids)).all() if data.ids else []
    selected_by_id = {p.id: p for p in selected}
    selected_plans = []
    counter = 1
    for pid in data.ids:
        plan = selected_by_id.get(pid)
        if plan is None or plan.jhlb != "大修理":
            continue
        if data.skipBenbu and plan.bumenid in benbu_ids:
            selected_plans.append(plan)
            continue
        old = plan.xuhao
        if plan.bumenid in benbu_ids:
            plan.nxuhao = counter
            plan.xuhao = f"1.{counter}"
            counter += 1
        plan.lastop = current.username
        plan.dbtimep = datetime.now()
        add_log(db, plan.id, "序号", old, plan.xuhao, current.username)
        selected_plans.append(plan)

    all_plans = db.query(JhSsdb).filter(
        JhSsdb.zt == STATUS_APPROVED, JhSsdb.niandu == year,
    ).all()
    all_plans.sort(key=lambda p: (
        p.jhlb or "",
        (dept_meta[p.bumenid].xuhaotou if p.bumenid in dept_meta and dept_meta[p.bumenid].xuhaotou is not None else 10**6),
        (dept_meta[p.zb].dnnum if p.zb in dept_meta and dept_meta[p.zb].dnnum is not None else 10**6),
        p.bz or "",
    ))
    selected_ids = {
        p.id for p in selected_plans
        if (p.xuhao or "").strip() or (data.skipBenbu and p.bumenid in benbu_ids)
    }
    counters = {}
    for plan in all_plans:
        if plan.id in selected_ids:
            continue
        if data.skipBenbu and plan.bumenid in benbu_ids:
            continue
        dept = dept_meta.get(plan.bumenid)
        prefix = dept.xuhaotou if dept and dept.xuhaotou is not None else (dept.id if dept else 0)
        key = (plan.jhlb, prefix)
        if key not in counters:
            counters[key] = counter if (plan.jhlb == "大修理" and plan.bumenid in benbu_ids) else 1
        idx = counters[key]
        old = plan.xuhao
        plan.nxuhao = idx
        plan.xuhao = f"{prefix}.{idx}"
        counters[key] += 1
        plan.lastop = current.username
        plan.dbtimep = datetime.now()
        add_log(db, plan.id, "序号", old, plan.xuhao, current.username)
    db.commit()
    return {"ok": True, "message": "编号完成"}


@router.post("/copy-to-official")
def copy_to_official(
    data: CopyIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:admin")),
):
    temps = db.query(JhSsdb).filter(
        JhSsdb.niandu == data.nd, JhSsdb.jhlb == data.lb, JhSsdb.zt == STATUS_APPROVED,
    ).all()
    if not temps:
        return {"ok": False, "message": "empty"}
    names = dept_name_map(db)
    old_count = db.query(GxGxgz).filter(GxGxgz.nd == data.nd, GxGxgz.lb == data.lb).count()
    db.query(GxGxgz).filter(GxGxgz.nd == data.nd, GxGxgz.lb == data.lb).delete(synchronize_session=False)
    for t in temps:
        db.add(GxGxgz(
            xh=t.xuhao, jine=(t.jine or 0) * 10000, fzr=t.fzr,
            zb=names.get(t.zb, ""), bm=names.get(t.bumenid, ""), bmid=t.bumenid,
            nxuhao=t.nxuhao, zgy=t.zhuanguan_name or "", nd=t.niandu, lb=t.jhlb,
            name=t.daibanname, bz=t.bz, khbj=False,
        ))
        add_log(db, t.id, "复制到正式计划",
                f"覆盖删除原有{old_count}条" if old_count else "",
                f"{data.nd}年度{data.lb}正式计划", current.username)
    db.commit()
    return {"ok": True, "message": f"已复制 {len(temps)} 条到正式计划"}


@router.get("/locks")
def get_locks(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    return {"apply": get_lock(db, LOCK_APPLY), "summary": get_lock(db, LOCK_SUMMARY)}


@router.post("/locks")
def update_lock(
    data: LockIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:admin")),
):
    if data.key == "apply":
        set_lock(db, LOCK_APPLY, data.value)
    elif data.key == "summary":
        set_lock(db, LOCK_SUMMARY, data.value)
    else:
        raise HTTPException(status_code=400, detail="未知开关")
    db.commit()
    return {"ok": True}


@router.get("/logs/{item_id}")
def get_logs(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    rows = log_rows(db, item_id)
    return {"rows": rows, "total": len(rows)}


@router.get("/template")
def download_template(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    host = db.query(Department).filter(Department.dnnum > 0).order_by(Department.id).first()
    dept = db.query(Department).filter(Department.dnnum == 0).order_by(Department.id).first()
    data = template_ssdb(host.name if host else "", dept.name if dept else "")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E8%AE%A1%E5%88%92.xlsx"},
    )


@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:manage")),
):
    content = await file.read()
    try:
        rows = read_sheet(content)
    except Exception:
        return {"ok": False, "message": "文件格式无法识别"}
    names = {d.name: d.id for d in db.query(Department).all()}
    ok_num = 0
    bad_num = 0
    created = []
    for line in rows[1:]:
        if not line or not str(line[0] or "").strip():
            break
        try:
            nd = int(float(line[0])) if line[0] not in (None, "") else plan_year()
        except (TypeError, ValueError):
            nd = plan_year()
        leibie = str(line[1] or "").strip() if len(line) > 1 else ""
        name = str(line[2] or "").strip() if len(line) > 2 else ""
        bz = str(line[3] or "").strip() if len(line) > 3 else ""
        try:
            jine = float(line[4]) if len(line) > 4 and line[4] not in (None, "") else None
        except (TypeError, ValueError):
            jine = None
        zb_name = str(line[5] or "").strip() if len(line) > 5 else ""
        bm_name = str(line[6] or "").strip() if len(line) > 6 else ""
        jhlb = str(line[7] or "").strip() if len(line) > 7 else ""
        if jine is None or zb_name not in names or bm_name not in names:
            bad_num += 1
            continue
        row = JhSsdb(
            niandu=nd, leibie=leibie, daibanname=name, bz=bz, jine=jine,
            zb=names[zb_name], bumenid=names[bm_name], jhlb=jhlb or "更新改造",
            zt=STATUS_TODO, zhuanguan=current.id, zhuanguan_name=current.username,
            dbtimep=datetime.now(), kstimep=datetime.now(),
            opname=f"{current.username}上传", lastop=current.username,
            fzr=(db.get(Department, names[zb_name]).zg or ""),
        )
        db.add(row)
        db.flush()
        add_log(db, row.id, "新增计划", "", name, current.username)
        created.append(row.id)
        ok_num += 1
    db.commit()
    return {"ok": True, "message": f"成功上传{ok_num}条记录，未上传{bad_num}条重复记录", "ids": created}


def _export_rows(
    db, *, nd, mohu, jhlb, bumenid, zb, zgy, zt,
):
    q = ssdb_base_query(
        db, nd=nd or plan_year(), jhlb=jhlb, zb=zb, bumenid=bumenid, mohu=mohu,
        zt=zt or STATUS_SUBMITTED, zgy=zgy, all_zgy=True, exclude_deleted=False,
    )
    return q.order_by(JhSsdb.bumenid, JhSsdb.nxuhao).all()


@router.get("/export")
def export_all(
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bumenid: Optional[int] = None,
    zb: Optional[int] = None,
    zgy: str = "",
    zt: str = "",
    px: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhsshz:view")),
):
    year = nd or plan_year()
    plans = sort_ssdb_plans(db, _export_rows(db, nd=year, mohu=mohu, jhlb=jhlb, bumenid=bumenid, zb=zb, zgy=zgy, zt=zt))
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
    current: User = Depends(require_permission("jhsshz:view")),
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
