"""稽查模块共享服务:筛选/行组装/字典/奖励计算(jcxt + spjicha + jcjl 共用)。

口径全部照旧系统 1:1 复刻(whl.BLL/jcxxService.cs、ExcelJcxt.cs、
SpjichaController.comput/compta/jsjb/FairlyDistribute):
- 日期口径 lb(rqsx) 5 种分支,含 C# &&/|| 优先级语义
- tijiao 开关:true -> spzt != 暂存;false -> spzt == 暂存;审批页恒排除暂存
- 大管 dg -> intguanjing >= 300;逃逸/农村稽查精确匹配
- 奖励计算硬编码部门按迁移映射:旧 1(售水总)->7、旧 4(售水本部)->15、旧 8(同安)->12
"""

import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.jcxt import JcJcxx, JcTupian

# 旧系统硬编码部门 id -> 新 departments.id(迁移映射:旧1->7 旧4->15 旧8->12)
BM_TOTAL = 7     # 售水事业部(旧 1,售水总奖励汇总行)
BM_HQ = 15       # 售水本部(旧 4,拿追缴补贴 30%)
BM_TONGAN = 12   # 同安营业所(旧 8,追缴奖励 3.5% 公平分配)

# 下拉字典(照旧 ViewBag)
WZLEIBIE = [
    "施工挖破水管", "汽车撞断消防栓", "私启消防栓用水", "私接市政管道用水",
    "私自倒装水表", "私自装表", "私自破坏水表", "其他",
]
WZLEIBIE_SP = WZLEIBIE[:4] + ["其他"]  # 审批页的违章类别下拉(旧 Spjicha Index)
JUBAOLEIBIE = ["内部员工", "外协人员", "用户举报", "肇事举报", "稽查人员", "其他"]
ZHUIJIAOBM = ["稽查部", "管网部", "营业部"]
ZHUANGTAI = ["处理中", "已完结"]
ZHUANGTAI_FILTER = ["处理中", "已完结", "未提交"]
ZHIXINGQK_JCXT = ["逃逸"]
ZHIXINGQK_SP = ["已缴款", "不处理", "减免", "逃逸"]
XINXILAIYUAN = ["96303下单", "用户举报", "其他"]
NONGCUN = ["农村稽查"]
GUANCAI = ["PVC", "球墨铸铁", "灰口铸铁", "镀锌", "钢管", "水泥管", "PE", "砼管",
           "玻璃钢管", "PPR管", "塑钢管", "其他材质"]
GUANJING = ["DN15", "DN20", "DN25", "DN32", "DN40", "DN50", "DN63", "DN75", "DN80",
            "DN90", "消防栓", "DN100", "DN110", "DN150", "DN160", "DN200", "DN250",
            "DN300", "DN400", "DN500", "DN600", "DN700", "DN800", "DN1000", "DN1100",
            "DN1200", "DN1400", "DN1600", "DN1800", "DN2000", "其他口径"]
DANJIA = ["3.7", "2.2", "2.6", "3.2", "4.1", "5.2"]
RQSX = ["违章日期", "已处理", "该月报表", "该月发生未处理", "没当月处理"]

# 导出字段清单(照旧 ShowColum,modJcxt_yhxz)
EXPORT_FIELDS = [
    ("gongdanhao", "工单号"), ("caozuoriqi", "操作日期"), ("chuliriqi", "处理日期"),
    ("weizhangriqi", "违章日期"), ("zhuangtai", "处理状态"), ("zhuijiaojiangli", "追缴奖励"),
    ("jbjiangli", "举报奖励"), ("zuihougengxin", "最后更新日期"), ("zhuijiaobm", "追缴部门/人员"),
    ("ssbmid", "所属部门"), ("jubaoren", "举报人"), ("zhuijiaogongliaofei", "追缴工料费"),
    ("zhuijiaoshuifei", "追缴水费"), ("weizhangdizhi", "违章地址"), ("weizhangdianhua", "违章电话"),
    ("weizhangren", "违章单位"), ("wzleibie", "违章类别"), ("beizhu", "备注"),
    ("jubaoleibie", "举报类别"), ("weizhangneirong", "违章内容"), ("guanjing", "管径"),
    ("guancai", "管材"), ("zhuijiaoshuiliang", "追缴水量"), ("nongcunjicha", "农村稽查"),
    ("peibiaofei", "赔表费"), ("spzt", "审批状态"),
]


