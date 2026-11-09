"""年度计划模块公共口径(照旧 gxdxljihua/jhssdb/jhsshz/jhyyfaqi 复刻)。

四个页面共用 jh_ssdb(实施单/汇总) 与 gx_gxgz(正式计划) 数据,这里集中:
- 字典(计划类别/小类别/状态)、计划年度算法(6 月后算次年)
- 部门/专管员下拉、部门名称映射
- 字段变更日志(shuifeixitong_log,source=jhssdb)
- 提交时「更新改造」默认值补全
- 进度统计(最新状态 vs 历史最大进度、总付、关注人)
- 开关 consol_tb
"""

from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.plan import (
    ConsolTb, GxGxgz, GxJilu, GxJindu, GxUserGxgz,
    JhSsdb, JhSsdbPz, JhYyfq,
)
from app.models.sms import SmsContact
from app.models.user import Department, User
from app.models.water_fee import ShuifeixitongLog

JHLB_OPTIONS = ["更新改造", "大修理", "管道工程", "长期待摊", "中期更新", "中期大修"]
MIDDLE_CATEGORIES = ("中期更新", "中期大修")
LEIBIE_OPTIONS = ["生产类", "安全类", "福利类", "研发类", "其他"]

STATUS_TODO = "专管员落实"
STATUS_SUBMITTED = "售水待汇总"
STATUS_RETURNED = "已回退"
STATUS_APPROVED = "售水通过"
STATUS_DELETED = "删除"

YY_SUBMITTED = "提交审核"
YY_SWSH = "售水专管审批"
YY_RETURNED = "售水退回"

LOCK_APPLY = "锁定营业所计划"
LOCK_SUMMARY = "jhsshz浏览锁定"

DEPT_SW_BENBU = "售水本部"

STATUS_LABELS = {
    STATUS_TODO: "待处理计划",
    STATUS_SUBMITTED: "已提交计划",
    STATUS_RETURNED: "已回退营业所",
    STATUS_APPROVED: "已通过计划",
    STATUS_DELETED: "已删除",
    YY_SUBMITTED: "提交审核",
    YY_SWSH: "已报售水",
    YY_RETURNED: "售水退回",
}

JHSS_FIELDS = [
    "序号", "小类别", "计划类别", "项目名称", "项目说明", "金额", "年初金额", "本年计划投资",
    "开工年月", "竣工年月", "新建/续建", "专管员", "所属部门", "主办部门", "负责人", "批注", "状态", "年度",
]

COMPLETED_STATUS = {"完成计划", "付完质保金", "尚余质保金"}
COMPLETED_PREFIX = "完成所有手续"


def plan_year(now: Optional[datetime] = None) -> int:
    """旧 bbrq.getYear():6 月以后算下一年度计划。"""
    now = now or datetime.now()
    return now.year + 1 if now.month > 5 else now.year


