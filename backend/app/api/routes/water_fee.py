"""水费系统(特殊群体水费优惠管理)接口。

列表筛选/单条与批量编辑(字段日志)/变动历史提取与编辑/取消同步/统计;Excel 相关见 water_fee_excel.py。
业务逻辑照旧系统 ShuifeixtController 复刻。
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map as _dept_name_map, dept_scope_ids as _dept_scope_ids, require_permission
from app.core.security import create_short_token
from app.db.session import get_db
from app.models.user import User, Department
from app.models.water_fee import Shuifeixitong, ShuifeixitongBiandong, ShuifeixitongLog, ShuifeixitongQuxiao
from app.services.water_fee_common import (
    FIELD_LABELS,
    TEXT_FIELDS,
    DATE_FIELDS,
    INT_FIELDS,
    MOHU_FIELDS,
    diff_and_log,
    extract_snapshot,
    snapshot,
    sync_quxiao_table,
)

router = APIRouter()

# 统计里"已匹配"的口径:银行账号非空(照旧 Export 报表口径:有银行账户视为已匹配)


class WaterFeeIn(BaseModel):
    """全部可选:更新时没传的字段不动。"""

    shi: Optional[str] = None
    quxian: Optional[str] = None
    xiangzhen: Optional[str] = None
    cun: Optional[str] = None
    shixiang: Optional[str] = None
    xingming: Optional[str] = None
    sfz: Optional[str] = None
    juzhudizhi: Optional[str] = None
    dianhua: Optional[str] = None
    kaihuming: Optional[str] = None
    yinhangzhanghao: Optional[str] = None
    kaihuhang: Optional[str] = None
    kaihushenfenzheng: Optional[str] = None
    yinhangbeizhu: Optional[str] = None
    ksbriqi: Optional[datetime] = None
    jsbriqi: Optional[datetime] = None
    tekunlei: Optional[str] = None
    gongyangfangshi: Optional[str] = None
    gongyangjigou: Optional[str] = None
    bm: Optional[str] = None
    bmid: Optional[int] = None
    yonghuhao: Optional[str] = None
    qitayongshui: Optional[str] = None
    beizhu: Optional[str] = None
    shouliriqi: Optional[datetime] = None
    youhuiksriqi: Optional[datetime] = None
    youhuijsriqi: Optional[datetime] = None
    wushuifeihetui: Optional[datetime] = None
    daoruqingkuang: Optional[str] = None
    fanhuiminzhengju: Optional[str] = None
    guitaishouli: Optional[str] = None
    nd: Optional[int] = None
    bmid: Optional[int] = None
    yueshu: Optional[int] = None
    quxiaoriqi: Optional[datetime] = None
    biaoming: Optional[str] = None
    wenjianxuhao: Optional[int] = None


class IdsIn(BaseModel):
    ids: List[int]


class BatchUpdateIn(BaseModel):
    ids: List[int]
    data: WaterFeeIn


class BiandongIn(BaseModel):
    yonghuhao: Optional[str] = None
    qitayongshui: Optional[str] = None
    beizhu: Optional[str] = None
    youhuiksriqi: Optional[datetime] = None
    youhuijsriqi: Optional[datetime] = None
    wushuifeihetui: Optional[datetime] = None
    daoruqingkuang: Optional[str] = None
    fanhuiminzhengju: Optional[str] = None
    guitaishouli: Optional[str] = None
    yueshu: Optional[int] = None
    bmid: Optional[int] = None
    shoulishijian: Optional[datetime] = None
    juzhudizhi: Optional[str] = None


def _ensure_in_scope(db: Session, user: User, rows: list):
    """非管理员只能操作本人部门(含子部门)范围内的记录(照旧:管理标签只管上传导入,编辑靠部门范围兜底)。"""
    scope = _dept_scope_ids(db, user)
    if scope is not None:
        for r in rows:
            if r.bmid is None or r.bmid not in scope:
                raise HTTPException(status_code=403, detail="只能操作本部门(含子部门)的记录")


def _get_row(db: Session, row_id: int) -> Shuifeixitong:
    row = db.get(Shuifeixitong, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return row


def _bmid_to_log_names(before: dict, after: dict, names: dict):
    """把 diff 字典里的 bmid 换成部门名,修改日志展示营业所名称而不是数字 id。"""
    for d in (before, after):
        if d.get("bmid") is not None:
            d["bmid"] = names.get(d["bmid"], str(d["bmid"]))


def _apply_fields(row, data: WaterFeeIn):
    """只写请求里显式传入的字段(pydantic fields_set 区分"未传"与"传了 null=清空")。"""
    provided = data.model_fields_set
    for f in TEXT_FIELDS:
        if f in provided:
            v = getattr(data, f)
            setattr(row, f, v.strip() if isinstance(v, str) else v)
    for f in DATE_FIELDS - {"caozuoriqi"}:
        if f in provided:
            setattr(row, f, getattr(data, f))
    for f in ("nd", "bmid", "yueshu"):
        if f in provided:
            setattr(row, f, getattr(data, f))


def _filtered_query(
    db: Session,
    nd: str,
    bmid: Optional[int],
    mohu: str,
    qitayongshui: str,
    daoruqingkuang: str,
    show_quxiao: bool,
    dup_sfz: bool,
    yhh: str = "",
    fanmin: bool = False,
    scope_ids: Optional[set] = None,
):
    query = db.query(Shuifeixitong)
    # 年度多选(逗号分隔),照旧系统:不选年度不返回数据
    years = [int(x) for x in nd.split(",") if x.strip().isdigit()]
    if not years:
        return None
    query = query.filter(Shuifeixitong.nd.in_(years))
    if bmid:
        query = query.filter(Shuifeixitong.bmid == bmid)
    if scope_ids is not None:
        # 部门数据权限:只看本部门(含子部门)记录(照旧 bmcj)
        query = query.filter(Shuifeixitong.bmid.in_(scope_ids))
    if yhh == "有":
        query = query.filter(Shuifeixitong.yonghuhao != "", Shuifeixitong.yonghuhao.isnot(None))
    elif yhh == "无":
        conds = or_(Shuifeixitong.yonghuhao == "", Shuifeixitong.yonghuhao.is_(None))
        query = query.filter(conds)
    if fanmin:
        query = query.filter(Shuifeixitong.fanhuiminzhengju == "是")
    if mohu.strip():
        kw = f"%{mohu.strip()}%"
        query = query.filter(or_(*[getattr(Shuifeixitong, f).like(kw) for f in MOHU_FIELDS]))
    if qitayongshui.strip():
        vals = [v.strip() for v in qitayongshui.split(",") if v.strip()]
        conds = []
        for v in vals:
            if v == "__empty__":
                conds.append(or_(Shuifeixitong.qitayongshui.is_(None), Shuifeixitong.qitayongshui == ""))
            elif v == "__notempty__":
                conds.append(Shuifeixitong.qitayongshui.notin_(["", None]))
            else:
                conds.append(Shuifeixitong.qitayongshui == v)
        query = query.filter(or_(*conds))
    if daoruqingkuang.strip():
        vals = [v.strip() for v in daoruqingkuang.split(",") if v.strip()]
        query = query.filter(Shuifeixitong.daoruqingkuang.in_(vals))
    if not show_quxiao:
        query = query.filter(Shuifeixitong.quxiaoriqi.is_(None))
    if dup_sfz:
        sub = (
            db.query(Shuifeixitong.sfz)
            .filter(Shuifeixitong.sfz != "", Shuifeixitong.nd.in_(years))
            .group_by(Shuifeixitong.sfz)
            .having(func.count() > 1)
            .subquery()
        )
        query = query.filter(Shuifeixitong.sfz.in_(sub))
    return query


@router.get("")
def list_water_fee(
    page: int = 1,
    size: int = 20,
    nd: str = "",
    bmid: Optional[int] = None,
    mohu: str = "",
    qitayongshui: str = "",
    daoruqingkuang: str = "",
    show_quxiao: bool = False,
    dup_sfz: bool = False,
    yhh: str = "",
    fanmin: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    query = _filtered_query(
        db, nd, bmid, mohu, qitayongshui, daoruqingkuang, show_quxiao, dup_sfz, yhh, fanmin,
        scope_ids=_dept_scope_ids(db, current),
    )
    if query is None:
        return {"total": 0, "items": [], "need_year": True}
    total = query.count()
    rows = query.order_by(Shuifeixitong.id.desc()).offset((page - 1) * size).limit(size).all()
    # 每行日志数(旧系统"历史"列)
    ids = [r.id for r in rows]
    log_counts = {}
    if ids:
        pairs = (
            db.query(ShuifeixitongLog.main_id, func.count())
            .filter(ShuifeixitongLog.main_id.in_(ids), ShuifeixitongLog.source == "shuifeixitong")
            .group_by(ShuifeixitongLog.main_id)
            .all()
        )
        log_counts = dict(pairs)
    dept_names = _dept_name_map(db)
    items = []
    for r in rows:
        d = r.to_dict()
        d["log_count"] = log_counts.get(r.id, 0)
        # 营业所(关联部门名,照旧 Get 的 bumen 列)
        d["bumen"] = dept_names.get(r.bmid, "")
        items.append(d)
    return {"total": total, "items": items}


@router.get("/years")
def list_years(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    rows = db.query(Shuifeixitong.nd).filter(Shuifeixitong.nd.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows}, reverse=True)


@router.get("/daoru-options")
def list_daoru_options(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    """系统导入情况去重值(照旧系统按年度分组)。"""
    rows = (
        db.query(Shuifeixitong.nd, Shuifeixitong.daoruqingkuang)
        .filter(Shuifeixitong.daoruqingkuang != "")
        .distinct()
        .all()
    )
    out = {}
    for nd, v in rows:
        out.setdefault(nd, set()).add(v)
    return [{"nd": nd, "values": sorted(vs)} for nd, vs in sorted(out.items(), reverse=True)]


@router.get("/statistics")
def statistics(
    nd: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """部门×事项 户数/已匹配/匹配率(照旧 Export 报表口径:
    排除已取消;已匹配 = 用户号或其他用水情况任一非空;按关联部门分组)。"""
    rows = (
        db.query(
            Shuifeixitong.bmid,
            Shuifeixitong.bm,
            Shuifeixitong.shixiang,
            func.count(),
            func.sum(case(
                (
                    and_(
                        or_(Shuifeixitong.yonghuhao != "", Shuifeixitong.qitayongshui != ""),
                        Shuifeixitong.quxiaoriqi.is_(None),
                    ),
                    1,
                ),
                else_=0,
            )),
        )
        .filter(Shuifeixitong.nd == nd, Shuifeixitong.quxiaoriqi.is_(None))
        .group_by(Shuifeixitong.bmid, Shuifeixitong.bm, Shuifeixitong.shixiang)
        .all()
    )
    dept_names = _dept_name_map(db)
    return [
        {"bm": dept_names.get(bmid) or bm or "", "shixiang": shixiang or "", "total": c, "matched": m,
         "rate": round(m / c * 100, 1) if c else 0}
        for bmid, bm, shixiang, c, m in rows
    ]


@router.get("/logs/{row_id}")
def list_logs(
    row_id: int,
    source: str = "shuifeixitong",
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    if source not in ("shuifeixitong", "shuifeixitongbiandong"):
        raise HTTPException(status_code=400, detail="source 不合法")
    rows = (
        db.query(ShuifeixitongLog)
        .filter(ShuifeixitongLog.main_id == row_id, ShuifeixitongLog.source == source)
        .order_by(ShuifeixitongLog.id.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


@router.post("")
def create_water_fee(
    data: WaterFeeIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """单条新增(旧系统无此功能,新系统补齐)。用户号必填,年度内按 身份证+事项 查重。
    部门归属照旧:登录人部门,多部门可在本人部门内自选,越界/未选兜底第一个。"""
    if data.yonghuhao is None or not data.yonghuhao.strip():
        raise HTTPException(status_code=400, detail="用户号不能为空")
    if data.nd is None:
        raise HTTPException(status_code=400, detail="年度不能为空")
    row = Shuifeixitong()
    _apply_fields(row, data)
    if row.sfz and row.shixiang:
        dup = (
            db.query(Shuifeixitong)
            .filter(
                Shuifeixitong.nd == row.nd, Shuifeixitong.sfz == row.sfz,
                Shuifeixitong.shixiang == row.shixiang,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail="该年度已存在相同身份证+事项的记录")
    row.caozuo = current.username
    row.caozuoriqi = datetime.now()
    # 归属部门照旧:登录人部门(多部门可在本人部门内自选,越界/未选兜底第一个)
    if not current.is_superuser and current.departments:
        my_ids = [d.id for d in current.departments]
        row.bmid = row.bmid if row.bmid in my_ids else my_ids[0]
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.put("/{row_id}")
def update_water_fee(
    row_id: int,
    data: WaterFeeIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """单条编辑(照旧 SaveEdit,不要求管理标签;范围由部门作用域兜底)。"""
    row = _get_row(db, row_id)
    _ensure_in_scope(db, current, [row])
    if data.yonghuhao is not None and not data.yonghuhao.strip():
        raise HTTPException(status_code=400, detail="用户号不能为空")
    before = snapshot(row)
    _apply_fields(row, data)
    # bmid 差异按部门名写日志(照旧旧系统取 bb_bumen.bm)
    names = _dept_name_map(db)
    _bmid_to_log_names(before, {f: getattr(row, f) for f in before}, names)
    n = diff_and_log(db, before, {f: getattr(row, f) for f in before}, row.id, current, "shuifeixitong")
    # 照旧 SaveEdit:受理日期为空且填了用户号 → 自动默认当前日期(不写日志)
    if row.shouliriqi is None and row.yonghuhao:
        row.shouliriqi = datetime.now()
    # 取消日期变更 → 同步取消名单表
    if before["quxiaoriqi"] != row.quxiaoriqi:
        sync_quxiao_table(db, row, current)
    row.caozuo = current.username
    row.caozuoriqi = datetime.now()
    db.commit()
    return {**row.to_dict(), "log_added": n}


@router.post("/batch-update")
def batch_update(
    data: BatchUpdateIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """批量修改勾选记录的指定字段(照旧 BatchUpdate,逐条写日志;非管理员限本部门记录)。"""
    if not data.ids:
        raise HTTPException(status_code=400, detail="请先勾选记录")
    rows = db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(data.ids)).all()
    _ensure_in_scope(db, current, rows)
    changed = 0
    names = _dept_name_map(db)
    for row in rows:
        before = snapshot(row)
        old_beizhu = row.beizhu
        _apply_fields(row, data.data)
        # 备注照旧系统 BatchUpdate:非空值追加而不是覆盖(旧提示"备注字段不会覆盖")
        if "beizhu" in data.data.model_fields_set and (data.data.beizhu or "").strip() and old_beizhu:
            row.beizhu = f"{old_beizhu}\n{data.data.beizhu}"
        _bmid_to_log_names(before, {f: getattr(row, f) for f in before}, names)
        changed += diff_and_log(db, before, {f: getattr(row, f) for f in before}, row.id, current, "shuifeixitong")
        if before["quxiaoriqi"] != row.quxiaoriqi:
            sync_quxiao_table(db, row, current)
        row.caozuo = current.username
        row.caozuoriqi = datetime.now()
    db.commit()
    return {"message": f"已修改 {len(rows)} 条记录,共 {changed} 处变更"}


@router.post("/batch-delete")
def batch_delete(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请先勾选记录")
    n = db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(data.ids)).delete(synchronize_session=False)
    # 关联的变动/日志一并清理
    db.query(ShuifeixitongBiandong).filter(ShuifeixitongBiandong.zhuid.in_(data.ids)).delete(synchronize_session=False)
    db.query(ShuifeixitongLog).filter(ShuifeixitongLog.main_id.in_(data.ids)).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {n} 条"}


# ==================== 变动历史 ====================

class ExtractIn(BaseModel):
    ids: List[int]
    # 编辑弹窗提取时传当前表单值(照旧 ExtractToHistory:快照的是表单当前数据,不是库里的旧值)
    data: Optional[dict] = None


@router.post("/extract")
def extract_to_history(
    data_in: ExtractIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """勾选记录提取到变动历史(照旧 ExtractToHistory;非管理员限本部门记录)。"""
    if not data_in.ids:
        raise HTTPException(status_code=400, detail="请先勾选记录")
    rows = db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(data_in.ids)).all()
    _ensure_in_scope(db, current, rows)
    form = data_in.data
    for row in rows:
        if form is not None:
            # 照旧:用表单当前值生成快照;受理时间为空且填了用户号 → 默认当前
            shouli = form.get("shouliriqi") or (datetime.now() if form.get("yonghuhao") else None)
            db.add(ShuifeixitongBiandong(
                zhuid=row.id,
                biandongriqi=datetime.now(),
                yonghuhao=form.get("yonghuhao") or "",
                qitayongshui=form.get("qitayongshui") or "",
                beizhu=form.get("beizhu"),
                youhuiksriqi=_parse_ym(form.get("youhuiksriqi")),
                youhuijsriqi=_parse_ym(form.get("youhuijsriqi")),
                wushuifeihetui=_parse_ym(form.get("wushuifeihetui")),
                daoruqingkuang=form.get("daoruqingkuang") or "",
                fanhuiminzhengju=form.get("fanhuiminzhengju") or "",
                guitaishouli=form.get("guitaishouli") or "",
                yueshu=form.get("yueshu"),
                caozuo=current.username,
                shoulishijian=shouli,
                juzhudizhi=form.get("juzhudizhi") or "",
            ))
        else:
            db.add(extract_snapshot(row, current))
    db.commit()
    return {"message": f"已提取 {len(rows)} 条到变动历史"}


def _parse_ym(v):
    """前端表单的日期字符串 → datetime(解析失败原样返回 None)。"""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            continue
    return None


@router.post("/batch-in-lishi")
def batch_in_lishi(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    """批量导入历史(照旧 BatchInLishi:快照 + 月数空且优惠起止齐则自动算月数)。"""
    if not data.ids:
        raise HTTPException(status_code=400, detail="请先勾选记录")
    rows = db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(data.ids)).all()
    for row in rows:
        snap = extract_snapshot(row, current)
        if snap.yueshu is None and snap.youhuiksriqi and snap.youhuijsriqi:
            from app.services.water_fee_common import calc_months
            snap.yueshu = calc_months(snap.youhuiksriqi, snap.youhuijsriqi)
        db.add(snap)
    db.commit()
    return {"message": f"已导入 {len(rows)} 条历史记录"}


@router.get("/{row_id}/history")
def list_row_history(
    row_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    rows = (
        db.query(ShuifeixitongBiandong)
        .filter(ShuifeixitongBiandong.zhuid == row_id)
        .order_by(ShuifeixitongBiandong.id.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


@router.get("/biandong")
def list_biandong(
    page: int = 1,
    size: int = 20,
    nd: str = "",
    mohu: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """历史 Tab:变动记录分页,联查主表年度/身份证/姓名/营业所;附 has_log(照旧 GetHis)。"""
    from sqlalchemy.orm import aliased
    main = aliased(Shuifeixitong)
    query = db.query(ShuifeixitongBiandong).join(main, ShuifeixitongBiandong.zhuid == main.id)
    if nd.strip():
        years = [int(x) for x in nd.split(",") if x.strip().isdigit()]
        if years:
            query = query.filter(main.nd.in_(years))
    if bmid:
        query = query.filter(main.bmid == bmid)
    # 部门数据权限:按主表 bmid 限定(照旧 bmcj)
    scope_ids = _dept_scope_ids(db, current)
    if scope_ids is not None:
        query = query.filter(main.bmid.in_(scope_ids))
    if mohu.strip():
        kw = f"%{mohu.strip()}%"
        query = query.filter(or_(
            ShuifeixitongBiandong.yonghuhao.like(kw),
            ShuifeixitongBiandong.qitayongshui.like(kw),
            ShuifeixitongBiandong.juzhudizhi.like(kw),
        ))
    total = query.count()
    rows = query.order_by(ShuifeixitongBiandong.id.desc()).offset((page - 1) * size).limit(size).all()
    # 附主表信息 + 是否有变动日志(照旧 GetHis 的 hasLog:查看记录红字)
    zhuids = {r.zhuid for r in rows if r.zhuid}
    mains = {}
    if zhuids:
        for m in db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(zhuids)).all():
            mains[m.id] = {"nd": m.nd, "sfz": m.sfz, "xingming": m.xingming, "bm": m.bm}
    log_ids = set()
    if rows:
        log_ids = {
            r[0]
            for r in db.query(ShuifeixitongLog.main_id)
            .filter(
                ShuifeixitongLog.source == "shuifeixitongbiandong",
                ShuifeixitongLog.main_id.in_([r.id for r in rows]),
            )
            .distinct()
            .all()
        }
    items = []
    for r in rows:
        d = r.to_dict()
        d["main"] = mains.get(r.zhuid)
        d["has_log"] = r.id in log_ids
        items.append(d)
    return {"total": total, "items": items}


@router.put("/biandong/{row_id}")
def update_biandong(
    row_id: int,
    data: BiandongIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    row = db.get(ShuifeixitongBiandong, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="变动记录不存在")
    bd_labels = {k: v for k, v in FIELD_LABELS.items() if k in BiandongIn.__fields__}
    before = {f: getattr(row, f, None) for f in bd_labels}
    for f in bd_labels:
        v = getattr(data, f)
        if v is not None:
            setattr(row, f, v.strip() if isinstance(v, str) else v)
    after = {f: getattr(row, f, None) for f in bd_labels}
    # bmid 差异按部门名写日志(照旧 oldBm/newBm 取 bb_bumen.bm)
    _bmid_to_log_names(before, after, _dept_name_map(db))
    n = diff_and_log(db, before, after, row.id, current, "shuifeixitongbiandong")
    db.commit()
    return {**row.to_dict(), "log_added": n}


@router.post("/biandong/batch-delete")
def batch_delete_biandong(
    data: IdsIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="请先勾选记录")
    n = db.query(ShuifeixitongBiandong).filter(ShuifeixitongBiandong.id.in_(data.ids)).delete(synchronize_session=False)
    db.commit()
    return {"message": f"已删除 {n} 条变动记录"}


# ==================== 复制到下一年度 ====================

@router.get("/copy-count")
def copy_count(
    nd: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    """预估可复制条数:目标年度不存在 身份证+事项 的未取消记录。"""
    existing = set(
        (r[0], r[1])
        for r in db.query(Shuifeixitong.sfz, Shuifeixitong.shixiang)
        .filter(Shuifeixitong.nd == nd + 1)
        .all()
    )
    rows = (
        db.query(Shuifeixitong.sfz, Shuifeixitong.shixiang)
        .filter(Shuifeixitong.nd == nd, Shuifeixitong.quxiaoriqi.is_(None))
        .all()
    )
    cnt = sum(1 for sfz, sx in rows if (sfz, sx) not in existing)
    return {"source_nd": nd, "target_nd": nd + 1, "count": cnt}


@router.post("/copy-to-next-year")
def copy_to_next_year(
    nd: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    existing = set(
        (r[0], r[1])
        for r in db.query(Shuifeixitong.sfz, Shuifeixitong.shixiang)
        .filter(Shuifeixitong.nd == nd + 1)
        .all()
    )
    rows = (
        db.query(Shuifeixitong)
        .filter(Shuifeixitong.nd == nd, Shuifeixitong.quxiaoriqi.is_(None))
        .all()
    )
    n = 0
    for row in rows:
        if (row.sfz, row.shixiang) in existing:
            continue
        clone = Shuifeixitong(
            **{
                c.name: getattr(row, c.name)
                for c in Shuifeixitong.__table__.columns
                if c.name not in ("id", "quxiaoriqi", "caozuo", "caozuoriqi")
            }
        )
        clone.nd = nd + 1
        clone.quxiaoriqi = None
        clone.caozuo = current.username
        clone.caozuoriqi = datetime.now()
        db.add(clone)
        n += 1
    db.commit()
    return {"message": f"已复制 {n} 条到 {nd + 1} 年度"}


# ==================== Excel 导入 / 更新 / 导出 ====================

from fastapi import File, UploadFile
from fastapi.responses import StreamingResponse

from app.services.water_fee_excel import (
    EXPORT_COLUMNS,
    EXPORT_SIMPLIFIED_COLUMNS,
    LS_EXPORT_COLUMNS,
    build_excel,
    import_cancel_writeback,
    import_rows,
    import_update,
)


class ImportIn(BaseModel):
    nd: int
    selected_cols: List[str] = []
    is_quxiao: bool = False
    quxiaoriqi: Optional[datetime] = None
    cancel_writeback: bool = False


class ImportUpdateIn(BaseModel):
    nd: int
    selected_cols: List[str] = []


@router.post("/import")
async def import_excel(
    nd: int,
    file: UploadFile = File(...),
    selected_cols: str = "",
    is_quxiao: bool = False,
    quxiaoriqi: Optional[datetime] = None,
    cancel_writeback: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    """导入新增(照旧 UploadE);勾选取消时,可选回写模式匹配已有记录写取消日期。"""
    data = await file.read()
    cols = [c for c in selected_cols.split(",") if c]
    if cancel_writeback:
        if quxiaoriqi is None:
            raise HTTPException(status_code=400, detail="取消导入必须填写取消日期")
        result = import_cancel_writeback(db, current, data, nd, quxiaoriqi)
        return {"mode": "cancel_writeback", **result}
    result = import_rows(db, current, data, nd, cols, is_quxiao, quxiaoriqi)
    return {"mode": "import", **result}


@router.post("/import-update")
async def import_update_excel(
    nd: int,
    file: UploadFile = File(...),
    selected_cols: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:manage")),
):
    data = await file.read()
    cols = [c for c in selected_cols.split(",") if c]
    return import_update(db, current, data, nd, cols)


@router.get("/export")
def export_excel(
    nd: str = "",
    bmid: Optional[int] = None,
    mohu: str = "",
    qitayongshui: str = "",
    daoruqingkuang: str = "",
    show_quxiao: bool = True,
    dup_sfz: bool = False,
    yhh: str = "",
    fanmin: bool = False,
    simplified: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """导出 Excel(按当前筛选;全量列或简化列)。部门数据权限同列表。"""
    query = _filtered_query(
        db, nd, bmid, mohu, qitayongshui, daoruqingkuang, show_quxiao, dup_sfz, yhh, fanmin,
        scope_ids=_dept_scope_ids(db, current),
    )
    rows = query.all() if query is not None else []
    columns = EXPORT_SIMPLIFIED_COLUMNS if simplified else EXPORT_COLUMNS
    dept_names = _dept_name_map(db)
    value_maps = {"bm2": lambda r: dept_names.get(r.bmid, "")}
    return build_excel(rows, columns, "特殊群体用户信息" if simplified else "民政局数据", value_maps=value_maps)


@router.get("/biandong/export")
def export_biandong(
    nd: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("waterfee:view")),
):
    """变动历史导出(照旧 ExportLsExcel:需主表联查的 年度/营业所/姓名/证件号/电话/新居住地址)。"""
    from sqlalchemy.orm import aliased
    query = db.query(ShuifeixitongBiandong)
    main = aliased(Shuifeixitong)
    query = query.join(main, ShuifeixitongBiandong.zhuid == main.id)
    if nd.strip():
        years = [int(x) for x in nd.split(",") if x.strip().isdigit()]
        if years:
            query = query.filter(main.nd.in_(years))
    scope_ids = _dept_scope_ids(db, current)
    if scope_ids is not None:
        query = query.filter(main.bmid.in_(scope_ids))
    rows = query.order_by(ShuifeixitongBiandong.id.desc()).all()
    from types import SimpleNamespace
    from app.services.water_fee_excel import LS_EXPORT_COLUMNS
    dept_names = _dept_name_map(db)
    zhuids = {r.zhuid for r in rows if r.zhuid}
    mains = {}
    if zhuids:
        for m in db.query(Shuifeixitong).filter(Shuifeixitong.id.in_(zhuids)).all():
            mains[m.id] = m
    objs = []
    for r in rows:
        m = mains.get(r.zhuid)
        objs.append(SimpleNamespace(
            id=r.id, nd=m.nd if m else None,
            # 营业所列:优先关联部门名(照旧 u.shuifeixitong.bb_bumen.bm),退文件列 bm
            bm=(dept_names.get(m.bmid) if m and m.bmid else (m.bm if m else "")),
            caozuo=r.caozuo, biandongriqi=r.biandongriqi,
            xingming=m.xingming if m else "", sfz=m.sfz if m else "",
            juzhudizhi_bd=r.juzhudizhi, dianhua_main=m.dianhua if m else "",
            yonghuhao=r.yonghuhao, qitayongshui=r.qitayongshui, beizhu=r.beizhu,
            daoruqingkuang=r.daoruqingkuang, fanhuiminzhengju=r.fanhuiminzhengju,
            guitaishouli=r.guitaishouli, shoulishijian=r.shoulishijian,
            youhuiksriqi=r.youhuiksriqi, youhuijsriqi=r.youhuijsriqi,
            yueshu=r.yueshu, wushuifeihetui=r.wushuifeihetui,
            juzhudizhi_main=m.juzhudizhi if m else "",
        ))
    return build_excel(objs, LS_EXPORT_COLUMNS, "民政局变动历史数据")


@router.get("/export-report")
def export_report(
    nd: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("waterfee:view")),
):
    """匹配率报表(照旧 Export:部门×事项 矩阵,每事项 户数/已匹配/匹配率 + 合计)。"""
    from app.services.water_fee_excel import build_report_excel
    return build_report_excel(statistics(nd=nd, db=db, _user=_user), nd)


@router.post("/import-headers")
async def import_headers(
    file: UploadFile = File(...),
    _user: User = Depends(require_permission("waterfee:view")),
):
    """解析 Excel 表头:返回各 sheet 名与表头列(去重),供前端勾选导入哪些列。

    表头需在 COLUMN_MAP 里能映射到字段才可选;返回时标注是否认识。
    """
    from app.services.water_fee_excel import COLUMN_MAP, iter_bytes
    data = await file.read()
    sheets, all_headers, seen = [], [], set()
    for name, header in iter_bytes(data):
        headers = [h for h in header if h]
        sheets.append({"name": name, "headers": headers})
        for h in headers:
            if h not in seen:
                seen.add(h)
                all_headers.append({"header": h, "field": COLUMN_MAP.get(h)})
    return {"sheets": sheets, "columns": all_headers}