def get_date_range(filter_type: str, selected_month: str,
                   rq: Optional[str], rqend: Optional[str]):
    """照旧 DateHelper.GetDateRange。返回 (start, end) 字符串或 None。"""
    if filter_type == "currentMonth":
        now = datetime.now()
        first = now.strftime("%Y-%m-01")
        last = f"{now.year}-{now.month:02d}-{calendar.monthrange(now.year, now.month)[1]}"
        return first, last
    if filter_type == "lastMonth":
        lm = (datetime.now().replace(day=1) - timedelta(days=1))
        first = f"{lm.year}-{lm.month:02d}-01"
        last = f"{lm.year}-{lm.month:02d}-{calendar.monthrange(lm.year, lm.month)[1]}"
        return first, last
    if filter_type == "selectMonth":
        if not selected_month:
            return None, None
        y, m = int(selected_month[:4]), int(selected_month[5:7])
        return (f"{y}-{m:02d}-01",
                f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]}")
    # custom 或空:自选日期
    return rq or None, rqend or None


def computer_gj(guanjing: Optional[str]) -> int:
    """照旧 computerGj:DNxx -> 数值;消防栓/其他口径/空 -> 0。"""
    if not guanjing:
        return 0
    g = guanjing.strip()
    if g.startswith("DN"):
        try:
            return int(g[2:])
        except ValueError:
            return 0
    return 0


def parse_date(v: Optional[str], end_inclusive: bool = False) -> Optional[datetime]:
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            continue
    try:
        d = date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None
    if end_inclusive:
        return datetime(d.year, d.month, d.day, 23, 59, 59)
    return datetime(d.year, d.month, d.day)


def apply_jcxx_filters(
    q,
    *,
    rq: Optional[str], rqend: Optional[str], lb: Optional[str],
    lbid: Optional[str] = "", jblb: Optional[str] = "",
    guanjing: Optional[str] = "",
    mohu: Optional[str] = "",
    dg: bool = False, taoyi: bool = False, nongcun: bool = False,
    tijiao: Optional[bool] = None, sp_mode: bool = False,
    dept_ids: Optional[set] = None,
):
    """照旧 jcxxService.LoadSearchEntities / LoadSearchEntitiesSp 的 WHERE 构造。

    dept_ids: 部门作用域(旧 cj 前缀语义换算成 departments 子树 id 集合);
    None 表示不限定(超管/未挂部门)。
    """
    # 照旧:rq 与 rqend 都非空才用自定义区间,否则 当月1号 ~ 现在
    ksd = parse_date(rq) if rq else None
    jsd = parse_date(rqend, end_inclusive=True) if rqend else None
    if not (rq and rqend and ksd and jsd):
        ksd = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        jsd = datetime.now()

    # 1. 部门(旧 cj 前缀)
    if dept_ids is not None:
        q = q.filter(JcJcxx.ssbmid.in_(dept_ids))

    # 2. lb(rqsx) 日期口径 5 分支
    if lb in (None, "", "违章日期"):
        if ksd:
            q = q.filter(JcJcxx.weizhangriqi >= ksd)
        if jsd:
            q = q.filter(JcJcxx.weizhangriqi <= jsd)
    elif lb == "该月报表":
        # 旧: (weizhangriqi 属 jsd 月) || (chuliriqi 属 jsd 月);jsd 空则用今天
        anchor = jsd or datetime.now()
        month_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = month_start.year * 12 + month_start.month
        days = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=days, hour=23, minute=59, second=59)
        q = q.filter(or_(
            (JcJcxx.weizhangriqi >= month_start) & (JcJcxx.weizhangriqi <= month_end),
            (JcJcxx.chuliriqi >= month_start) & (JcJcxx.chuliriqi <= month_end),
        ))
    elif lb == "该月发生未处理":
        anchor = jsd or datetime.now()
        month_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=days, hour=23, minute=59, second=59)
        q = q.filter(
            (JcJcxx.weizhangriqi >= month_start) & (JcJcxx.weizhangriqi <= month_end)
            & ((JcJcxx.zhuijiaoshuifei.is_(None) & JcJcxx.zhuijiaogongliaofei.is_(None))
               | ((JcJcxx.zhuijiaogongliaofei <= 0) & (JcJcxx.zhuijiaoshuifei <= 0)))
        )
    elif lb == "没当月处理":
        anchor = jsd or datetime.now()
        month_start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=days, hour=23, minute=59, second=59)
        q = q.filter(
            (JcJcxx.weizhangriqi >= month_start) & (JcJcxx.weizhangriqi <= month_end)
            & (JcJcxx.chuliriqi.is_(None)
               | (func.month(JcJcxx.chuliriqi) > anchor.month))
        )
        # 旧 EF 翻译成 SQL MONTH():跨年时会误留"往年同月之后"的行,这里保持等价
    else:  # "已处理"及其它值
        if ksd:
            q = q.filter(JcJcxx.chuliriqi >= ksd)
        if jsd:
            q = q.filter(JcJcxx.chuliriqi <= jsd)
        q = q.filter(
            or_(JcJcxx.zhuijiaoshuifei.isnot(None), JcJcxx.zhuijiaogongliaofei.isnot(None))
            & or_(JcJcxx.zhuijiaogongliaofei >= 0, JcJcxx.zhuijiaoshuifei >= 0)
        )

    # 3. 各下拉/开关
    if lbid:
        q = q.filter(JcJcxx.wzleibie == lbid)
    if jblb:
        q = q.filter(JcJcxx.jubaoleibie == jblb)
    if guanjing:
        q = q.filter(JcJcxx.guanjing == guanjing)
    if mohu:
        like = f"%{mohu}%"
        q = q.filter(or_(
            JcJcxx.weizhangren.contains(mohu),
            JcJcxx.weizhangdianhua.contains(mohu),
            JcJcxx.weizhangdizhi.contains(mohu),
            JcJcxx.beizhu.contains(mohu),
            JcJcxx.jubaoren.contains(mohu),
            JcJcxx.weizhangneirong.contains(mohu),
            JcJcxx.gongdanhao.contains(mohu),
            JcJcxx.zhuijiaobm.contains(mohu),
            JcJcxx.nongcunjicha.contains(mohu),
        ))
    if dg:
        q = q.filter(JcJcxx.intguanjing >= 300)
    if taoyi:
        q = q.filter(JcJcxx.zhixingqingkuang == "逃逸")
    if nongcun:
        q = q.filter(JcJcxx.nongcunjicha == "农村稽查")
    # 4. 提交开关:审批页恒排除暂存;稽查页 true=非暂存 / false=暂存
    if sp_mode:
        q = q.filter(JcJcxx.spzt != "暂存")
    elif tijiao is True:
        q = q.filter(JcJcxx.spzt != "暂存")
    elif tijiao is False:
        q = q.filter(JcJcxx.spzt == "暂存")
    return q


