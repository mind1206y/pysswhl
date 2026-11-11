"""测漏成果汇总(照旧 CelouTbController / whl.Model/celouTb.cs 复刻)。

旧库表名、字段名、大小写全部沿用(便于历史数据平移与对照):
- celouTb: 测漏成果主表,旧库 21,398 行
- CLdui  : 测漏队伍字典,旧库 5 行

新增一列 bm:旧部门名(bb_bumen.bm)。bmid 迁移时按部门名重映射到新
departments.id,保留 bm 便于导出「经办部门」列与部门字典改名后回溯。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Index, Integer, Numeric, String
from app.db.session import Base


def _s(v):
    return "" if v is None else v


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _d(v):
    return v.isoformat() if isinstance(v, date) else None


def _dt(v):
    return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else None


class CelouTb(Base):
    __tablename__ = "celouTb"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    gongdan = Column(String(50), comment="派工单号(外部工单系统 ID)")
    bgdate = Column(Date, comment="漏点上报日期")
    xiufudate = Column(Date, comment="修复日期")
    didian = Column(String(250), comment="地点/地址")
    guanjing = Column(String(50), comment="管径(原始文本)")
    guancai = Column(String(50), comment="材质/管材")
    yy = Column(String(250), comment="漏水原因")
    dwwucha = Column(String(50), comment="定位误差")
    dingliang = Column(String(50), comment="定量方式")
    louliang = Column(Numeric(18, 2), comment="测定漏量(m³/h)")
    bmid = Column(Integer, index=True, comment="部门 id → departments.id")
    bm = Column(String(50), default="", comment="旧部门名保留")
    celoudw = Column(String(100), comment="测漏单位(CLdui.coname 文本)")
    nian = Column(Integer, index=True, comment="记录年度")
    yue = Column(Integer, comment="记录月份")
    scdatetime = Column(DateTime, comment="上传日期时间")
    username = Column(String(15), comment="上传人")
    bh = Column(Integer, comment="Excel 序号")
    gjsmall = Column(Integer, comment="管径数值(小)")
    gjbig = Column(Integer, comment="管径数值(大)")
    yudingliang = Column(Boolean, comment="是否预定量")
    zuobiao_leibie = Column(String(100), comment="坐标类别")
    zuobiao_jingdu = Column(Numeric(18, 10), comment="经度")
    zuobiao_weidu = Column(Numeric(18, 10), comment="纬度")
    xgusername = Column(String(15), default="", comment="坐标修改人")
    xgdatetime = Column(DateTime, comment="坐标修改时间")

    __table_args__ = (
        Index("ix_celouTb_nian_yue", "nian", "yue"),
        Index("ix_celouTb_gongdan", "gongdan"),
        Index("ix_celouTb_celoudw", "celoudw"),
        Index("ix_celouTb_gjsmall", "gjsmall"),
        Index("ix_celouTb_louliang", "louliang"),
    )

    def to_dict(self):
        """字段与旧 /CelouTb/gettable 的 rows 对齐(ID 大写、xsbm 由调用方注入)。"""
        return {
            "ID": self.id,
            "bh": self.bh,
            "gongdan": _s(self.gongdan),
            "bgdate": _d(self.bgdate),
            "xiufudate": _d(self.xiufudate),
            "nian": self.nian,
            "yue": self.yue,
            "yy": _s(self.yy),
            "scdatetime": _dt(self.scdatetime),
            "username": _s(self.username),
            "guancai": _s(self.guancai),
            "guanjing": _s(self.guanjing),
            "louliang": _f(self.louliang),
            "celoudw": _s(self.celoudw),
            "didian": _s(self.didian),
            "dingliang": _s(self.dingliang),
            "dwwucha": _s(self.dwwucha),
            "gjbig": self.gjbig,
            "gjsmall": self.gjsmall,
            "yudingliang": bool(self.yudingliang),
            "zuobiao_leibie": _s(self.zuobiao_leibie),
            "zuobiao_jingdu": _f(self.zuobiao_jingdu),
            "zuobiao_weidu": _f(self.zuobiao_weidu),
            "xgusername": _s(self.xgusername),
            "xgdatetime": _dt(self.xgdatetime),
            "bmid": self.bmid,
            "bm": _s(self.bm),
        }


class CLdui(Base):
    __tablename__ = "CLdui"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coname = Column(String(150), nullable=False, default="", comment="测漏单位名称")

    def to_dict(self):
        return {"id": self.id, "coname": _s(self.coname)}


EXPORT_COLUMNS = [
    "序号", "派工单号", "报告时间", "修复时间", "地点", "管径", "材质",
    "漏水原因", "定位误差", "定量方式", "测定漏量（m³/h）", "经办部门",
    "测漏队伍", "上传人", "年度", "月份", "年度节约水量(m³)",
    "坐标类型", "经度", "纬度", "计算过程",
]

# 导入模板表头(前 11 列严格相等,后 2 列包含关键字即可)
IMPORT_HEADERS = [
    "序号", "派工单号", "报告时间", "修复时间", "地点", "管径", "材质",
    "漏水原因", "定位误差", "定量方式", "测定漏量（m³/h）", "经度", "纬度",
]

# 导入 Excel 的 sheet 名 → 旧部门(迁移时按同名映射到新 departments.id)
IMPORT_SHEET_DEPTS = [
    "厦门营业所", "集美营业所", "杏林营业所", "海沧营业所", "同安营业所", "翔安营业所",
]

COORDINATE_TYPES = [
    {"value": "高德火星坐标", "label": "高德火星坐标 (GCJ-02)"},
    {"value": "WGS84", "label": "WGS84"},
    {"value": "百度坐标", "label": "百度坐标 (BD-09)"},
]
