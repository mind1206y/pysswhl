"""财务管理三模块公共逻辑:数据范围、行组装、查询构造、图片代理。

旧系统用 bb_bumen.cj 层级码做数据隔离(本部门 + 全部下级),新系统用
departments.parent_id 子树(dept_scope_ids)。旧代码还硬编码了集美所特权:
cj='000103'(集美,新 id 10)的用户额外可见 cj='000109'(杏林,新 id 16)的数据,
这里在 finance_scope_ids 里保留该特例。
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, dept_scope_ids
from app.core.config import settings
from app.core.security import create_short_token, decode_short_token
from app.models.finance import Wzcgsq, WzcgsqMx, ZcBaofeidan, ZcBaofeitp, ZcCw, ZcLb
from app.models.user import Department, User

# 1×1 透明 PNG:旧 /Upload 图片多数已缺失,照其它模块的做法返回占位图而不是 404
TRANSPARENT_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082"
)
JIMEI_DEPT_ID = 10   # 旧 cj 000103 集美营业所
XINGLIN_DEPT_ID = 16  # 旧 cj 000109 杏林营业所

_DEPT_CJ_CACHE = None


def dept_cj_map() -> dict:
    """新 departments.id → 旧 bb_bumen.cj(wzcgsq.cj 前缀过滤与新建单据写入用)。"""
    global _DEPT_CJ_CACHE
    if _DEPT_CJ_CACHE is None:
        path = (Path(__file__).resolve().parents[2] / "scripts" / "migration_reports"
                / "department_map.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        _DEPT_CJ_CACHE = {
            int(v["new_id"]): (v.get("cj") or "")
            for v in data["depts"].values() if v.get("new_id")
        }
    return _DEPT_CJ_CACHE


def _subtree_ids(db, root_ids) -> set:
    ids = set(root_ids)
    while True:
        children = (
            db.query(Department.id)
            .filter(Department.parent_id.in_(ids), ~Department.id.in_(ids)).all()
        )
        if not children:
            break
        ids |= {c[0] for c in children}
    return ids


def finance_scope_ids(db, user) -> set | None:
    """本模块可见部门 id 集合(超管/无部门返回 None = 全部),含集美所特权。"""
    scope = dept_scope_ids(db, user)
    if scope is None:
        return None
    if JIMEI_DEPT_ID in {d.id for d in user.departments} and XINGLIN_DEPT_ID not in scope:
        scope = set(scope) | _subtree_ids(db, {XINGLIN_DEPT_ID})
    return scope


def dept_options(db, user) -> list:
    """部门下拉:当前可见范围(照旧 ViewBag.bb_bumen 只列本级及下级)。"""
    scope = finance_scope_ids(db, user)
    q = db.query(Department)
    if scope is not None:
        q = q.filter(Department.id.in_(scope))
    return [{"id": d.id, "name": d.name, "cj": dept_cj_map().get(d.id, "")}
            for d in q.order_by(Department.id).all()]


def display_name(user: User) -> str:
    return (user.real_name or "").strip() or user.username


def user_dept_id(user: User):
    return user.departments[0].id if user.departments else None


def default_bmid(user: User):
    """新增单据的部门:取登录人第一个部门(超管无部门时返回 None)。"""
    return user_dept_id(user)


def _apply_scope(q, column, db, user):
    scope = finance_scope_ids(db, user)
    if scope is not None:
        q = q.filter(column.in_(scope))
    return q


# ==================== 固定资产 gdzc ====================
def gdzc_query(db, user, *, nd="", keyword="", dept_id=None, categories="",
               qy_years="", expired=False):
    """照旧 cwService.LoadSearchEntities:年份是必过滤条件,部门/类别/启用年度/到期/关键字可选。

    旧代码关键字为非数字时 a=0,会意外命中 yz=0 的记录(明显 bug),这里只在
    关键字确实是数字时才追加「原值精确等于」,避免误命中。
    """
    q = db.query(ZcCw).outerjoin(ZcLb, ZcCw.lbid == ZcLb.id)
    q = _apply_scope(q, ZcCw.bmid, db, user)

    nd_value = int(nd) if str(nd).isdigit() else 0
    q = q.filter(ZcCw.nd == nd_value)   # 照旧:不传年度 ndid=0 → 查不到数据
    if dept_id:
        q = q.filter(ZcCw.bmid.in_(_subtree_ids(db, {int(dept_id)})))

    ids = [int(x) for x in str(categories or "").split(",") if x.strip().isdigit()]
    if ids:
        q = q.filter(ZcCw.lbid.in_(ids))

    years = [int(x) for x in str(qy_years or "").split(",") if x.strip().isdigit()]
    if years:
        q = q.filter(func.year(ZcCw.qyrq).in_(years))

    if expired:
        q = q.filter(ZcCw.yujishiyong == ZcCw.yishiyong)

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        conds = [
            ZcCw.sbname.like(like), ZcCw.guige.like(like), ZcCw.didian.like(like),
            ZcCw.zccode.like(like), ZcCw.sbbh.like(like), ZcCw.beizhu.like(like),
            ZcCw.pandian.like(like), ZcCw.baofeiqk == kw,
        ]
        try:
            conds.append(ZcCw.yz == float(kw))
        except ValueError:
            pass
        q = q.filter(or_(*conds))
    return q


def gdzc_totals(q):
    row = (q.order_by(None)
           .with_entities(func.coalesce(func.sum(ZcCw.yz), 0),
                          func.coalesce(func.sum(ZcCw.jz), 0)).first())
    return round(float(row[0] or 0), 2), round(float(row[1] or 0), 2)


def gdzc_rows(db, rows) -> list:
    """照旧 Getxz 投影:补 lb(类别名) / bm(部门名) / xsriqi / 到期标记。"""
    names = dept_name_map(db)
    cats = {c.id: c.lb for c in db.query(ZcLb).all()}
    out = []
    for r in rows:
        d = r.to_dict()
        d["lb"] = cats.get(r.lbid) or ""
        d["bm"] = names.get(r.bmid) or ""
        d["xsriqi"] = d["qyrq"] or ""
        d["expired_flag"] = bool(
            r.yishiyong and r.yujishiyong == r.yishiyong and r.yishiyong > 0
        )
        out.append(d)
    return out


# ==================== 清理报告 baofeizc ====================
def baofei_query(db, user, *, keyword="", dept_id=None, start="", end=""):
    q = db.query(ZcBaofeidan)
    q = _apply_scope(q, ZcBaofeidan.bmid, db, user)
    if dept_id:
        q = q.filter(ZcBaofeidan.bmid.in_(_subtree_ids(db, {int(dept_id)})))
    # 照旧 zc_baofeiService:rqend 加一天后取 < (含结束日全天)
    if start:
        try:
            q = q.filter(ZcBaofeidan.riqi >= date.fromisoformat(start))
        except ValueError:
            pass
    if end:
        try:
            q = q.filter(ZcBaofeidan.riqi < date.fromisoformat(end) + timedelta(days=1))
        except ValueError:
            pass
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        conds = [
            ZcCw.sbname.like(like), ZcCw.guige.like(like), ZcCw.didian.like(like),
            ZcCw.zccode.like(like), ZcCw.sbbh.like(like), ZcCw.beizhu.like(like),
        ]
        try:
            conds.append(ZcCw.yz == float(kw))
        except ValueError:
            pass
        # 旧系统关键字搜的是已挂报废单的资产明细,命中明细所属单据被返回
        ids = (db.query(ZcCw.baofeidanid)
               .filter(ZcCw.baofeidanid.isnot(None), or_(*conds)).distinct().all())
        q = q.filter(ZcBaofeidan.id.in_([i[0] for i in ids]))
    return q


def baofei_rows(db, user, rows) -> list:
    names = dept_name_map(db)
    out = []
    for r in rows:
        d = r.to_dict()
        d["bm"] = names.get(r.bmid) or ""
        d["ts"] = db.query(func.count(ZcCw.id)).filter(
            ZcCw.baofeidanid == r.id).scalar() or 0
        pics = (db.query(ZcBaofeitp).filter(ZcBaofeitp.bfdid == r.id)
                .order_by(ZcBaofeitp.id).all())
        d["tps"] = [image_url(p.dizhi, user.id) for p in pics if p.dizhi]
        out.append(d)
    return out


def candidate_query(db, user, *, bfid=0, keyword=""):
    """照旧 LoadSearchEntitiesBF:本部门未报废资产 ∪ 已挂当前单据资产。"""
    scope = finance_scope_ids(db, user)
    base = and_(ZcCw.baofeiqk.is_(None))
    if scope is not None:
        base = and_(base, ZcCw.bmid.in_(scope))
    q = db.query(ZcCw).filter(or_(base, ZcCw.baofeidanid == (bfid or 0)))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        conds = [
            ZcCw.sbname.like(like), ZcCw.guige.like(like), ZcCw.didian.like(like),
            ZcCw.zccode.like(like), ZcCw.sbbh.like(like), ZcCw.beizhu.like(like),
            ZcCw.pandian.like(like),
        ]
        try:
            conds.append(ZcCw.yz == float(kw))
        except ValueError:
            pass
        q = q.filter(or_(*conds))
    return q


# ==================== 物资采购申请 wzcgsq ====================
def wz_scope_cj(db, user, scope: str):
    """返回 (前缀列表, 是否按本人过滤)。照旧 GetList 的 scope 语义。

    scope=all 仍是「全部有权限部门」,不是全库,必须保留当前用户的 cj 前缀限制。
    """
    mine = (not scope or scope == "mine")
    user_cj = "" if user.is_superuser else dept_cj_map().get(user_dept_id(user) or 0, "")
    if scope in ("all", "", "mine"):
        return ([user_cj] if user_cj else []), mine
    if str(scope).isdigit():
        did = int(scope)
        allowed = finance_scope_ids(db, user)
        if allowed is None or did in allowed:
            cj = dept_cj_map().get(did, "")
            if cj:
                return [cj], False
        return [""], False   # 越权部门 → 空列表
    # 非法 scope 退化为全部「有权限」部门,照旧不给全库
    return ([user_cj] if user_cj else []), False


def wzcgsq_query(db, user, *, keyword="", start="", end="", scope="mine"):
    q = db.query(Wzcgsq)
    prefixes, mine = wz_scope_cj(db, user, scope)
    if prefixes:
        q = q.filter(or_(*[Wzcgsq.cj.like(f"{p}%") for p in prefixes]))
    if mine:
        q = q.filter(or_(Wzcgsq.userid == user.id,
                         and_(Wzcgsq.userid.is_(None), Wzcgsq.username == display_name(user))))
    if start:
        try:
            q = q.filter(Wzcgsq.djriqi >= datetime.combine(date.fromisoformat(start), datetime.min.time()))
        except ValueError:
            pass
    if end:
        try:
            q = q.filter(Wzcgsq.djriqi < datetime.combine(
                date.fromisoformat(end) + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        main_ids = (db.query(WzcgsqMx.mainid)
                    .filter(or_(WzcgsqMx.wpmc.like(like), WzcgsqMx.ggxh.like(like)))
                    .distinct().all())
        q = q.filter(or_(Wzcgsq.bumen.like(like), Wzcgsq.sgyy.like(like),
                         Wzcgsq.username.like(like),
                         Wzcgsq.id.in_([i[0] for i in main_ids])))
    return q


def wzcgsq_visible(db, user, main_id: int) -> Wzcgsq:
    """所有单头/明细/打印/下载统一的数据范围校验(补旧 GetMx/ShowEditInfo 的越权缺口)。"""
    m = db.get(Wzcgsq, main_id)
    if m is None:
        raise HTTPException(status_code=404, detail="采购申请单不存在")
    if not user.is_superuser:
        cj = dept_cj_map().get(user_dept_id(user) or 0, "")
        if not cj or not (m.cj or "").startswith(cj):
            raise HTTPException(status_code=403, detail="无权访问该采购单")
    return m


def is_owner(user: User, m: Wzcgsq) -> bool:
    """照旧 IsOwner:优先 userid,旧数据 userid 为 NULL 时回退 username 文本。"""
    if m.userid:
        return m.userid == user.id
    return (m.username or "") == display_name(user)


def wzcgsq_rows(db, rows) -> list:
    out = []
    for r in rows:
        d = r.to_dict()
        d["mxcount"] = db.query(func.count(WzcgsqMx.id)).filter(
            WzcgsqMx.mainid == r.id).scalar() or 0
        d["djriqi"] = (d["djriqi"] or "")[:10]
        out.append(d)
    return out


# ==================== 报废单图片(短令牌代理) ====================
IMAGE_SCOPE = "finance_image"


def image_url(dizhi: str, user_id: int) -> str:
    if not dizhi:
        return ""
    token = create_short_token(IMAGE_SCOPE, {"p": dizhi, "sub": str(user_id)}, minutes=180)
    return f"/api/baofeizc/image?token={token}"


def _safe_rel(dizhi: str) -> Path | None:
    rel = (dizhi or "").replace("\\", "/").lstrip("/")
    if rel.lower().startswith("upload/"):
        rel = rel[len("upload/"):]
    p = Path(rel)
    if not rel or p.is_absolute() or ".." in p.parts:
        return None
    return p


def image_path(dizhi: str) -> Path | None:
    rel = _safe_rel(dizhi)
    return Path(settings.UPLOAD_DIR) / rel if rel else None


def read_image(token: str):
    try:
        payload = decode_short_token(token, IMAGE_SCOPE)
    except Exception:
        return None, "image/png"
    rel = _safe_rel(payload.get("p", ""))
    if rel is None:
        return None, "image/png"
    path = Path(settings.UPLOAD_DIR) / rel
    if not path.is_file():
        return None, "image/png"
    suffix = path.suffix.lower()
    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}.get(
                 suffix, "application/octet-stream")
    return path.read_bytes(), media


def save_upload(data: bytes, filename: str) -> str:
    """新上传的报废单图片落到 backend/uploads,返回旧格式的 /Upload/... 路径。"""
    now = datetime.now()
    rel = Path("baofeidanImages") / str(now.year) / str(now.month) / str(now.day) / filename
    dest = Path(settings.UPLOAD_DIR) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return "/Upload/" + rel.as_posix()