def order_jcxx(q, px: bool):
    """照旧:px=true 按最后更新降序;否则违章日期降序+最后更新降序。"""
    if px:
        return q.order_by(JcJcxx.zuihougengxin.desc(), JcJcxx.id.desc())
    return q.order_by(JcJcxx.weizhangriqi.desc(), JcJcxx.zuihougengxin.desc(), JcJcxx.id.desc())


def _num(v):
    return Decimal("0") if v is None else Decimal(v)


def jcxx_row(db: Session, row: JcJcxx, dept_names: dict, pics: dict) -> dict:
    """列表行组装(照旧 getjcList 投影):ze=工料费+水费。"""
    sf = _num(row.zhuijiaoshuifei)
    glf = _num(row.zhuijiaogongliaofei)
    return {
        **row.to_dict(),
        "zhuijiaoshuifei": float(sf) if row.zhuijiaoshuifei is not None else None,
        "zhuijiaogongliaofei": float(glf) if row.zhuijiaogongliaofei is not None else None,
        "jbjiangli": float(row.jbjiangli) if row.jbjiangli is not None else None,
        "zhuijiaojiangli": float(row.zhuijiaojiangli) if row.zhuijiaojiangli is not None else None,
        "peibiaofei": float(row.peibiaofei) if row.peibiaofei is not None else None,
        "danjia": float(row.danjia) if row.danjia is not None else None,
        "ze": float(sf + glf),
        "bumen": dept_names.get(row.ssbmid, ""),
        "tps": pics.get(row.id, []),
    }


def load_pics(db: Session, ids: List[int]) -> dict:
    """返回 {jcxxid: [{"id": 图片id, "url": 路径}]}(前端用 id 换短令牌)。"""
    if not ids:
        return {}
    rows = db.query(JcTupian).filter(JcTupian.jcxxid.in_(ids)).all()
    out: dict = {}
    for p in rows:
        out.setdefault(p.jcxxid, []).append({"id": p.id, "url": p.url or ""})
    return out


