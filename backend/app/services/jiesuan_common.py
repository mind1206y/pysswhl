"""材料结算单查看(照旧 JiesuanController + Views/Jiesuan/Index.cshtml 复刻)。

只读列表:列出部门子树内、领料单状态为已审核/部分结算/全部结算的领料明细,
附带材料上次单价、已结算数量、剩余可结算数量与最近一次结算日期。
旧页面无新增/修改/删除入口(控制器里的 SaveJiesuan/Edit 属残留死代码,不复刻)。
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.jiesuandan import JiesuanCailiao, JiesuanDetail
from app.models.lingliao import LingLiao, LingLiaoDetail
from app.models.material import MaterialLibrary


def r4(v) -> float:
    return round(float(v or 0), 4)


def s(v) -> str:
    return "" if v is None else str(v)


def view_query(db: Session, scope=None, keyword: str = ""):
    q = (
        db.query(LingLiaoDetail, LingLiao, MaterialLibrary)
        .join(LingLiao, LingLiaoDetail.lingliaoid == LingLiao.id)
        .outerjoin(MaterialLibrary, LingLiaoDetail.material_id == MaterialLibrary.id)
        .filter(LingLiao.shzt.in_((2, 5, 6)))
    )
    if scope is not None:
        q = q.filter(LingLiao.bmid.in_(scope))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(
            LingLiaoDetail.llname.like(like),
            LingLiao.danno.like(like),
            LingLiao.gongyingshang.like(like),
            LingLiaoDetail.materialname.like(like),
            LingLiaoDetail.beizhu.like(like),
        ))
    return q


def settlement_dates(db: Session, detail_ids) -> dict:
    ids = list(dict.fromkeys(int(i) for i in detail_ids if i))
    if not ids:
        return {}
    rows = (
        db.query(JiesuanDetail.lingliaodetailid, JiesuanCailiao.jiesuanriqi)
        .join(JiesuanCailiao, JiesuanDetail.jiesuanid == JiesuanCailiao.id)
        .filter(JiesuanDetail.lingliaodetailid.in_(ids))
        .order_by(JiesuanDetail.id)
        .all()
    )
    result = {}
    for detail_id, jiesuanriqi in rows:
        if detail_id in result:
            continue
        result[detail_id] = jiesuanriqi.strftime("%Y-%m-%d") if jiesuanriqi else ""
    return result


def view_rows(db: Session, scope, keyword: str = "", page: int = 1,
              size: int = 20) -> tuple:
    q = view_query(db, scope, keyword)
    total = q.count()
    page_size = max(int(size or 20), 1)
    rows = (
        q.order_by(LingLiaoDetail.id.desc())
        .offset((max(int(page or 1), 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    dates = settlement_dates(db, [detail.id for detail, _main, _mat in rows])
    result = []
    for detail, main, material in rows:
        renum = r4(detail.renum)
        jiesuannum = r4(detail.jiesuannum)
        result.append({
            "danno": s(main.danno),
            # 旧页面「材料ID」列绑定的是领料明细 id,这里保持 1:1
            "id": detail.id,
            "MaterialId": detail.material_id,
            "materialname": s(detail.materialname),
            "danjia": r4(material.lastdanjia if material is not None else None),
            "model": s(detail.model),
            "spec": s(detail.spec),
            "unit": s(detail.unit),
            "jsrq": dates.get(detail.id, ""),
            "llname": s(detail.llname),
            "beizhu": s(detail.beizhu),
            "num": r4(detail.num),
            "renum": renum,
            "jiesuannum": jiesuannum,
            "shengyu": round(renum - jiesuannum, 4),
            "gongyingshang": s(main.gongyingshang),
            "sqriqi": main.sqriqi.strftime("%Y-%m-%d") if main.sqriqi else "",
        })
    return total, result
