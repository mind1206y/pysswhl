"""审批稽查(照旧 SpjichaController 1:1 复刻)。

- 列表:与 jcxt 同一套筛选,但恒排除暂存(spzt != "暂存"),无 tijiao 开关
- 审批/取消审批:单个(oneok/kjqqxgzjh)+ 批量(dogz/qxgzjh);
  审批认领规则:未被他人认领(ssspren 空)或本人已审过的才可审;取消须审批人本人
- 计算奖励 comput:举报奖励 jsjb 回写 + jcjiangli 月度汇总(旧硬编码 bmid
  1/4 -> 新 7/15,尾差回补本部)
- 同安奖励 compta:追缴水费 3.5% 四舍五入公平分配(FairlyDistribute)
- 奖励报表导出 loadsx(按当前筛选月份);工单信息核对 upExcel(命中染绿)
- 月份上下文:旧系统靠 TempData,新系统由前端显式传 date(当前筛选结束日期)

权限:spjicha:view 模块入口 + 审批/奖励计算。
"""

import calendar
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.jcxt import JcJcxx, Jcjiangli, JcjiangliFp
from app.models.user import Department, User
from app.services import jcxt_excel
from app.services.jcxt_common import (
    BM_HQ, BM_TOTAL, apply_jcxx_filters, get_date_range, jcxx_footer,
    jcxx_row, load_pics, order_jcxx, parse_date, fairly_distribute,
    jsjb, reward_base_query, _cint,
)

router = APIRouter()


class SubmitIn(BaseModel):
    ids: str


