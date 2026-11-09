"""合同登记/归集公共常量与序列化(照旧 htdj/htgj)。"""

from datetime import datetime

from app.api.deps import dept_name_map

# 履行情况(旧系统 htdjController.Index 的下拉)
LVXING_QINGKUANG = ["合同签约", "合同履行", "履行中止", "履行完毕", "履行异常"]

# 合同类别(旧系统顺序)
LEIBIE = [
    "买卖合同", "技术合同", "租赁合同", "委托合同", "建设工程合同", "融资租赁合同",
    "承揽合同", "运输合同", "供用电、水、气、热力合同", "保管合同", "仓储合同",
    "行纪合同", "居间合同", "赠与合同", "借款合同", "其他",
]

# 招标方式(旧系统顺序)
ZHAOBIAO_FANGSHI = [
    "直接采购", "网上竞价", "单一来源采购", "竞争性谈判", "竞争性磋商", "询价",
    "最低价评标法的公开招标", "最低价评标法的邀请招标",
    "综合评分法的公开招标", "综合评分法的邀请招标",
]

# 旧 htdjController.CheckTextLen 的长文本上限
TEXT_LIMITS = {
    "name": (500, "合同名称"),
    "biaodi": (1000, "合同标的"),
    "nr": (2000, "简要内容"),
    "beizhu": (1000, "备注描述"),
    "duixiang": (500, "签订对象"),
}


def _day(v):
    return v.strftime("%Y-%m-%d") if v else None


def _time(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if v else None


def display_name(user) -> str:
    return (user.real_name or user.username or "").strip()


def check_text_len(data) -> None:
    """超长文本护栏,和旧系统一样返回中文提示(由路由转 400)。"""
    for field, (limit, label) in TEXT_LIMITS.items():
        value = getattr(data, field, None)
        if value is not None and len(str(value)) > limit:
            raise ValueError(f"{label}最多 {limit} 字,当前 {len(str(value))} 字,请精简后再保存")


def supplier_dict(row) -> dict:
    return {
        "id": row.id,
        "gongyingshang": row.gongyingshang or "",
        "toubiaojia": float(row.toubiaojia) if row.toubiaojia is not None else None,
        "zuizhongjia": float(row.zuizhongjia) if row.zuizhongjia is not None else None,
        "paixu": row.paixu,
        "sfzb": bool(row.sfzb),
        "swfs": float(row.swfs) if row.swfs is not None else None,
        "jsfs": float(row.jsfs) if row.jsfs is not None else None,
        "jgfs": float(row.jgfs) if row.jgfs is not None else None,
        "zfs": float(row.zfs) if row.zfs is not None else None,
        "beizhu": row.beizhu or "",
    }


def contract_dict(row, dept_names=None, tps=None, suppliers=None) -> dict:
    dept_names = dept_names or {}
    return {
        "id": row.id,
        "ID": row.id,
        "name": row.name or "",
        "nr": row.nr or "",
        "bz": row.bz or "",
        "djdate": _time(row.djdate),
        "editdate": _time(row.editdate),
        "djuser": row.djuser,
        "user": row.djuser_name or "",
        "spuserid": row.spuserid,
        "sp": row.spuserid_name or "",
        "zt": row.zt or "",
        "niandu": row.niandu,
        "bh": row.bh,
        "spdate": _time(row.spdate),
        "locked": row.locked,
        "jine": float(row.jine) if row.jine is not None else None,
        "allbh": row.allbh or "",
        "leibie": row.leibie or "",
        "duixiang": row.duixiang or "",
        "biaodi": row.biaodi or "",
        "zzdate": _day(row.zzdate),
        "lvxingqingkuang": row.lvxingqingkuang or "",
        "jingbanren": row.jingbanren or "",
        "qddate": _day(row.qddate),
        "ssdate": _day(row.ssdate),
        "gjtime": _time(row.gjtime),
        "bumenid": row.bumenid,
        "bm": dept_names.get(row.bumenid, ""),
        "beizhu": row.beizhu or "",
        "zhaobiaofangshi": row.zhaobiaofangshi or "",
        "kongzhijia": float(row.kongzhijia) if row.kongzhijia is not None else None,
        "sfwjdw": bool(row.sfwjdw) if row.sfwjdw is not None else None,
        "tps": tps or [],
        "suppliers": suppliers or [],
    }


def load_related(db, contract_ids):
    """批量取附件与供应商明细,返回 {htid: (tps, suppliers)}。"""
    from app.models.contract import HtTp, HtZbSupplier

    tps, sups = {}, {}
    if not contract_ids:
        return {}
    for a in (
        db.query(HtTp)
        .filter(HtTp.htid.in_(contract_ids))
        .order_by(HtTp.id)
        .all()
    ):
        tps.setdefault(a.htid, []).append(
            {"id": a.id, "url": a.url or "", "oldname": a.oldname or "", "fsize": float(a.fsize) if a.fsize is not None else None}
        )
    for s in (
        db.query(HtZbSupplier)
        .filter(HtZbSupplier.htid.in_(contract_ids))
        .order_by(HtZbSupplier.paixu, HtZbSupplier.id)
        .all()
    ):
        sups.setdefault(s.htid, []).append(supplier_dict(s))
    return {cid: (tps.get(cid, []), sups.get(cid, [])) for cid in contract_ids}


def dicts_payload():
    return {
        "lvxingqingkuang": LVXING_QINGKUANG,
        "leibie": LEIBIE,
        "zhaobiaofangshi": ZHAOBIAO_FANGSHI,
    }


def department_names(db):
    return dept_name_map(db)


def now():
    return datetime.now()
