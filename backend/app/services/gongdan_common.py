"""工单信息录入 Gongdan 公共逻辑(照旧 gongdancailiaoservice.LoadSearchEntities 1:1 复刻)。

筛选口径(与旧服务逐条对照):
- 部门:旧 `bb_bumen.cj.StartsWith(bumen.cj)` 层级前缀 → 新 `dept_scope_ids` 子树
- 日期:rq 为空 → 起始今年 1/1;rq 有值、rqend 为空 → 起始 rq 所在月 1 日;
        rq 与 rqend 都有 → 起始 rq、结束 rqend 次月零点(含结束当天)
        anbjriqi=on 按 djriqi 过滤,否则 ksriqi>=起 且 jsriqi<止(旧口径)
- cf=on   只留工单号重复(>1 条)的记录;fcf=on 每个工单号只留 djriqi 最新的一条
- mohu    地址/内容/备注/材质/主材/班组/工单号/管径 八字段 OR 模糊
- minP/maxp 按 pipesize(管径文本解析出的数字)范围
- 排序 ksriqi desc, id desc

与旧系统的唯一差异:旧服务把 `bmid` 精确过滤放在 Count/Skip/Take **之后**,
导致带部门筛选时 total 与当页行数不符;新系统统一在分页前过滤(与 workorder 模块的修正一致)。
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids
from app.models.gongdan import GongdanCaizhiDict, GongdanNeirongDict
from app.models.material import MaterialLibrary, MaterialRecord, WorkOrder
from app.models.user import User
from app.models.workorder import GongdanCailiao

DN_OPTIONS = [
    "DN15", "DN20", "DN25", "DN32", "DN40", "DN50", "DN63", "DN65", "DN75",
    "DN80", "DN90", "DN100", "DN110", "DN150", "DN200", "DN300", "DN400",
    "DN500", "DN600", "DN700", "DN800", "DN900", "DN1000", "其他",
]
TINGSHUI_OPTIONS = ["是", "否"]
MOHU_FIELDS = ("dizhi", "neirong", "beizhu", "caizhi", "cailiao",
               "qiangxiurenyuan", "gongdanhao", "guanjing")


class SearchParams:
    def __init__(self, *, rq: str = "", rqend: str = "", mohu: str = "",
                 minPipe: Optional[int] = None, maxPipe: Optional[int] = None,
                 anbjriqi: str = "", cf: str = "", fcf: str = "",
                 bmid: Optional[int] = None):
        self.rq = rq or ""
        self.rqend = rqend or ""
        self.mohu = (mohu or "").strip()
        self.minPipe = minPipe
        self.maxPipe = maxPipe
        self.anbjriqi = anbjriqi or ""
        self.cf = cf or ""
        self.fcf = fcf or ""
        self.bmid = bmid


def s(v) -> str:
    return "" if v is None else str(v)


def fmt_dt(v, with_seconds: bool = True) -> str:
    if not v:
        return ""
    fmt = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return v.strftime(fmt) if isinstance(v, datetime) else s(v)


def parse_dt(value) -> Optional[datetime]:
    """兼容 el-date-picker 的 yyyy-MM-dd HH:mm:ss / ISO / 纯日期 / 旧接口字符串。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    txt = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    if len(txt) >= 10:
        try:
            return datetime.strptime(txt[:10], "%Y-%m-%d")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        return None


def parse_pipe_size(text: Optional[str]) -> Optional[int]:
    """照旧 ParsePipeSize:含 # 视为非管径,否则取第一个数字串。"""
    if not text or not str(text).strip():
        return None
    upper = str(text).strip().upper()
    if "#" in upper:
        return None
    m = re.search(r"\d+", upper)
    return int(m.group()) if m else None


def scoped(db: Session, user: User, requested_bmid: Optional[int] = None) -> Optional[set]:
    """可见部门 id 集合(子树);None=不限定。指定 bmid 时收窄到该部门。"""
    scope = dept_scope_ids(db, user)
    if requested_bmid and requested_bmid > 0:
        if scope is not None:
            return {requested_bmid} if requested_bmid in scope else {-1}
        return {requested_bmid}
    return scope


def date_bounds(p: SearchParams) -> tuple[datetime, datetime]:
    """旧 LoadSearchEntities 的 ksd/jsd。"""
    now = datetime.now()
    if p.rq:
        start = parse_dt(p.rq) or now
        ksd = datetime(start.year, start.month, 1)
    else:
        ksd = datetime(now.year, 1, 1)
    jsd = now + timedelta(days=1)
    if p.rq and p.rqend:
        ksd = parse_dt(p.rq) or ksd
        end = parse_dt(p.rqend)
        if end:
            jsd = datetime(end.year, end.month, end.day) + timedelta(days=1)
    return ksd, jsd


def _date_filter(q, p: SearchParams):
    ksd, jsd = date_bounds(p)
    if p.anbjriqi == "on":
        return q.filter(GongdanCailiao.djriqi >= ksd, GongdanCailiao.djriqi < jsd)
    return q.filter(GongdanCailiao.ksriqi >= ksd, GongdanCailiao.jsriqi < jsd)