def _dept_filter(db: Session, user: User, bmid: Optional[int]) -> Optional[set]:
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
        lbid=params.get("lbid") or "",
        guanjing=params.get("guanjing") or "",
        mohu=params.get("sousou") or "",
        dg=bool(params.get("dg")),
        sp_mode=True,
        dept_ids=_dept_filter(db, user, params.get("bmid")),
    )
    return q, end


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
    guanjing: str = "",
    sousou: str = "",
    bmid: Optional[int] = None,
    px: bool = False,
    dg: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    params = dict(filterType=filterType, selectedMonth=selectedMonth, rq=rq,
                  rqend=rqend, rqsx=rqsx, lbid=lbid, guanjing=guanjing,
                  sousou=sousou, bmid=bmid, px=px, dg=dg)
    q, _end = _list_query(db, current, params)
    total = q.count()
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows = order_jcxx(q, px).offset((page - 1) * size).limit(size).all()
    pics = load_pics(db, [r.id for r in rows])
    return {"total": total,
            "items": [jcxx_row(db, r, dept_names, pics) for r in rows],
            "footer": jcxx_footer(q)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    return {
        "departments": departments,
        "wzleibie": ["施工挖破水管", "汽车撞断消防栓", "私启消防栓用水",
                     "私接市政管道用水", "其他"],
        "rqsx": ["违章日期", "已处理", "该月报表", "该月发生未处理", "没当月处理"],
        "guanjing": ["DN15", "DN20", "DN25", "DN32", "DN40", "DN50", "DN63",
                     "DN75", "DN80", "DN90", "消防栓", "DN100", "DN110", "DN150",
                     "DN160", "DN200", "DN250", "DN300", "DN400", "DN500", "DN600",
                     "DN700", "DN800", "DN1000", "DN1100", "DN1200", "DN1400",
                     "DN1600", "DN1800", "DN2000", "其他口径"],
        "perms": {"view": True},
    }


# ==================== 审批 / 取消审批 ====================
@router.post("/approve/{row_id}")
def approve_one(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no")
    if row.ssspren and row.ssspren != current.username and not current.is_superuser:
        raise HTTPException(
            status_code=403,
            detail=f"该记录已由[{row.ssspren}]审批,如需改动请先取消其审批")
    row.spzt = "审核通过"
    row.spdate = datetime.now()
    row.ssspren = current.username
    db.commit()
    return {"ok": True}


@router.post("/approve-rows")
def approve_rows(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="错误")
    for s in data.ids.split(","):
        try:
            rid = int(s)
        except ValueError:
            continue
        if rid <= 0:
            continue
        row = db.get(JcJcxx, rid)
        if row is None:
            continue
        if row.ssspren and row.ssspren != current.username and not current.is_superuser:
            continue  # 照旧:已被他人认领的静默跳过
        row.spzt = "审核通过"
        row.spdate = datetime.now()
        row.ssspren = current.username
    db.commit()
    return {"ok": True}


@router.post("/cancel/{row_id}")
def cancel_one(
    row_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    row = db.get(JcJcxx, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no")
    if row.spzt != "审核通过":
        raise HTTPException(status_code=400, detail="该记录当前不是已审批状态")
    if row.ssspren != current.username and not current.is_superuser:
        raise HTTPException(
            status_code=403, detail=f"该记录由[{row.ssspren}]审批,只有审批人本人可取消")
    row.spzt = "待审核"
    row.spdate = datetime.now()
    row.ssspren = current.username
    db.commit()
    return {"ok": True}


@router.post("/cancel-rows")
def cancel_rows(
    data: SubmitIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    if not data.ids:
        raise HTTPException(status_code=400, detail="错误")
    for s in data.ids.split(","):
        try:
            rid = int(s)
        except ValueError:
            continue
        if rid <= 0:
            continue
        row = db.get(JcJcxx, rid)
        if row is None:
            continue
        # 照旧:只有「已审核通过且本人审批的」才会改回待审核,其余静默跳过
        if row.spzt == "审核通过" and (row.ssspren == current.username
                                       or current.is_superuser):
            row.spzt = "待审核"
            row.spdate = datetime.now()
            row.ssspren = current.username
    db.commit()
    return {"ok": True}


# ==================== 奖励计算 ====================
def _month_from_date(d: Optional[str]) -> datetime:
    v = parse_date(d, end_inclusive=True) or datetime.now()
    return v


@router.post("/comput")
def comput(
    date_str: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    """照旧 comput:举报奖励回写 + jcjiangli 三类汇总 + 尾差回补。"""
    rq = _month_from_date(date_str)
    jg = reward_base_query(db, rq.date()).all()

    for row in jg:
        if not row.jubaoren:
            row.jbjiangli = 0
        else:
            row.jbjiangli = jsjb(row.jubaoleibie, row.zhuijiaoshuifei)
    db.commit()

    zjsf = sum((_num_v(r.zhuijiaoshuifei) for r in jg), Decimal("0"))
    jbjl = sum((_num_v(r.jbjiangli) for r in jg), Decimal("0"))
    old = db.query(Jcjiangli).filter(Jcjiangli.nd == rq.year,
                                     Jcjiangli.yue == rq.month).all()
    for o in old:
        cnt = db.query(JcjiangliFp).filter(JcjiangliFp.jlid == o.id).count()
        if cnt > 0:
            raise HTTPException(status_code=400, detail="已分配奖励无法更新")
    for o in old:
        db.delete(o)
    db.flush()

    d = _cint(float(zjsf) * 0.05)  # 追缴补贴(总额 5%,银行家舍入)

    total = Jcjiangli(bmid=BM_TOTAL, nd=rq.year, yue=rq.month,
                      zjshuifei=zjsf, jbjiangli=jbjl, zjbutie_int=d,
                      jianglijine=jbjl + d, usname=current.username,
                      utime=datetime.now())
    db.add(total)
    db.flush()

    sszjje = _cint(d * 0.3)  # 本部拿追缴补贴 30%
    hq = Jcjiangli(bmid=BM_HQ, nd=rq.year, yue=rq.month, zjshuifei=0, jbjiangli=0,
                   zjbutie_int=sszjje, zjbutie=Decimal(d) * Decimal("0.3"),
                   jianglijine=sszjje, usname=current.username, utime=datetime.now())
    db.add(hq)
    db.flush()

    # 各营业所(拿追缴补贴 70%)
    by_dept: dict = {}
    for r in jg:
        e = by_dept.setdefault(r.ssbmid, {"sf": Decimal("0"), "jbjl": Decimal("0")})
        e["sf"] += _num_v(r.zhuijiaoshuifei)
        e["jbjl"] += _num_v(r.jbjiangli)
    for bmid, e in by_dept.items():
        if bmid is None:
            continue
        zf = e["sf"] * Decimal("0.05") * Decimal("0.7")
        db.add(Jcjiangli(
            bmid=bmid, nd=rq.year, yue=rq.month, zjshuifei=e["sf"],
            jbjiangli=e["jbjl"], zjbutie=zf,
            zjbutie_int=_cint(zf),  # 旧 Convert.ToInt32(Math.Round(zf)),银行家舍入
            jianglijine=_cint(zf) + int(e["jbjl"]),
            usname=current.username, utime=datetime.now(),
        ))
    db.flush()

    # 尾差核对:非售水总记录的奖励合计回写 zjbutie,差额回补本部(照旧顺序)
    ze = db.query(func.coalesce(func.sum(Jcjiangli.jianglijine), 0)).filter(
        Jcjiangli.nd == rq.year, Jcjiangli.yue == rq.month,
        Jcjiangli.bmid != BM_TOTAL).scalar()
    ze = Decimal(str(ze or 0))
    total.zjbutie = ze
    jss = (total.jianglijine or Decimal("0")) - ze
    hq.zjbutie_int = sszjje + _cint(jss)
    hq.jianglijine = hq.zjbutie_int
    total.zjbutie = (total.zjbutie or Decimal("0")) + jss
    db.commit()
    return {"ok": True}


@router.post("/compta")
def compta(
    date_str: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    """照旧 compta:同安所追缴奖励 3.5% 公平分配。"""
    rq = _month_from_date(date_str)
    jg = reward_base_query(db, rq.date()).all()
    n = fairly_distribute(jg)
    db.commit()
    return {"ok": True, "updated": n}


def _num_v(v):
    return Decimal("0") if v is None else Decimal(v)


# ==================== 奖励报表导出(照旧 loadsx) ====================
@router.get("/export/reward")
def export_reward(
    date_str: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    rq = _month_from_date(date_str)
    rows = reward_base_query(db, rq.date()).all()
    dept_names = {d.id: d.name for d in db.query(Department).all()}
    wb = jcxt_excel.build_reward_report(rows, rq.date(), dept_names)
    buf = BytesIO()
    wb.save(buf)
    filename = f"{rq.year}-{rq.month:02d}稽查奖励报表.xlsx"
    from urllib.parse import quote
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ==================== 工单信息核对(照旧 upExcel/downhedui) ====================
@router.post("/hedui")
def hedui(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("spjicha:view")),
):
    fname = file.filename or ""
    if "工单信息" not in fname or not fname.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="需要名为工单信息的文件.xls")
    data = file.file.read()
    existing = {
        r[0] for r in db.query(JcJcxx.gongdanhao).filter(
            JcJcxx.gongdanhao.isnot(None)).all()
    }
    wb, hits = jcxt_excel.build_hedui(data, fname, existing)
    buf = BytesIO()
    wb.save(buf)
    from urllib.parse import quote
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote('工单核对结果文件.xlsx')}",
                 "X-Hedui-Hits": str(hits)},
    )
