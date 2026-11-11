"""财务管理三模块模型(表名/字段沿用旧库 db_plan.dbo.*,见 docs/数据迁移约定.md)。

- 固定资产 gdzc:zc_cw(按年度的资产快照) + zc_lb(类别) + zc_nd(年度字典,旧页面未用)
- 清理报告 baofeizc:zc_baofeidan(报废单) + zc_baofeitp(单据图片);
  报废明细没有独立表,直接把 zc_cw.baofeidanid 挂到单据上
- 物资采购申请 wzcgsq:wzcgsq(主表) + wzcgsq_mx(明细)

⚠️ 旧库 bmid 是 bb_bumen.id,与新 departments.id 不对应:导入脚本按
scripts/migration_reports/department_map.json 的 bmid_map 逐行重映射。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Index, Integer, Numeric, String

from app.db.session import Base


def _d(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if isinstance(value, Decimal) else value


class ZcLb(Base):
    """固定资产类别字典(旧 zc_lb,29 行)。"""

    __tablename__ = "zc_lb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lb = Column(String(50), comment="类别名称")


class ZcNd(Base):
    """旧 zc_nd 年度字典。旧 gdzc 页面实际用 zc_cw.nd 去重,此表是死表,仅随数据迁入。"""

    __tablename__ = "zc_nd"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nd = Column(Integer, nullable=False)


class ZcCw(Base):
    """固定资产台账 / 盘点明细 / 报废明细(旧 zc_cw,41383 行)。

    同一 zccode 在多个 nd(盘点年度)各有一行;报废时按 zccode 取最新年度行
    挂 baofeidanid,并把其它年度行标 baofeiqk='已报废'。
    """

    __tablename__ = "zc_cw"
    __table_args__ = (
        Index("ix_zccw_nd", "nd"),
        Index("ix_zccw_bmid", "bmid"),
        Index("ix_zccw_lbid", "lbid"),
        Index("ix_zccw_zccode", "zccode"),
        Index("ix_zccw_baofeidanid", "baofeidanid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lbid = Column(Integer, comment="资产类别 zc_lb.id")
    zccode = Column(String(50), comment="资产号")
    sbname = Column(String(200), comment="设备名称")
    num = Column(Integer, comment="数量")
    bmid = Column(Integer, comment="所属部门 departments.id(已重映射)")
    qyrq = Column(Date, nullable=False, comment="设备启用日期")
    yz = Column(Numeric(18, 4), comment="原值")
    jz = Column(Numeric(18, 4), comment="净值")
    didian = Column(String(200), comment="在用地点")
    nd = Column(Integer, comment="盘点年度")
    guige = Column(String(200), comment="规格型号")
    sbbh = Column(String(100), comment="设备编号")
    yujishiyong = Column(Integer, comment="预计使用期限(年)")
    yishiyong = Column(Integer, comment="已使用(年)")
    beizhu = Column(String(500), comment="备注")
    beizhuren = Column(String(50), comment="备注/最近操作登记人")
    bzdate = Column(DateTime, comment="备注/最近操作时间")
    pandian = Column(String(10), comment="盘点状态:NULL 未盘点 / 盘点")
    baofeidanid = Column(Integer, comment="报废单 zc_baofeidan.id")
    baofeiqk = Column(String(10), comment="报废情况:NULL / 已报废")
    baofeicztime = Column(DateTime, comment="报废操作时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "lbid": self.lbid, "zccode": self.zccode or "",
            "sbname": self.sbname or "", "num": self.num, "bmid": self.bmid,
            "qyrq": _d(self.qyrq), "yz": _n(self.yz), "jz": _n(self.jz),
            "didian": self.didian or "", "nd": self.nd,
            "guige": self.guige or "", "sbbh": self.sbbh or "",
            "yujishiyong": self.yujishiyong, "yishiyong": self.yishiyong,
            "beizhu": self.beizhu or "", "beizhuren": self.beizhuren or "",
            "bzdate": _dt(self.bzdate),
            "pandian": (self.pandian or "").strip() or None,
            "baofeidanid": self.baofeidanid,
            "baofeiqk": self.baofeiqk or "",
            "baofeicztime": _dt(self.baofeicztime),
        }


class ZcBaofeidan(Base):
    """资产清理(报废)报告单头(旧 zc_baofeidan,176 行)。"""

    __tablename__ = "zc_baofeidan"
    __table_args__ = (Index("ix_zcbfrq", "riqi"), Index("ix_zcbfbmid", "bmid"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    riqi = Column(Date, comment="报废单日期")
    bmid = Column(Integer, comment="报废部门 departments.id(已重映射)")
    caozuo = Column(String(15), comment="登记人")
    czriqi = Column(DateTime, comment="登记日期")
    zaiyao = Column(String(250), comment="摘要")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "riqi": _d(self.riqi), "bmid": self.bmid,
            "caozuo": self.caozuo or "", "czriqi": _dt(self.czriqi),
            "zaiyao": self.zaiyao or "",
        }


class ZcBaofeitp(Base):
    """报废单图片(旧 zc_baofeitp,208 行)。dizhi 是 /Upload/... 相对路径。"""

    __tablename__ = "zc_baofeitp"
    __table_args__ = (Index("ix_zcbftp_bfdid", "bfdid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    dizhi = Column(String(255), comment="图片相对路径")
    bfdid = Column(Integer, comment="报废单 id")


class Wzcgsq(Base):
    """物资采购申请单头(旧 wzcgsq)。

    bumen 是手填文本(打印信息行用),bmid/cj 取登录人部门(数据范围用),
    两者可能不一致,照旧保留双轨。
    """

    __tablename__ = "wzcgsq"
    __table_args__ = (Index("ix_wzcgsq_cj", "cj"), Index("ix_wzcgsq_djriqi", "djriqi"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    bumen = Column(String(50), nullable=False, comment="申请部门(手填文本留痕)")
    sgyy = Column(String(200), comment="申购原因")
    hj = Column(Numeric(18, 2), nullable=False, default=0, comment="合计金额")
    cj = Column(String(50), comment="旧部门层级码前缀(数据范围)")
    djriqi = Column(DateTime, comment="登记日期")
    username = Column(String(50), comment="录入人姓名")
    userid = Column(Integer, comment="录入人 users.id(已重映射)")
    bmid = Column(Integer, comment="录入部门 departments.id(已重映射)")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "bumen": self.bumen or "", "sgyy": self.sgyy or "",
            "hj": _n(self.hj), "cj": self.cj or "", "djriqi": _dt(self.djriqi),
            "username": self.username or "", "userid": self.userid, "bmid": self.bmid,
        }


class WzcgsqMx(Base):
    """物资采购申请明细(旧 wzcgsq_mx)。xiaoji 由服务端 Math.Round(数量*单价,2) 重算。"""

    __tablename__ = "wzcgsq_mx"
    __table_args__ = (Index("ix_wzcgsqmx_mainid", "mainid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    mainid = Column(Integer, nullable=False, comment="主表 wzcgsq.id")
    wpmc = Column(String(100), nullable=False, comment="物品名称")
    ggxh = Column(String(100), comment="规格、型号")
    danwei = Column(String(20), comment="单位")
    shuliang = Column(Numeric(18, 2), nullable=False, default=0)
    danjia = Column(Numeric(18, 2), nullable=False, default=0)
    xiaoji = Column(Numeric(18, 2), nullable=False, default=0)
    ysqk = Column(String(20), nullable=False, default="完成", comment="验收情况")
    beizhu = Column(String(200), comment="备注")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "mainid": self.mainid, "wpmc": self.wpmc or "",
            "ggxh": self.ggxh or "", "danwei": self.danwei or "",
            "shuliang": _n(self.shuliang), "danjia": _n(self.danjia),
            "xiaoji": _n(self.xiaoji), "ysqk": self.ysqk or "完成",
            "beizhu": self.beizhu or "",
        }