def split_csv(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _fmt_money(v):
    return float(v) if v is not None else 0.0


def dept_options(db: Session, user: User, *, host_only: bool = False) -> list[dict]:
    """部门下拉:默认本人部门子树;host_only=True 取主办部门(dnnum>0)。"""
    q = db.query(Department)
    # 主办部门是跨所选择的公共字典,不做部门范围过滤(照旧 dnnum>0 全量)
    scope = dept_scope_ids(db, user)
    if host_only:
        q = q.filter(Department.dnnum > 0)
    else:
        if scope is not None:
            q = q.filter(Department.id.in_(scope))
        q = q.filter(or_(Department.dnnum == 0, Department.dnnum.is_(None)))
    return [{"id": d.id, "name": d.name} for d in q.order_by(Department.id).all()]


def dept_ids(db: Session, user: User) -> list[int]:
    return [d.id for d in user.departments]


def primary_dept_id(db: Session, user: User) -> Optional[int]:
    ids = dept_ids(db, user)
    return ids[0] if ids else None


def zgy_options(db: Session, *, only_zgy: bool = False) -> list[str]:
    """专管员候选。

    默认:新系统启用用户 + 历史计划里出现过的旧用户名快照。
    only_zgy=True(营业所发起,照旧 bb_user.zw == "专管员"):只取职务为
    「专管员」的新用户,以及旧 bb_user 联系人目录里职务为「专管员」的人。
    """
    if only_zgy:
        names = {
            (u.username or "").strip()
            for u in db.query(User).filter(User.is_active == True).all()  # noqa: E712
            if (u.zw or "").strip() == "专管员"
        }
        for c in db.query(SmsContact).all():
            if (c.zw or "").strip() == "专管员":
                name = (c.username or c.real_name or "").strip()
                if name:
                    names.add(name)
        return sorted(n for n in names if n)

    names = {u.username for u in db.query(User.username).filter(User.is_active == True).all()}  # noqa: E712
    for (v,) in db.query(JhSsdb.zhuanguan_name).filter(JhSsdb.zhuanguan_name != "").distinct():
        names.add(v)
    for (v,) in db.query(JhYyfq.zgy_name).filter(JhYyfq.zgy_name != "").distinct():
        names.add(v)
    for (v,) in db.query(GxGxgz.zgy).filter(GxGxgz.zgy != "").distinct():
        names.add(v)
    return sorted(n for n in names if n)


def resolve_user_id(db: Session, name: str) -> Optional[int]:
    if not name:
        return None
    row = db.query(User.id).filter(User.username == name).first()
    return row[0] if row else None


def get_lock(db: Session, name: str) -> bool:
    row = db.query(ConsolTb).filter(ConsolTb.conName == name).first()
    return bool(row and row.val)


def set_lock(db: Session, name: str, value: bool) -> None:
    row = db.query(ConsolTb).filter(ConsolTb.conName == name).first()
    if row is None:
        db.add(ConsolTb(conName=name, val=value))
    else:
        row.val = value


def add_log(db: Session, main_id: int, field: str, old, new, username: str, source: str = "jhssdb"):
    o = "" if old is None else str(old)
    n = "" if new is None else str(new)
    if o == n:
        return
    db.add(ShuifeixitongLog(
        main_id=main_id, field_name=field, old_value=o, new_value=n,
        update_user=username or "", update_time=datetime.now(), source=source,
    ))


def log_rows(db: Session, main_id: int) -> list[dict]:
    rows = (
        db.query(ShuifeixitongLog)
        .filter(ShuifeixitongLog.main_id == main_id, ShuifeixitongLog.source == "jhssdb")
        .order_by(ShuifeixitongLog.update_time.desc(), ShuifeixitongLog.id.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


def one_log_rows(db: Session, main_id: int) -> list[dict]:
    return log_rows(db, main_id)


def fill_gxgz_defaults(row, username: str = "") -> list[tuple[str, str, str]]:
    """提交/通过时「更新改造」补默认值,返回补全明细供写日志。"""
    changes: list[tuple[str, str, str]] = []
    if (row.jhlb or "") != "更新改造":
        return changes
    if row.zongtouzi is None and row.jine is not None:
        changes.append(("本年计划投资", "", str(row.jine)))
        row.zongtouzi = row.jine
    year = row.niandu or plan_year()
    if not row.kgny:
        row.kgny = f"{year}-06"
        changes.append(("开工年月", "", row.kgny))
    if not row.jgny:
        row.jgny = f"{year}-12"
        changes.append(("竣工年月", "", row.jgny))
    if not row.xjxl:
        row.xjxl = "续建" if "未完成" in (row.bz or "") else "新建"
        changes.append(("新建/续建", "", row.xjxl))
    return changes


def snapshot_ssdb(db: Session, row: JhSsdb) -> None:
    """每次售水待办变更前快照进 jh_ssdbpz(旧库由触发器写入,这里显式补)。"""
    db.add(JhSsdbPz(
        id=row.id, xuhao=row.xuhao, daibanname=row.daibanname, bz=row.bz,
        jine=row.jine, zb=row.zb, fzr=row.fzr, niandu=row.niandu,
        jhlb=row.jhlb, zt=row.zt, zhuanguan=row.zhuanguan,
        zhuanguan_name=row.zhuanguan_name, opname=row.opname, bumenid=row.bumenid,
        faqiid=row.faqiid, dbtimep=row.dbtimep, kstimep=row.kstimep,
        pizhu=row.pizhu, lastop=row.lastop, nxuhao=row.nxuhao,
        yincang=row.yincang, leibie=row.leibie, startjine=row.startjine,
        zongtouzi=row.zongtouzi, kgny=row.kgny, jgny=row.jgny, xjxl=row.xjxl,
    ))


def log_ssdb_diff(db: Session, row: JhSsdb, old: dict, username: str) -> None:
    names = dept_name_map(db)
    now = {
        "序号": row.xuhao, "小类别": row.leibie, "计划类别": row.jhlb,
        "项目名称": row.daibanname, "项目说明": row.bz, "金额": row.jine,
        "年初金额": row.startjine, "本年计划投资": row.zongtouzi, "开工年月": row.kgny,
        "竣工年月": row.jgny, "新建/续建": row.xjxl, "专管员": row.zhuanguan_name,
        "所属部门": row.bumenid, "主办部门": row.zb, "负责人": row.fzr,
        "批注": row.pizhu, "状态": row.zt, "年度": row.niandu,
    }

    def conv(field, val):
        if field in ("所属部门", "主办部门"):
            return names.get(val, "") if isinstance(val, int) else (val or "")
        return val

    for field, val in old.items():
        add_log(db, row.id, field, conv(field, val), conv(field, now.get(field)), username)


def parse_xuhao(value: Optional[str]) -> Optional[int]:
    """3.33 -> 33;纯数字取全值;其他放空。"""
    if not value:
        return None
    s = str(value).strip()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    return int(s) if s.isdigit() else None


def dept_name_of(names: dict, did) -> str:
    return names.get(did, "") if did is not None else ""


def completed_expr(db: Session):
    """已完成:存在进度类型为「完成所有手续100」或 value=100 的记录。"""
    return (
        db.query(GxJilu.id)
        .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
        .join(GxJindu, GxJilu.zhuangtaiid == GxJindu.id)
        .filter(
            GxUserGxgz.gxgzid == GxGxgz.id,
            or_(GxJindu.value == 100, GxJindu.leixing.like(f"{COMPLETED_PREFIX}%")),
        )
        .exists()
    )


def official_query(
    db: Session, user: User, *, nd=None, lb="", mohu="", zgy_list=None,
    bmid=None, zb="", px=True, unfinished=False, finished=False,
    unfollowed=False, zbj_only=False, khbj_only=False, gxgzid=None,
):
    q = db.query(GxGxgz)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(GxGxgz.bmid.in_(scope))
    if gxgzid:
        q = q.filter(GxGxgz.id == gxgzid)
    if nd:
        q = q.filter(GxGxgz.nd == int(nd))
    if lb:
        q = q.filter(GxGxgz.lb == lb)
    if bmid:
        q = q.filter(GxGxgz.bmid == int(bmid))
    if zb:
        q = q.filter(GxGxgz.zb == zb)
    zgy_arr = split_csv(zgy_list)
    if zgy_arr:
        q = q.filter(GxGxgz.zgy.in_(zgy_arr))
    kw = (mohu or "").strip()
    if kw:
        like = f"%{kw}%"
        cond = or_(
            GxGxgz.bz.like(like), GxGxgz.name.like(like), GxGxgz.fzr.like(like),
            GxGxgz.xh.like(like), GxGxgz.ssusers.like(like), GxGxgz.zgy.like(like),
        )
        try:
            cond = or_(cond, GxGxgz.jine == float(kw))
        except ValueError:
            pass
        q = q.filter(cond)
    if unfinished:
        q = q.filter(~completed_expr(db))
    if finished:
        q = q.filter(completed_expr(db))
    if unfollowed:
        q = q.filter(~db.query(GxUserGxgz.id).filter(GxUserGxgz.gxgzid == GxGxgz.id).exists())
    if zbj_only:
        q = q.filter(GxGxgz.zbj.isnot(None))
    if khbj_only:
        q = q.filter(GxGxgz.khbj == True)  # noqa: E712
    if px:
        if lb in MIDDLE_CATEGORIES:
            q = q.order_by(GxGxgz.nxuhao.is_(None), GxGxgz.nxuhao, GxGxgz.id)
        else:
            q = q.order_by(GxGxgz.bmid.is_(None), GxGxgz.bmid, GxGxgz.nxuhao.is_(None), GxGxgz.nxuhao, GxGxgz.id)
    else:
        q = q.order_by(GxGxgz.id)
    return q


def progress_maps(db: Session, plan_ids: Iterable[int]):
    """返回 (按计划汇总, 最新记录, 最大进度, 我的关注id由调用方另算)。"""
    ids = [int(x) for x in plan_ids]
    if not ids:
        return {}, {}, {}, {}
    jindu = {j.id: j for j in db.query(GxJindu).all()}
    follows = db.query(GxUserGxgz).filter(GxUserGxgz.gxgzid.in_(ids)).all()
    fmap = {f.id: f for f in follows}
    jilus = (
        db.query(GxJilu)
        .filter(GxJilu.guanzhuid.in_(list(fmap.keys())))
        .order_by(GxJilu.id)
        .all()
        if fmap else []
    )
    agg = {pid: {"numb": 0, "zongji": 0.0, "users": set(), "follows": []} for pid in ids}
    latest = {}
    maxjd = {}
    dates = {pid: {"latest_riqi": "", "kaigong_date": "", "hetong_date": ""} for pid in ids}
    for f in follows:
        a = agg.setdefault(f.gxgzid, {"numb": 0, "zongji": 0.0, "users": set(), "follows": []})
        a["follows"].append(f)
        if f.username:
            a["users"].add(f.username)
    for j in jilus:
        f = fmap.get(j.guanzhuid)
        if not f:
            continue
        a = agg.setdefault(f.gxgzid, {"numb": 0, "zongji": 0.0, "users": set(), "follows": []})
        a["numb"] += 1
        a["zongji"] += float(j.fukuan or 0)
        jd = jindu.get(j.zhuangtaiid)
        cur = {
            "leixing": jd.leixing if jd else "",
            "value": jd.value if jd else None,
            "miaoshu": j.miaoshu or "",
        }
        latest[f.gxgzid] = cur
        d = dates.setdefault(f.gxgzid, {"latest_riqi": "", "kaigong_date": "", "hetong_date": ""})
        d["latest_riqi"] = j.riqi.strftime("%Y-%m-%d") if j.riqi else ""
        if jd is not None:
            if jd.value == 10 and not d["kaigong_date"] and j.riqi:
                d["kaigong_date"] = j.riqi.strftime("%Y-%m-%d")
            if jd.value == 30 and not d["hetong_date"] and j.riqi:
                d["hetong_date"] = j.riqi.strftime("%Y-%m-%d")
        val = jd.value if jd and jd.value is not None and 10 <= jd.value <= 100 else -1
        prev = maxjd.get(f.gxgzid)
        if prev is None or val >= (prev[0] if prev[0] is not None else -1):
            maxjd[f.gxgzid] = (val, jd.leixing if jd else "")
    return agg, latest, maxjd, dates


def official_rows(db: Session, plans: list[GxGxgz], user: User) -> list[dict]:
    names = dept_name_map(db)
    agg, latest, maxjd, dates = progress_maps(db, [p.id for p in plans])
    my_follow = {
        f.gxgzid: f.id
        for f in db.query(GxUserGxgz).filter(
            GxUserGxgz.userid == user.id,
            GxUserGxgz.gxgzid.in_([p.id for p in plans] or [0]),
        ).all()
    }
    rows = []
    for p in plans:
        a = agg.get(p.id, {"numb": 0, "zongji": 0.0, "users": set(), "follows": []})
        lt = latest.get(p.id) or {}
        mx = maxjd.get(p.id) or (None, "")
        max_lx = mx[1] or ""
        completed = max_lx in COMPLETED_STATUS or max_lx.startswith(COMPLETED_PREFIX)
        rows.append({
            "ID": p.id,
            "numb": a["numb"],
            "ssusers": "|".join(sorted(a["users"])),
            "myGuanzhuid": my_follow.get(p.id, 0),
            "jdzt": lt.get("leixing", ""),
            "jdztDesc": lt.get("miaoshu", ""),
            "jdztValue": mx[0] if mx[0] not in (-1, None) else None,
            "jdztMaxLx": max_lx,
            "completed": completed,
            "nd": p.nd,
            "name": p.name or "",
            "xh": p.xh or "",
            "bz": p.bz or "",
            "jine": (p.jine or 0) / 10000,
            "zb": p.zb or "",
            "bm": p.bm or names.get(p.bmid, ""),
            "bmid": p.bmid,
            "fzr": p.fzr or "",
            "lb": p.lb or "",
            "xmbz": p.xmbz or "",
            "zgy": p.zgy or "",
            "zongji": round(a["zongji"] / 10000, 4),
            "zbj": float(p.zbj) if p.zbj is not None else None,
            "zbjrq": p.zbjrq.strftime("%Y-%m-%d") if p.zbjrq else "",
            "zbjdjr": p.zbjdjr or "",
            "zbjdjriqi": p.zbjdjriqi.strftime("%Y-%m-%d %H:%M:%S") if p.zbjdjriqi else "",
            "khbj": bool(p.khbj),
            "latest_riqi": (dates.get(p.id) or {}).get("latest_riqi", ""),
            "kaigong_date": (dates.get(p.id) or {}).get("kaigong_date", ""),
            "hetong_date": (dates.get(p.id) or {}).get("hetong_date", ""),
        })
    return rows


def official_totals(db: Session, q) -> dict:
    """筛选结果全量统计:总金额、总付、考核金额/完成量/完成率。"""
    plans = q.all()
    total_jine = sum((p.jine or 0) for p in plans) / 10000
    ids = [p.id for p in plans]
    zongji = 0.0
    latest_val = {}
    if ids:
        zongji = (
            db.query(func.coalesce(func.sum(GxJilu.fukuan), 0))
            .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
            .filter(GxUserGxgz.gxgzid.in_(ids))
            .scalar()
            or 0
        )
        jindus = {j.id: j.value for j in db.query(GxJindu).all()}
        for jid, pid, ztid in (
            db.query(GxJilu.id, GxUserGxgz.gxgzid, GxJilu.zhuangtaiid)
            .join(GxUserGxgz, GxJilu.guanzhuid == GxUserGxgz.id)
            .filter(GxUserGxgz.gxgzid.in_(ids))
            .order_by(GxJilu.id)
            .all()
        ):
            latest_val[pid] = jindus.get(ztid)
    kh_total = 0.0
    kh_done = 0.0
    for p in plans:
        if not p.khbj:
            continue
        wan = (p.jine or 0) / 10000
        kh_total += wan
        val = latest_val.get(p.id)
        if val is not None and 10 <= val <= 100:
            kh_done += wan * val / 100
    pct = round(kh_done / kh_total * 100, 1) if kh_total > 0 else 0
    return {
        "allTotalJine": round(total_jine, 2),
        "footerJine": round(total_jine, 2),
        "footerZongji": round(float(zongji) / 10000, 2),
        "khTotalJine": round(kh_total, 2),
        "khCompletedJine": round(kh_done, 2),
        "khCompletePct": pct,
    }


def ssdb_base_query(db: Session, *, nd=None, jhlb="", zb=None, bumenid=None,
                    mohu="", zt="", zgy="", all_zgy=False, username="",
                    scope=None, exclude_deleted=True):
    q = db.query(JhSsdb)
    if exclude_deleted:
        q = q.filter(JhSsdb.zt != STATUS_DELETED)
    if nd:
        q = q.filter(JhSsdb.niandu == int(nd))
    if jhlb:
        q = q.filter(JhSsdb.jhlb == jhlb)
    if bumenid:
        q = q.filter(JhSsdb.bumenid == int(bumenid))
    elif scope is not None:
        q = q.filter(JhSsdb.bumenid.in_(scope))
    if zb:
        q = q.filter(JhSsdb.zb == int(zb))
    if zgy:
        q = q.filter(JhSsdb.zhuanguan_name == zgy)
    elif not all_zgy and username:
        q = q.filter(JhSsdb.zhuanguan_name == username)
    if zt:
        q = q.filter(JhSsdb.zt == zt)
    kw = (mohu or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            JhSsdb.bz.like(like), JhSsdb.daibanname.like(like),
            JhSsdb.pizhu.like(like), JhSsdb.leibie.like(like),
        ))
    return q


def ssdb_totals(q) -> dict:
    total_jine = 0.0
    total_start = 0.0
    total_zongtouzi = 0.0
    for p in q.all():
        total_jine += float(p.jine or 0)
        total_start += float(p.startjine or 0)
        total_zongtouzi += float(p.zongtouzi or 0)
    return {
        "tongjijine": round(total_jine, 4),
        "tongjinianchu": round(total_start, 4),
        "tongjizongtouzi": round(total_zongtouzi, 4),
        "tongjitzy": round(total_jine - total_start, 4),
    }


def sort_ssdb_plans(db: Session, plans: list[JhSsdb]) -> list[JhSsdb]:
    """计划文档顺序:部门排序号 -> 部门 -> 计划类别 -> 数字序号 -> 最后操作时间。"""
    depts = {d.id: d for d in db.query(Department).all()}
    return sorted(plans, key=lambda p: (
        (depts[p.bumenid].xuhaotou if p.bumenid in depts and depts[p.bumenid].xuhaotou is not None else 10**6),
        p.bumenid or 0,
        p.jhlb or "",
        p.nxuhao if p.nxuhao is not None else 10**9,
        p.dbtimep or datetime.min,
    ))


def ssdb_rows(db: Session, plans: list[JhSsdb]) -> list[dict]:
    names = dept_name_map(db)
    rows = []
    for p in plans:
        rows.append({
            "ID": p.id,
            "id": p.id,
            "xuhao": p.xuhao or "",
            "daibanname": p.daibanname or "",
            "bz": p.bz or "",
            "jine": p.jine,
            "zongtouzi": p.zongtouzi,
            "startjine": p.startjine,
            "zb": names.get(p.zb, ""),
            "zb_id": p.zb,
            "fzr": p.fzr or "",
            "jhlb": p.jhlb or "",
            "zt": p.zt or "",
            "opname": p.opname or "",
            "username": p.zhuanguan_name or "",
            "zhuanguan": p.zhuanguan,
            "ssbm": names.get(p.bumenid, ""),
            "bumenid": p.bumenid,
            "faqiid": p.faqiid,
            "kstimep": p.kstimep.strftime("%Y-%m-%d %H:%M:%S") if p.kstimep else "",
            "dbtimep": p.dbtimep.strftime("%Y-%m-%d %H:%M:%S") if p.dbtimep else "",
            "pizhu": p.pizhu or "",
            "lastop": p.lastop or "",
            "leibie": p.leibie or "",
            "kgny": p.kgny or "",
            "jgny": p.jgny or "",
            "xjxl": p.xjxl or "",
            "nxuhao": p.nxuhao,
            "niandu": p.niandu,
            "canHt": p.faqiid is not None,
        })
    return rows


def latest_ssdb_by_faqiid(db: Session, faqiids: list[int]) -> dict[int, JhSsdb]:
    if not faqiids:
        return {}
    rows = (
        db.query(JhSsdb)
        .filter(JhSsdb.faqiid.in_(faqiids))
        .order_by(JhSsdb.dbtimep.asc(), JhSsdb.id.asc())
        .all()
    )
    result = {}
    for r in rows:
        result[r.faqiid] = r
    return result


def yyfq_query(db: Session, *, nd=None, jhlb="", bumenid=None, scope=None,
               mohu="", reported=False, summary=False):
    q = db.query(JhYyfq)
    if nd:
        q = q.filter(JhYyfq.niandu == int(nd))
    if jhlb:
        q = q.filter(JhYyfq.jhlb == jhlb)
    if bumenid:
        q = q.filter(JhYyfq.bmid == int(bumenid))
    elif not summary and scope is not None:
        q = q.filter(JhYyfq.bmid.in_(scope))
    if reported:
        q = q.filter(JhYyfq.zt == YY_SWSH)
    else:
        q = q.filter(JhYyfq.zt != YY_SWSH)
    kw = (mohu or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(JhYyfq.bz.like(like), JhYyfq.faqiname.like(like)))
    return q


def yyfq_totals(q) -> dict:
    total = 0.0
    start = 0.0
    for p in q.all():
        total += float(p.jine or 0)
        start += float(p.startjine or 0)
    return {
        "tongjijine": round(total, 4),
        "tongjinianchu": round(start, 4),
        "tongjitzy": round(total - start, 4),
    }


def yyfq_rows(db: Session, plans: list[JhYyfq]) -> list[dict]:
    names = dept_name_map(db)
    latest = latest_ssdb_by_faqiid(db, [p.id for p in plans])
    rows = []
    for p in plans:
        ss = latest.get(p.id)
        rows.append({
            "ID": p.id,
            "id": p.id,
            "faqiname": p.faqiname or "",
            "bz": p.bz or "",
            "jine": p.jine,
            "niandu": p.niandu,
            "zgy": p.zgy_name or "",
            "op": p.opname or "",
            "zt": p.zt or "",
            "fqtimep": p.fqtimep.strftime("%Y-%m-%d %H:%M:%S") if p.fqtimep else "",
            "jhlb": p.jhlb or "",
            "bm": names.get(p.bmid, ""),
            "bmid": p.bmid,
            "lastop": p.lastop or "",
            "beginTime": p.beginTime.strftime("%Y-%m-%d %H:%M:%S") if p.beginTime else "",
            "startjine": p.startjine,
            "zongtouzi": p.zongtouzi,
            "kgny": p.kgny or "",
            "jgny": p.jgny or "",
            "xjxl": p.xjxl or "",
            "pizhu": ss.pizhu if ss and ss.pizhu else "",
            "szzt": ss.zt if ss else "",
        })
    return rows


def reported_rows(db: Session, *, nd, jhlb, bumenid=None, scope=None,
                  summary=False, mohu="") -> list[dict]:
    q = db.query(JhSsdb).filter(
        JhSsdb.zt.notin_([STATUS_DELETED, STATUS_RETURNED]),
        JhSsdb.niandu == int(nd),
        JhSsdb.jhlb == jhlb,
    )
    if bumenid:
        q = q.filter(JhSsdb.bumenid == int(bumenid))
    elif not summary and scope is not None:
        q = q.filter(JhSsdb.bumenid.in_(scope))
    if mohu:
        like = f"%{mohu}%"
        q = q.filter(or_(JhSsdb.daibanname.like(like), JhSsdb.bz.like(like)))
    rows = q.order_by(JhSsdb.dbtimep.desc()).all()
    linked = {}
    unlinked = []
    for r in rows:
        if r.faqiid is None:
            unlinked.append(r)
        else:
            old = linked.get(r.faqiid)
            if old is None or (r.dbtimep or datetime.min) >= (old.dbtimep or datetime.min):
                linked[r.faqiid] = r
    merged = list(linked.values()) + unlinked
    # 先按最后操作时间倒序,再按排序号升序(稳定排序,避免 datetime.min.timestamp() 在 Windows 抛错)
    merged.sort(key=lambda x: x.dbtimep or datetime.min, reverse=True)
    merged.sort(key=lambda x: x.nxuhao if x.nxuhao is not None else 10**9)
    names = dept_name_map(db)
    result = []
    for s in merged:
        result.append({
            "ID": s.faqiid if s.faqiid else s.id,
            "id": s.id,
            "unlinked": s.faqiid is None,
            "xuhao": s.xuhao or "",
            "faqiname": s.daibanname or "",
            "bz": s.bz or "",
            "jine": s.jine,
            "niandu": s.niandu,
            "zgy": s.zhuanguan_name or "",
            "op": s.opname or "",
            "zt": s.zt or "",
            "fqtimep": s.dbtimep.strftime("%Y-%m-%d %H:%M:%S") if s.dbtimep else "",
            "jhlb": s.jhlb or "",
            "bm": names.get(s.bumenid, ""),
            "zb": names.get(s.zb, ""),
            "fzr": s.fzr or "",
            "lastop": s.lastop or "",
            "beginTime": s.kstimep.strftime("%Y-%m-%d %H:%M:%S") if s.kstimep else "",
            "startjine": s.startjine,
            "zongtouzi": s.zongtouzi,
            "kgny": s.kgny or "",
            "jgny": s.jgny or "",
            "xjxl": s.xjxl or "",
            "pizhu": s.pizhu or "",
        })
    return result


def is_summary_user(user: User) -> bool:
    if user.is_superuser:
        return True
    return bool({p.code for r in user.roles for p in r.permissions} & {"jhyyfaqi:summary"})


def is_readonly_summary(user: User) -> bool:
    """计划汇总权限只读;超级管理员不受限(可写、可看全部)。"""
    if user.is_superuser:
        return False
    return is_summary_user(user)


def has_perm(user: User, code: str) -> bool:
    if user.is_superuser:
        return True
    return code in {p.code for r in user.roles for p in r.permissions}
