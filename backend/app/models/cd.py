"""传导完好率分组 4 模块模型(表名/字段沿用旧库 db_plan.dbo.CD_*)。

- 传导完好率 CD_whl:每月 25 日按部门生成的汇总报表(生成报表 tjbb 的产物)
- 传导故障 CD_gz:故障明细,decgztss(故障台时数)由 dects 汇总
- 传导大修 CD_daxiu:设备大修/更新记录,支持 Excel 导出
- 传导变动表 CD_xz:新增/报废/调出/停用设备明细,支持 Excel 模板导入

四张表的 bmid 均为旧 bb_bumen.id,导入时按 migration_reports/department_map.json
的 bmid_map 重映射到新 departments.id;username 是中文姓名文本(照旧用于本人判定)。
锁定开关复用年度计划模块的 consol_tb,conName='锁定传导报表'。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Index, Integer, Numeric, String

from app.db.session import Base


def _d(value):
    """date/datetime → yyyy-MM-dd(旧页面 pattern 格式)。"""
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if isinstance(value, Decimal) else value


class CDWhl(Base):
    """传导设备完好率月报表(旧 CD_whl,184 行)。

    ts=设备台数,sytss=实有台时数,decgztss/decwhtss=故障/完好台时数(小数),
    whl=完好率%,xzts/bfts/dcts/tyts=本月新增/报废/调出/停用台数。
    历史 gztss/whtss 是早期整数列,已停用但数据保留。
    """

    __tablename__ = "CD_whl"
    __table_args__ = (
        Index("ix_cdwhl_bbdate", "bbdate"),
        Index("ix_cdwhl_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bmid = Column(Integer, comment="部门 departments.id")
    ts = Column(Integer, comment="设备台数")
    sytss = Column(Integer, comment="实有台时数")
    gztss = Column(Integer, comment="旧故障台时数(已停用)")
    whtss = Column(Integer, comment="旧完好台时数(已停用)")
    whl = Column(Numeric(18, 2), comment="设备完好率%")
    bbdate = Column(Date, comment="报表日期,每月25日")
    xzts = Column(Integer, comment="本月新增设备台数")
    bfts = Column(Integer, comment="本月报废设备台数")
    dcts = Column(Integer, comment="本月调出设备台数")
    tyts = Column(Integer, comment="本月停用设备台数")
    bz = Column(String(250), comment="备注")
    adddate = Column(DateTime, comment="生成时间")
    finadate = Column(DateTime, comment="最后操作时间")
    username = Column(String(20), comment="操作员中文姓名")
    decgztss = Column(Numeric(18, 2), comment="故障台时数")
    decwhtss = Column(Numeric(18, 2), comment="完好台时数")


class CDGz(Base):
    """传导设备故障明细(旧 CD_gz,3132 行)。"""

    __tablename__ = "CD_gz"
    __table_args__ = (
        Index("ix_cdgz_bbdate", "bbdate"),
        Index("ix_cdgz_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bmid = Column(Integer, comment="部门 departments.id")
    sbname = Column(String(50), comment="设备名称")
    guanjing = Column(String(50), comment="管径")
    guancai = Column(String(50), comment="管材")
    didian = Column(String(250), comment="故障地点")
    ksdate = Column(Date, comment="故障开始日期")
    jsdate = Column(Date, comment="故障结束日期")
    yy = Column(String(50), comment="故障原因")
    ts = Column(Integer, comment="旧故障时数(已停用)")
    bz = Column(String(50), comment="备注是否停水")
    bbdate = Column(Date, comment="报表日期,每月25日")
    adddate = Column(DateTime, comment="录入时间")
    finadate = Column(DateTime, comment="最后操作时间")
    username = Column(String(20), comment="操作员中文姓名")
    dects = Column(Numeric(18, 2), comment="故障台时数")


class CDDaxiu(Base):
    """传导设备大修/更新记录(旧 CD_daxiu,410 行)。"""

    __tablename__ = "CD_daxiu"
    __table_args__ = (
        Index("ix_cddaxiu_bbdate", "bbdate"),
        Index("ix_cddaxiu_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bbdate = Column(Date, comment="报表日期,每月25日")
    daxiudate = Column(Date, comment="大修日期")
    lb = Column(String(50), comment="大修/更新类别")
    nr = Column(String(250), comment="项目内容(更新、大修地点)")
    gdh = Column(String(50), comment="工单号")
    gdkj = Column(String(50), comment="管道口径")
    xbqkj = Column(String(50), comment="修补器口径")
    fmkj = Column(String(50), comment="阀门口径")
    xfskj = Column(String(50), comment="消防栓口径")
    num = Column(Integer, comment="数量")
    bz = Column(String(150), comment="外力损坏")
    cfd = Column(String(50), comment="其他存放点")
    sgy = Column(String(50), comment="施工员")
    sgtel = Column(String(50), comment="施工电话")
    bmid = Column(Integer, comment="部门 departments.id")
    adddate = Column(DateTime, comment="录入时间")
    finadate = Column(DateTime, comment="最后操作时间")
    username = Column(String(20), comment="操作员中文姓名")


class CDXz(Base):
    """传导设备变动明细(旧 CD_xz,1355 行)。"""

    __tablename__ = "CD_xz"
    __table_args__ = (
        Index("ix_cdxz_bbdate", "bbdate"),
        Index("ix_cdxz_bmid", "bmid"),
        Index("ix_cdxz_bdlb", "bdlb"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sbname = Column(String(500), comment="设备名称/明细")
    bmid = Column(Integer, comment="部门 departments.id")
    bbdate = Column(Date, comment="报表日期,每月25日")
    bdlb = Column(String(50), comment="变动类别:新增/报废/调出/停用设备")
    adddate = Column(DateTime, comment="录入时间")
    finadate = Column(DateTime, comment="最后操作时间")
    username = Column(String(20), comment="操作员中文姓名")