def jcxx_footer(q) -> list:
    """合计行(照旧 tongji* 回写):只对全量结果(未翻页)求和。"""
    rows = q.all()
    if not rows:
        return []
    total_sf = sum((_num(r.zhuijiaoshuifei) for r in rows), Decimal("0"))
    total_glf = sum((_num(r.zhuijiaogongliaofei) for r in rows), Decimal("0"))
    total_jbjl = sum((_num(r.jbjiangli) for r in rows), Decimal("0"))
    total_sl = sum((r.zhuijiaoshuiliang or 0) for r in rows)
    return [{
        "ze": float(total_sf + total_glf),
        "zhuijiaoshuifei": float(total_sf),
        "zhuijiaogongliaofei": float(total_glf),
        "jbjiangli": float(total_jbjl),
        "zhuijiaoshuiliang": total_sl,
    }]


# ==================== 奖励计算(照旧 SpjichaController) ====================

def _cint(x) -> int:
    """Convert.ToInt32:银行家舍入(与 C# 一致)。"""
    return int(Decimal(str(float(x))).quantize(Decimal("1"), rounding="ROUND_HALF_EVEN"))


def _round_away(x) -> int:
    """Math.Round(x, AwayFromZero):四舍五入(远离零)。"""
    return int(Decimal(str(float(x))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reward_base_query(db: Session, riqi: date):
    """照旧 ExcelJcxt.jgj:按处理日期所在年月、排除暂存、有追缴金额。"""
    start = datetime(riqi.year, riqi.month, 1)
    days = calendar.monthrange(riqi.year, riqi.month)[1]
    end = datetime(riqi.year, riqi.month, days, 23, 59, 59)
    return db.query(JcJcxx).filter(
        JcJcxx.chuliriqi >= start,
        JcJcxx.chuliriqi <= end,
        JcJcxx.spzt != "暂存",
        or_(JcJcxx.zhuijiaoshuifei.isnot(None), JcJcxx.zhuijiaogongliaofei.isnot(None)),
        or_(JcJcxx.zhuijiaogongliaofei >= 0, JcJcxx.zhuijiaoshuifei >= 0),
    )


def jsjb(lb: Optional[str], zjsf) -> int:
    """举报奖励公式(照旧 jsjb)。"""
    if zjsf is None or not lb:
        return 0
    if lb in ("用户举报", "外协人员"):
        if zjsf > 1000:
            return 100
        if zjsf > 99:
            return 50
        return 0
    if lb == "内部员工":
        if 0 < zjsf <= 100:
            return 0
        if 100 < zjsf <= 1000:
            return 50
        if 1000 < zjsf <= 5000:
            return 100
        if zjsf > 5000:
            return 200
    return 0


def fairly_distribute(rows: List[JcJcxx]) -> int:
    """同安追缴奖励公平分配(照旧 FairlyDistribute),返回处理条数。"""
    people = [r for r in rows if r.ssbmid == BM_TONGAN]
    if not people:
        return 0
    total_sum = sum((_num(p.zhuijiaoshuifei) for p in people), Decimal("0"))
    target_total = _round_away(float(total_sum) * 0.035)

    results = []
    for p in people:
        raw = _num(p.zhuijiaoshuifei) * Decimal("0.035")
        rounded = _round_away(float(raw))
        results.append({
            "row": p,
            "rounded": rounded,
            "diff": Decimal(rounded) - raw,
        })
    allocated = sum(r["rounded"] for r in results)
    error = target_total - allocated

    if error != 0:
        if error > 0:
            # 少分配的(Difference<0)从最负者起 +1
            neg = sorted([r for r in results if r["diff"] < 0], key=lambda r: r["diff"])
            for i in range(abs(error)):
                if neg:
                    neg[0]["rounded"] += 1
                    neg.pop(0)
        else:
            # 多分配的(Difference>0)从最大者起 -1
            pos = sorted([r for r in results if r["diff"] > 0],
                         key=lambda r: r["diff"], reverse=True)
            for i in range(abs(error)):
                if pos:
                    pos[0]["rounded"] -= 1
                    pos.pop(0)

    for r in results:
        r["row"].zhuijiaojiangli = r["rounded"]
    return len(people)


def visible_dept_ids(db: Session, user) -> Optional[set]:
    """部门作用域(旧 cj 前缀语义)。超管/未挂部门返回 None。"""
    from app.api.deps import dept_scope_ids
    return dept_scope_ids(db, user)
