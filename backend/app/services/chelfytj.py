"""车辆费用明细统计(照旧 chelfytjController 1:1 复刻)。

旧逻辑(Controllers/chelfytjController.cs + whl.BLL/chelService.LoadCheForTj):
- 车辆筛选:登录人部门子树(旧 cj StartsWith)→ 可再按部门下拉(子树)、关键字模糊
  (chehao/jiashiyuan/oilcard/lx/yongtu/telphone/pinpai/pingshi/fadongjihao/
   chejiahao/danganhao/syxingzhi)、类型(IN,逗号分隔)、用途(精确)、
  非油卡(yongtu != 油卡)、状态 zt(0 全部含已删除 / 1 正常 / 2 报废 / 3 已删除 delf==0)
- 排序:旧 OrderBy(bb_bumen.cj).ThenByDescending(chuchang);新 Department 无 cj,
  按既有约定改 bmid 升序 + chuchang 倒序
- 日期区间:rq/rqend 缺省取本年 1-1 ~ 12-31;结束时间扩到 23:59:59(旧 jsd 加时分秒)
- 每车四表金额(区间内):
  油费   = SUM(PlusOil.jine)      按 ptime
  维保费 = SUM(cl_wxdan.jine)     按 jcriqi
  保险费 = SUM(cl_baoxian.jine)   按 tbdate
  高速/停车/洗车 = SUM(cl_feiyong.jine) 按 feiyongdate 分 lx
  小计   = 油费+保险费+高速+洗车+停车+维保费(旧 ye 口径)
- footer 合计与列表行同口径(随状态等筛选变化),对全量车合计(不只当前页)
- 序号 ID 对全量车连续编号,分页只切内存列表;total = 车辆数
- 导出:全量车,列序照旧「序号/车牌号/油费/维保费/保险费/高速费/停车费/洗车费/小计/备注」,
  标题旧硬编码「2023年售水事业部…」,新系统按起始年 + 登录人部门名生成(修复硬编码年份)

权限:chelfytj:view(旧系统仅菜单控制访问,init_db 登记)。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import func, or_

from app.models.user import Department
from app.models.vehicle import ClBaoxian, ClChe, ClFeiyong, ClWxdan, PlusOil


def _n(v):
    return float(v) if isinstance(v, Decimal) else (v or 0)


def _round2(v):
    return round(_n(v), 2)


# ==================== 查询 ====================
MOHU_FIELDS = (
    ClChe.chehao, ClChe.jiashiyuan, ClChe.oilcard, ClChe.lx, ClChe.yongtu,
    ClChe.telphone, ClChe.pinpai, ClChe.pingshi, ClChe.fadongjihao,
    ClChe.chejiahao, ClChe.danganhao, ClChe.syxingzhi,
)


def parse_range(rq: str, rqend: str):
    """旧 getchl:缺省本年 1-1 ~ 12-31;结束扩到 23:59:59。"""
    year = datetime.now().year
    ksd = datetime(year, 1, 1)
    jsd = datetime(year, 12, 31, 23, 59, 59)
    if rq and rqend:
        try:
            ksd = datetime.strptime(rq, "%Y-%m-%d")
            jsd = datetime.strptime(rqend, "%Y-%m-%d") + timedelta(hours=23, minutes=59, seconds=59)
        except ValueError:
            pass
    return ksd, jsd


def car_query(db, user=None, *, subtree_ids=None, zt=0, mohu="", chellx="",
              chelyt="", nocd=False):
    """照旧 LoadCheForTj:部门子树 + 状态 + 模糊 + 类型/用途 + 非油卡。

    subtree_ids 由调用方算好:选了部门下拉取该部门子树(旧 StartsWith(bmcj),
    下拉本身已限在登录人子树内),否则取登录人部门子树;超管为 None 不限定。
    """
    q = db.query(ClChe)
    if subtree_ids is not None:
        q = q.filter(ClChe.bmid.in_(subtree_ids))
    if zt in (1, 2):
        q = q.filter(ClChe.delf == zt)
    elif zt == 3:
        # 旧代码写成 delf==3(delf 只有 0/1/2,选「已删除」永远空列表),按意图修正为 delf==0
        q = q.filter(ClChe.delf == 0)
    kw = (mohu or "").strip()
    if kw:
        q = q.filter(or_(*[f.like(f"%{kw}%") for f in MOHU_FIELDS]))
    lx_list = [s.strip() for s in (chellx or "").split(",") if s.strip()]
    if lx_list:
        q = q.filter(ClChe.lx.in_(lx_list))
    if (chelyt or "").strip():
        q = q.filter(ClChe.yongtu == chelyt.strip())
    if nocd:
        q = q.filter(ClChe.yongtu != "油卡")
    return q.order_by(ClChe.bmid.asc(), ClChe.chuchang.desc(), ClChe.id.asc())


def summarize(db, cars, ksd, jsd):
    """照旧 getchl:四表按车聚合(批量避免 N+1),返回 (rows, footer)。"""
    if not cars:
        return [], {"oil": "合计", "noil": 0, "weixiu": 0, "baoxian": 0,
                    "gaosu": 0, "tingche": 0, "xiche": 0, "ye": 0}
    ids = [c.id for c in cars]
    d_ksd, d_jsd = ksd.date(), jsd.date()

    oil = dict(db.query(PlusOil.cheid, func.sum(PlusOil.jine))
               .filter(PlusOil.cheid.in_(ids), PlusOil.ptime >= ksd, PlusOil.ptime <= jsd)
               .group_by(PlusOil.cheid).all())
    wx = dict(db.query(ClWxdan.cheid, func.sum(ClWxdan.jine))
              .filter(ClWxdan.cheid.in_(ids), ClWxdan.jcriqi >= d_ksd, ClWxdan.jcriqi <= d_jsd)
              .group_by(ClWxdan.cheid).all())
    bx = dict(db.query(ClBaoxian.cheid, func.sum(ClBaoxian.jine))
              .filter(ClBaoxian.cheid.in_(ids), ClBaoxian.tbdate >= d_ksd, ClBaoxian.tbdate <= d_jsd)
              .group_by(ClBaoxian.cheid).all())
    fees = {}
    for cheid, lx, jine in (
        db.query(ClFeiyong.cheid, ClFeiyong.lx, func.sum(ClFeiyong.jine))
        .filter(ClFeiyong.cheid.in_(ids),
                ClFeiyong.feiyongdate >= d_ksd, ClFeiyong.feiyongdate <= d_jsd)
        .group_by(ClFeiyong.cheid, ClFeiyong.lx).all()
    ):
        fees.setdefault(cheid, {})[lx] = jine

    dept_names = {d.id: d.name for d in db.query(Department).all()}
    rows, t = [], {"noil": 0, "weixiu": 0, "baoxian": 0, "gaosu": 0,
                   "tingche": 0, "xiche": 0, "ye": 0}
    for i, c in enumerate(cars, start=1):
        f = fees.get(c.id, {})
        noil, weixiu, baoxian = _n(oil.get(c.id)), _n(wx.get(c.id)), _n(bx.get(c.id))
        gaosu, tingche, xiche = _n(f.get("高速")), _n(f.get("停车")), _n(f.get("洗车"))
        ye = noil + baoxian + gaosu + xiche + tingche + weixiu  # 旧 ye 口径
        rows.append({
            "ID": i,
            "cheid": c.id,
            "bumen": dept_names.get(c.bmid) or c.bm or "",
            "chehao": c.chehao or "",
            "oil": c.oil or "",
            "delf": c.delf,
            "noil": _round2(noil), "weixiu": _round2(weixiu),
            "baoxian": _round2(baoxian), "gaosu": _round2(gaosu),
            "tingche": _round2(tingche), "xiche": _round2(xiche),
            "ye": _round2(ye),
        })
        t["noil"] += noil; t["weixiu"] += weixiu; t["baoxian"] += baoxian
        t["gaosu"] += gaosu; t["tingche"] += tingche; t["xiche"] += xiche
        t["ye"] += ye
    footer = {"oil": "合计", **{k: _round2(v) for k, v in t.items()}}
    return rows, footer


# ==================== 导出(照旧 GenerateExcel) ====================
EXPORT_HEADERS = ["序号", "车牌号", "油费", "维保费", "保险费",
                  "高速费", "停车费", "洗车费", "小计", "备注"]
_TITLE_FILL = PatternFill("solid", fgColor="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")   # 旧 Grey25Percent
_TOTAL_FILL = PatternFill("solid", fgColor="FFFF00")    # 旧 Yellow
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center")


def export_title(year: int, dept_name: str) -> str:
    """旧标题硬编码「2023年售水事业部车辆各类费用统计表」,新系统按查询起始年+部门名生成。"""
    return f"{year}年{dept_name}车辆各类费用统计表"


def build_excel(rows, footer, title: str) -> BytesIO:
    """照旧模板:标题合并行 + 灰底表头 + 数据行 + 黄底合计行(0-1 合并)。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "费用统计"
    widths = [6, 12, 10, 14, 10, 8, 8, 8, 10, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(EXPORT_HEADERS))
    tc = ws.cell(row=1, column=1, value=title)
    tc.font = Font(name="微软雅黑", size=16, bold=True)
    tc.alignment = _CENTER
    ws.row_dimensions[1].height = 35

    for i, h in enumerate(EXPORT_HEADERS, start=1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = Font(name="微软雅黑", bold=True)
        c.alignment = _CENTER
        c.border = _BORDER
        c.fill = _HEADER_FILL
    ws.row_dimensions[2].height = 25

    money_keys = ["noil", "weixiu", "baoxian", "gaosu", "tingche", "xiche", "ye"]
    r = 3
    for idx, row in enumerate(rows, start=1):
        values = [idx, row.get("chehao") or ""] + [row.get(k) or 0 for k in money_keys] + [""]
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.alignment = _CENTER
            c.border = _BORDER
        ws.row_dimensions[r].height = 20
        r += 1

    values = ["合计", ""] + [footer.get(k) or 0 for k in money_keys] + [""]
    for i, v in enumerate(values, start=1):
        c = ws.cell(row=r, column=i, value=v)
        c.alignment = _CENTER
        c.border = _BORDER
        c.fill = _TOTAL_FILL
        c.font = Font(bold=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    ws.row_dimensions[r].height = 25

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
