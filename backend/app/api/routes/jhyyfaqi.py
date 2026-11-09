"""营业所发起计划(jhyyfaqi)接口:照旧 jhyyfaqiController 复刻。

- 未报/已报售水两个列表 + 售水填报记录(只读,以 jh_ssdb 为准)
- 新增/编辑/删除;所长提交售水 -> 生成/覆盖 jh_ssdb(专管员落实)
- 计划明细抽屉:当前待办 + 上报历史快照(jh_ssdbpz) + 字段变更日志
- 模板导入/导出;锁定营业所计划时禁止提交

权限:jhyyfaqi:view + jhyyfaqi:manage;
     jhyyfaqi:summary 对应旧系统「计划汇总」,可跨部门查看但只读。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.plan import JhSsdb, JhSsdbPz, JhYyfq
from app.models.user import Department, User
from app.services.plan_common import (
    JHLB_OPTIONS, LOCK_APPLY, STATUS_TODO, YY_RETURNED, YY_SUBMITTED, YY_SWSH,
    add_log, dept_options, get_lock, latest_ssdb_by_faqiid, log_rows,
    is_readonly_summary, log_ssdb_diff, plan_year, primary_dept_id, reported_rows, resolve_user_id,
    snapshot_ssdb, yyfq_query, yyfq_rows, yyfq_totals, zgy_options,
)
from app.services import sms as sms_service
from app.services.plan_excel import export_reported, export_yyfq, read_sheet, template_yyfq

router = APIRouter()


class YyfqIn(BaseModel):
    niandu: Optional[int] = None
    bmid: Optional[int] = None
    jhlb: str = ""
    zgy: str = ""
    faqiname: str = ""
    bz: str = ""
    jine: Optional[float] = None
    startjine: Optional[float] = None
    zongtouzi: Optional[float] = None
    kgny: str = ""
    jgny: str = ""
    xjxl: str = ""


class IdsIn(BaseModel):
    ids: list[int]


class SubmitIn(BaseModel):
    ids: list[int]
    iftel: bool = False


def _summary(current: User) -> bool:
    from app.services.plan_common import is_summary_user
    return is_summary_user(current)


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    years = [r[0] for r in db.query(JhYyfq.niandu).filter(JhYyfq.niandu.isnot(None)).distinct().all()]
    years = sorted({int(y) for y in years if y}, reverse=True)
    cur_year = plan_year()
    if years:
        next_year = max(years) + 1
        if next_year not in years:
            years.insert(0, next_year)
    if cur_year not in years:
        years.insert(0, cur_year)
    summary = _summary(current)
    return {
        "years": years,
        "default_year": cur_year,
        "summary": summary,
        "departments": dept_options(db, current) if summary else [],
        "all_departments": [
            {"id": d.id, "name": d.name} for d in
            db.query(Department).filter(Department.dnnum == 0).order_by(Department.id).all()
        ] if summary else [],
        "zgys": zgy_options(db, only_zgy=True),
        "categories": JHLB_OPTIONS,
        "default_bmid": primary_dept_id(db, current),
        "locked": get_lock(db, LOCK_APPLY),
        "perms": {
            "view": True,
            "manage": True,
            "summary": summary,
            "readonly": is_readonly_summary(current),
        },
    }


@router.get("/list")
def list_rows(
    page: int = 1,
    size: int = 30,
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bmid: Optional[int] = None,
    ck: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    nd = nd or plan_year()
    lb = jhlb or "更新改造"
    summary = _summary(current)
    scope = dept_scope_ids(db, current)
    q = yyfq_query(
        db, nd=nd, jhlb=lb, bumenid=bmid, scope=scope,
        mohu=mohu, reported=ck, summary=summary,
    )
    q = q.order_by(JhYyfq.bmid, JhYyfq.fqtimep.desc(), JhYyfq.id)
    total = q.count()
    plans = q.offset((page - 1) * size).limit(size).all()
    rows = yyfq_rows(db, plans)
    totals = yyfq_totals(q)
    footer = [{
        "bz": "合计（万元）：",
        "jine": round(totals["tongjijine"], 2),
        "startjine": round(totals["tongjinianchu"], 2),
        "tzty": round(totals["tongjitzy"], 2),
    }]
    return {
        "rows": rows, "total": total, "tj": round(totals["tongjijine"], 2),
        "tjtz": round(totals["tongjitzy"], 2), "footer": footer,
        "locked": get_lock(db, LOCK_APPLY),
    }


@router.get("/reported")
def reported_list(
    page: int = 1,
    size: int = 30,
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    nd = nd or plan_year()
    lb = jhlb or "更新改造"
    summary = _summary(current)
    scope = dept_scope_ids(db, current)
    rows = reported_rows(
        db, nd=nd, jhlb=lb, bumenid=bmid, scope=scope, summary=summary, mohu=mohu,
    )
    total = len(rows)
    start = (page - 1) * size
    page_rows = rows[start:start + size]
    tj = sum(float(r.get("jine") or 0) for r in rows)
    return {
        "rows": page_rows, "total": total, "tj": round(tj, 2), "tjtz": "",
        "footer": [],
    }


@router.get("/item/{item_id}")
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    row = db.get(JhYyfq, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    ss = (
        db.query(JhSsdb).filter(JhSsdb.faqiid == row.id)
        .order_by(JhSsdb.dbtimep.desc()).first()
    )
    return {
        "id": row.id, "faqiname": row.faqiname or "", "bz": row.bz or "",
        "jine": row.jine, "jhlb": row.jhlb or "", "zgy": row.zgy_name or "",
        "bmid": row.bmid, "startjine": row.startjine, "zongtouzi": row.zongtouzi,
        "kgny": row.kgny or "", "jgny": row.jgny or "", "xjxl": row.xjxl or "",
        "zgy_name": row.zgy_name or "", "zt": row.zt or "",
        "pizhu": ss.pizhu if ss and ss.pizhu else "",
    }


def _apply(row: JhYyfq, data: YyfqIn, db: Session, current: User) -> None:
    row.niandu = data.niandu or plan_year()
    row.jhlb = data.jhlb
    row.zgy_name = (data.zgy or "").strip()
    row.zgy = resolve_user_id(db, row.zgy_name)
    row.faqiname = (data.faqiname or "").strip()
    row.bz = (data.bz or "").strip()
    row.jine = data.jine
    row.startjine = data.startjine
    row.zongtouzi = data.zongtouzi
    row.kgny = data.kgny
    row.jgny = data.jgny
    row.xjxl = data.xjxl
    row.lastop = current.username
    row.fqtimep = datetime.now()


@router.post("/create")
def create_row(
    data: YyfqIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:manage")),
):
    if is_readonly_summary(current):
        return {"ok": False, "message": "计划汇总权限仅可查看，不能新增计划"}
    if not (data.zgy or "").strip():
        return {"ok": False, "message": "请选择专管员"}
    bmid = primary_dept_id(db, current)
    if data.bmid and (current.is_superuser or _summary(current)):
        bmid = data.bmid
    if not bmid:
        first = db.query(Department.id).order_by(Department.id).first()
        bmid = first[0] if first else None
    if not bmid:
        return {"ok": False, "message": "当前账号未分配部门，且系统中没有可用部门"}
    row = JhYyfq(zt=YY_SUBMITTED, beginTime=datetime.now(), opid=current.id,
                 opname=current.username, bmid=bmid)
    _apply(row, data, db, current)
    db.add(row)
    db.commit()
    return {"ok": True, "message": "添加成功", "id": row.id}


@router.post("/update/{item_id}")
def update_row(
    item_id: int,
    data: YyfqIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:manage")),
):
    if is_readonly_summary(current):
        return {"ok": False, "message": "计划汇总权限仅可查看，不能编辑计划"}
    row = db.get(JhYyfq, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if row.zt == YY_SWSH:
        return {"ok": False, "message": "已提交售水审核，不能修改"}
    if not (data.zgy or "").strip():
        return {"ok": False, "message": "请选择专管员"}
    _apply(row, data, db, current)
    row.zt = YY_SUBMITTED
    db.commit()
    return {"ok": True, "message": "更新成功"}


@router.post("/delete")
def delete_rows(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:manage")),
):
    if is_readonly_summary(current):
        return {"ok": False, "message": "计划汇总权限仅可查看，不能删除计划"}
    for item_id in data.ids:
        row = db.get(JhYyfq, item_id)
        if row is None:
            continue
        ss_rows = db.query(JhSsdb).filter(JhSsdb.faqiid == item_id).all()
        if any(s.zt == "售水通过" for s in ss_rows):
            return {"ok": False, "message": "已是通过计划，不能删除"}
        for s in ss_rows:
            db.delete(s)
        db.delete(row)
    db.commit()
    return {"ok": True, "message": "删除成功"}


@router.post("/submit")
def submit_to_water(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:manage")),
):
    if is_readonly_summary(current):
        return {"ok": False, "message": "计划汇总权限仅可查看，不能提交售水"}
    if get_lock(db, LOCK_APPLY):
        return {"ok": False, "message": "计划申报提交已锁定"}
    if not data.ids:
        return {"ok": False, "message": "请选择要提交的计划"}
    ok_count = 0
    fails = []
    sms_targets = []
    dept_names = dept_name_map(db)
    for item_id in data.ids:
        fq = db.get(JhYyfq, item_id)
        if fq is None:
            continue
        label = f"ID:{fq.id} 项目:{fq.faqiname or ''}"
        if not (fq.zgy_name or "").strip():
            fails.append(label + " 没有选择专管员")
            continue
        if fq.zt != YY_SUBMITTED:
            fails.append(label + f" 状态为「{fq.zt}」的记录不允许提交售水，仅「提交审核」状态可提交")
            continue
        fq.zt = YY_SWSH
        fq.lastop = current.username
        fq.fqtimep = datetime.now()
        ss = (
            db.query(JhSsdb).filter(JhSsdb.faqiid == fq.id)
            .order_by(JhSsdb.dbtimep.desc()).first()
        )
        if ss is None:
            db.add(JhSsdb(
                zt=STATUS_TODO, faqiid=fq.id, bz=fq.bz, daibanname=fq.faqiname,
                jine=fq.jine, niandu=fq.niandu, zhuanguan=fq.zgy,
                zhuanguan_name=fq.zgy_name, opname=fq.opname, jhlb=fq.jhlb,
                lastop=fq.lastop, kstimep=fq.fqtimep, dbtimep=fq.fqtimep,
                bumenid=fq.bmid or 0, zongtouzi=fq.zongtouzi, kgny=fq.kgny,
                jgny=fq.jgny, xjxl=fq.xjxl, startjine=fq.startjine,
            ))
        else:
            old = {
                "序号": ss.xuhao, "小类别": ss.leibie, "计划类别": ss.jhlb,
                "项目名称": ss.daibanname, "项目说明": ss.bz, "金额": ss.jine,
                "年初金额": ss.startjine, "本年计划投资": ss.zongtouzi,
                "开工年月": ss.kgny, "竣工年月": ss.jgny, "新建/续建": ss.xjxl,
                "专管员": ss.zhuanguan_name, "所属部门": ss.bumenid, "主办部门": ss.zb,
                "负责人": ss.fzr, "批注": ss.pizhu, "状态": ss.zt, "年度": ss.niandu,
            }
            snapshot_ssdb(db, ss)
            ss.zt = STATUS_TODO
            ss.dbtimep = datetime.now()
            ss.bz = fq.bz
            ss.daibanname = fq.faqiname
            ss.jine = fq.jine
            ss.niandu = fq.niandu
            ss.zhuanguan = fq.zgy
            ss.zhuanguan_name = fq.zgy_name
            ss.opname = fq.opname
            ss.jhlb = fq.jhlb
            ss.lastop = fq.lastop
            ss.startjine = fq.startjine
            ss.zongtouzi = fq.zongtouzi
            ss.kgny = fq.kgny
            ss.jgny = fq.jgny
            ss.xjxl = fq.xjxl
            log_ssdb_diff(db, ss, old, current.username)
        sms_targets.append((dept_names.get(fq.bmid, ""), fq.zgy_name))
        ok_count += 1
    db.commit()

    sms_result = None
    if data.iftel and ok_count:
        treated = set()
        sent, skipped, failed = 0, [], []
        for dept_name, zgy_name in sms_targets:
            key = (dept_name, zgy_name)
            if not zgy_name or key in treated:
                continue
            treated.add(key)
            mobile, real_name = sms_service.find_phone(db, zgy_name)
            if not mobile:
                skipped.append(zgy_name)
                continue
            result = sms_service.send_sms(
                db, current.username, mobile,
                f"您有{dept_name}提交的计划待处理", "年度计划报送", real_name or zgy_name,
            )
            if result.get("ok"):
                sent += 1
            else:
                failed.append({"name": zgy_name, "message": result.get("status")})
        db.commit()
        sms_result = {"sent": sent, "skipped": skipped, "failed": failed}

    if fails:
        prefix = f"提交成功{ok_count}条，" if ok_count else ""
        return {"ok": False, "message": prefix + f"{len(fails)}条没有提交成功：" + "；".join(fails), "sms": sms_result}
    return {"ok": True, "message": f"提交成功{ok_count}条", "sms": sms_result}


@router.get("/detail/{item_id}")
def detail(
    item_id: int,
    ul: int = 0,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    names = dept_name_map(db)
    if ul:
        cur_ss = db.get(JhSsdb, item_id)
        history = []
    else:
        cur_ss = (
            db.query(JhSsdb).filter(JhSsdb.faqiid == item_id)
            .order_by(JhSsdb.dbtimep.desc()).first()
        )
        raw = (
            db.query(JhSsdbPz).filter(JhSsdbPz.faqiid == item_id)
            .order_by(JhSsdbPz.dbtimep.desc()).all()
        )
        seen = set()
        history = []
        for h in raw:
            key = (h.xuhao, h.daibanname, h.bz, h.jine, h.niandu, h.zb, h.fzr,
                   h.jhlb, h.zt, h.opname, h.zhuanguan_name, h.bumenid, h.faqiid,
                   h.kstimep, h.pizhu, h.lastop, h.startjine, h.zongtouzi,
                   h.kgny, h.jgny, h.xjxl)
            if key in seen:
                continue
            seen.add(key)
            history.append(h)
        if cur_ss is not None and history and history[0].dbtimep == cur_ss.dbtimep \
                and history[0].zt == cur_ss.zt:
            history = history[1:]

    def row_dict(x, *, is_current=False):
        if x is None:
            return None
        return {
            "id": x.id,
            "xuhao": x.xuhao or "",
            "daibanname": x.daibanname or "",
            "bz": x.bz or "",
            "jine": x.jine,
            "niandu": x.niandu,
            "zb": names.get(x.zb, ""),
            "fzr": x.fzr or "",
            "jhlb": x.jhlb or "",
            "zt": x.zt or "",
            "opname": x.opname or "",
            "zgy": x.zhuanguan_name or "",
            "ssbm": names.get(x.bumenid, ""),
            "faqiid": x.faqiid,
            "kstimep": x.kstimep.strftime("%Y-%m-%d %H:%M:%S") if x.kstimep else "",
            "dbtimep": x.dbtimep.strftime("%Y-%m-%d %H:%M:%S") if x.dbtimep else "",
            "pizhu": x.pizhu or "",
            "lastop": x.lastop or "",
            "startjine": x.startjine,
            "zongtouzi": x.zongtouzi,
            "kgny": x.kgny or "",
            "jgny": x.jgny or "",
            "xjxl": x.xjxl or "",
        }

    logs = log_rows(db, cur_ss.id) if cur_ss else []
    return {
        "rows": [row_dict(h) for h in history],
        "total": len(history),
        "current": row_dict(cur_ss, is_current=True),
        "logs": logs,
    }


@router.get("/template")
def download_template(
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    data = template_yyfq()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%9B%B4%E6%96%B0%E6%94%B9%E9%80%A0%E8%AE%A1%E5%88%92.xlsx"},
    )


@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:manage")),
):
    if is_readonly_summary(current):
        return {"ok": False, "message": "计划汇总权限仅可查看，不能导入计划"}
    bmid = primary_dept_id(db, current)
    if not bmid and current.is_superuser:
        first = db.query(Department.id).order_by(Department.id).first()
        bmid = first[0] if first else None
    if not bmid:
        return {"ok": False, "message": "当前账号未分配部门"}
    content = await file.read()
    try:
        rows = read_sheet(content)
    except Exception:
        return {"ok": False, "message": "文件格式无法识别"}
    ok_num = 0
    bad_num = 0
    for line in rows[2:]:
        if not line or not str(line[0] or "").strip():
            break
        name = str(line[0] or "").strip()
        bz = str(line[1] or "").strip() if len(line) > 1 else ""
        try:
            jine = float(line[2]) if len(line) > 2 and line[2] not in (None, "") else None
        except (TypeError, ValueError):
            jine = None
        zgy_name = str(line[3] or "").strip() if len(line) > 3 else ""
        jhlb = str(line[4] or "").strip() if len(line) > 4 else ""
        if not name or jine is None:
            bad_num += 1
            continue
        db.add(JhYyfq(
            faqiname=name, bz=bz, jine=jine, zgy_name=zgy_name,
            zgy=resolve_user_id(db, zgy_name), jhlb=jhlb or "更新改造",
            zt=YY_SUBMITTED, opid=current.id, opname=current.username,
            niandu=plan_year(), bmid=bmid, fqtimep=datetime.now(),
            beginTime=datetime.now(), lastop=current.username,
        ))
        ok_num += 1
    db.commit()
    return {"ok": True, "message": f"成功导入{ok_num}条，跳过{bad_num}条"}


@router.get("/export")
def export_apply(
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bmid: Optional[int] = None,
    ck: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    nd = nd or plan_year()
    lb = jhlb or "更新改造"
    summary = _summary(current)
    q = yyfq_query(
        db, nd=nd, jhlb=lb, bumenid=bmid, scope=dept_scope_ids(db, current),
        mohu=mohu, reported=ck, summary=summary,
    )
    rows = yyfq_rows(db, q.order_by(JhYyfq.bmid, JhYyfq.fqtimep.desc()).all())
    data = export_yyfq(rows, nd)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E8%90%A5%E4%B8%9A%E6%89%80%E8%AE%A1%E5%88%92.xlsx"},
    )


@router.get("/export-reported")
def export_reported_excel(
    nd: Optional[int] = None,
    mohu: str = "",
    jhlb: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jhyyfaqi:view")),
):
    nd = nd or plan_year()
    lb = jhlb or "更新改造"
    rows = reported_rows(
        db, nd=nd, jhlb=lb, bumenid=bmid, scope=dept_scope_ids(db, current),
        summary=_summary(current), mohu=mohu,
    )
    data = export_reported(rows, nd)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E5%94%AE%E6%B0%B4%E5%A1%AB%E6%8A%A5%E8%AE%B0%E5%BD%95.xlsx"},
    )