def _group_filter_ids(q, cf: bool, fcf: bool) -> Optional[list]:
    """cf/fcf 都在「已按日期+部门过滤」的集合上分组(照旧:先分组再 mohu/管径)。"""
    if not cf and not fcf:
        return None
    rows = list(q.with_entities(
        GongdanCailiao.id, GongdanCailiao.gongdanhao, GongdanCailiao.djriqi
    ).all())
    if cf:
        counts = {}
        for _id, no, _djr in rows:
            counts[no] = counts.get(no, 0) + 1
        repeated = {no for no, n in counts.items() if n > 1}
        rows = [r for r in rows if r[1] in repeated]
    if fcf:
        # fcf:每个工单号只保留 djriqi 最新的一条(并列取 id 最大,稳定排序)
        latest = {}
        for _id, no, djr in rows:
            key = (djr or datetime.min, _id)
            if no not in latest or key > latest[no][0]:
                latest[no] = (key, _id)
        return [v[1] for v in latest.values()]
    return [r[0] for r in rows]


def build_query(db: Session, user: User, p: SearchParams):
    q = db.query(GongdanCailiao)
    scope = scoped(db, user, p.bmid)
    if scope is not None:
        q = q.filter(GongdanCailiao.bmid.in_(scope))
    q = _date_filter(q, p)
    ids = _group_filter_ids(q, p.cf == "on", p.fcf == "on")
    if ids is not None:
        q = q.filter(GongdanCailiao.id.in_(ids or [-1]))
    if p.mohu:
        like = f"%{p.mohu}%"
        q = q.filter(or_(*(getattr(GongdanCailiao, f).like(like) for f in MOHU_FIELDS)))
    if p.minPipe is not None:
        q = q.filter(GongdanCailiao.pipesize >= p.minPipe)
    if p.maxPipe is not None:
        q = q.filter(GongdanCailiao.pipesize <= p.maxPipe)
    return q


def row_dict(item: GongdanCailiao) -> dict:
    """旧 GetList 的匿名对象字段(注意 ID 大写、pipesize 用于行标色)。"""
    return {
        "ID": item.id,
        "ksriqi": fmt_dt(item.ksriqi),
        "jsriqi": fmt_dt(item.jsriqi),
        "shijian": item.shijian,
        "dizhi": s(item.dizhi),
        "neirong": s(item.neirong),
        "caizhi": s(item.caizhi),
        "guanjing": s(item.guanjing),
        "gongdanhao": s(item.gongdanhao),
        "tingshui": s(item.tingshui),
        "shuliang": s(item.shuliang),
        "shuiliang": item.shuiliang,
        "cailiao": s(item.cailiao),
        "qiangxiurenyuan": s(item.qiangxiurenyuan),
        "djren": s(item.djren),
        "djriqi": fmt_dt(item.djriqi),
        "zuihouriqi": fmt_dt(item.zuihouriqi),
        "beizhu": s(item.beizhu),
        "pipesize": item.pipesize,
    }


# ==================== 字典 ====================

def dict_options(db: Session, model, column, q: str = "", blank_first: bool = False) -> list:
    query = db.query(model)
    key = (q or "").strip()
    if key:
        query = query.filter(column.like(f"%{key}%"))
    rows = query.order_by(model.use_count.desc(), model.last_used_time.desc(),
                          model.id.desc()).all()
    name = "caizhi" if model is GongdanCaizhiDict else "neirong"
    out = [{"Value": "", "Text": ""}] if blank_first else []
    out.extend([{"Value": getattr(r, name), "Text": getattr(r, name),
                 "useCount": r.use_count or 0} for r in rows])
    return out


def upsert_dict(db: Session, model, column, value: str):
    """照旧 UpsertNeirongDict / UpsertCaizhiDict:命中则 use_count+1,否则插入。"""
    text = (value or "").strip()
    if not text:
        return
    row = db.query(model).filter(column == text).first()
    if row:
        row.use_count = (row.use_count or 0) + 1
        row.last_used_time = datetime.now()
    else:
        field = "caizhi" if model is GongdanCaizhiDict else "neirong"
        db.add(model(**{field: text, "use_count": 1,
                        "last_used_time": datetime.now()}))
    db.flush()


# ==================== 领料明细 / 主材文本 ====================

def detail_join(db: Session, no: str):
    return (
        db.query(MaterialRecord, MaterialLibrary, WorkOrder)
        .join(MaterialLibrary, MaterialLibrary.id == MaterialRecord.material_id)
        .join(WorkOrder, WorkOrder.id == MaterialRecord.work_order_id)
        .filter(WorkOrder.work_order_no == no)
        .order_by(MaterialRecord.id)
    )


def order_detail_rows(db: Session, no: str) -> list:
    """旧 Gongdan/GetOrderDetails 7 列(JS columns 定义为准,忽略 HTML thead 残留 3 列)。"""
    out = []
    for rec, mat, _wo in detail_join(db, no).all():
        qty = float(rec.quantity or 0)
        out.append({
            "MaterialName": s(mat.material_name),
            "Model": s(mat.model),
            "Spec": s(mat.spec),
            "dakoujing": mat.dakoujing,
            "Quantity": round(qty, 1),
            "Unit": s(mat.unit),
            "CreatedTime": fmt_dt(rec.create_time, with_seconds=False),
        })
    return out


def material_text(db: Session, no: str) -> str:
    """旧 GetGongdanInfo 的 wst:型号+名称+规格(数量单位); 拼接。"""
    parts = []
    for rec, mat, _wo in detail_join(db, no).all():
        qty = float(rec.quantity or 0)
        parts.append(f"{s(mat.model)}{s(mat.material_name)}{s(mat.spec)}"
                     f"({qty:.1f}{s(mat.unit)});")
    return "".join(parts)
