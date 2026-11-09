"""SIM 卡管理模型(表名/字段沿用旧库 db_plan,照旧 simkaguanliController)。

- sim            主表(卡号台账),delf=1 正常 / 0 已软删除(删除时卡号追加 _X)
- sim_edit_log   字段级修改日志(旧系统 EditLogHelper.CompareAndLog)
- sim_taocan     套餐字典
- sim_vpn        VPN 字典
- sim_wangluo    运营商网络字典
- sim_zhuangtai  使用状态字典
- feiyong        月度话费(旧系统 simFeiyong 模块共用;SIM 卡列表展开子表展示)
- linshi         旧系统上传核对时用的临时表(保留建表,新核对逻辑不再依赖)
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, SmallInteger, String, Text

from app.db.session import Base


def _d(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if value is not None else None


def _blank_nulls(d: dict, keys) -> dict:
    for k in keys:
        if d.get(k) is None:
            d[k] = ""
    return d


SIM_TEXT_FIELDS = [
    "kahao", "xuliehao", "imhao", "ip", "vpn", "taocan", "zt", "yongtu",
    "didian", "wangluo", "bz", "dengjiren", "bianjiren", "glren", "syren",
    "zhanghu",
]


class SimCard(Base):
    """SIM 卡台账(旧库 sim)。bm 关联新库 departments.id(旧库 bb_bumen.id 已重映射)。"""

    __tablename__ = "sim"
    __table_args__ = (
        Index("ix_sim_kahao", "kahao"),
        Index("ix_sim_bm", "bm"),
        Index("ix_sim_delf", "delf"),
        Index("ix_sim_zhriqi", "zhriqi"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kahao = Column(String(150), default="", comment="卡号")
    xuliehao = Column(String(150), default="", comment="序列号")
    imhao = Column(String(150), default="", comment="IM号")
    ip = Column(String(150), default="", comment="IP")
    vpn = Column(String(150), default="", comment="VPN")
    taocan = Column(String(150), default="", comment="套餐")
    zt = Column(String(150), default="", comment="使用状态")
    yongtu = Column(String(350), default="", comment="用途")
    didian = Column(String(550), default="", comment="地点")
    wangluo = Column(String(120), default="", comment="运营商网络")
    bz = Column(String(450), default="", comment="备注")
    dengjiren = Column(String(120), default="", comment="登记人")
    djriqi = Column(DateTime, nullable=True, comment="登记时间")
    zhriqi = Column(DateTime, nullable=True, comment="最后修改时间")
    bianjiren = Column(String(120), default="", comment="最后编辑人")
    bm = Column(Integer, nullable=True, comment="部门id(新库 departments.id)")
    glren = Column(String(120), default="", comment="管理人")
    syren = Column(String(120), default="", comment="使用人")
    delf = Column(SmallInteger, default=1, nullable=False, comment="1正常 0软删除")
    zhanghu = Column(String(150), default="", comment="账户")

    def to_dict(self, dept_name: str = ""):
        return _blank_nulls({
            "ID": self.id, "id": self.id,
            "kahao": self.kahao, "xuliehao": self.xuliehao, "imhao": self.imhao,
            "ip": self.ip, "vpn": self.vpn, "taocan": self.taocan, "zt": self.zt,
            "yongtu": self.yongtu, "didian": self.didian, "wangluo": self.wangluo,
            "bz": self.bz, "dengjiren": self.dengjiren,
            "djriqi": _dt(self.djriqi), "zhriqi": _dt(self.zhriqi),
            "bianjiren": self.bianjiren, "bm": self.bm, "bumen": dept_name,
            "glren": self.glren, "syren": self.syren, "delf": self.delf,
            "zhanghu": self.zhanghu,
        }, SIM_TEXT_FIELDS)


class SimEditLog(Base):
    """SIM 卡字段修改日志(旧库 sim_edit_log)。field_name 存英文字段名,展示时转中文。"""

    __tablename__ = "sim_edit_log"
    __table_args__ = (Index("ix_simlog_sim_id", "sim_id"), Index("ix_simlog_edit_time", "edit_time"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    sim_id = Column(BigInteger, nullable=False, comment="SIM 卡 id")
    field_name = Column(String(50), default="", comment="字段名")
    old_value = Column(Text, nullable=True, comment="旧值")
    new_value = Column(Text, nullable=True, comment="新值")
    edit_user = Column(String(50), default="", comment="操作人")
    edit_time = Column(DateTime, nullable=True, comment="操作时间")
    edit_type = Column(String(20), default="", comment="操作类型:edit")

    def to_dict(self):
        return {
            "id": self.id, "sim_id": self.sim_id,
            "field_name": self.field_name or "",
            "old_value": self.old_value or "",
            "new_value": self.new_value or "",
            "edit_user": self.edit_user or "",
            "edit_time": self.edit_time,
            "edit_time_text": _dt(self.edit_time) or "",
            "edit_type": self.edit_type or "",
        }


class SimTaocan(Base):
    """套餐字典(旧库 sim_taocan)。"""

    __tablename__ = "sim_taocan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    taocan = Column(String(50), default="", comment="套餐名称")

    def to_dict(self):
        return {"id": self.id, "taocan": self.taocan or ""}


class SimVpn(Base):
    """VPN 字典(旧库 sim_vpn)。"""

    __tablename__ = "sim_vpn"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vpn = Column(String(50), default="", comment="VPN")

    def to_dict(self):
        return {"id": self.id, "vpn": self.vpn or ""}


class SimWangluo(Base):
    """运营商网络字典(旧库 sim_wangluo)。"""

    __tablename__ = "sim_wangluo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wangluo = Column(String(50), default="", comment="运营商网络")

    def to_dict(self):
        return {"id": self.id, "wangluo": self.wangluo or ""}


class SimZhuangtai(Base):
    """使用状态字典(旧库 sim_zhuangtai)。"""

    __tablename__ = "sim_zhuangtai"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zhuangtai = Column(String(50), default="", comment="使用状态")

    def to_dict(self):
        return {"id": self.id, "zhuangtai": self.zhuangtai or ""}


class Feiyong(Base):
    """月度话费(旧库 feiyong)。jine 保留旧库 money 4 位小数。"""

    __tablename__ = "feiyong"
    __table_args__ = (
        Index("ix_feiyong_kahao", "kahao"),
        Index("ix_feiyong_nian_yue", "nian", "yue"),
        Index("ix_feiyong_bm", "bm"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kahao = Column(String(50), default="", comment="卡号")
    jine = Column(Numeric(19, 4), nullable=True, comment="话费金额")
    nian = Column(Integer, nullable=True, comment="年度")
    yue = Column(Integer, nullable=True, comment="月份")
    syren = Column(String(20), default="", comment="使用人/录入人")
    bm = Column(Integer, nullable=True, comment="部门id(新库 departments.id)")
    bz = Column(String(250), default="", comment="备注")

    def to_dict(self):
        return {
            "id": self.id, "kahao": self.kahao or "", "jine": _n(self.jine),
            "nian": self.nian, "yue": self.yue, "syren": self.syren or "",
            "bm": self.bm, "bz": self.bz or "",
        }


class Linshi(Base):
    """旧系统上传核对时写入的临时卡号表(旧库 linshi)。保留建表以兼容历史数据。"""

    __tablename__ = "linshi"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kahao = Column(String(50), default="", comment="卡号")
    op = Column(Integer, nullable=True, comment="操作人id")
