"""IP 地址管理(照旧 ipadressController / whl.Model/ipadress.cs 复刻)。

旧库表名、字段名全部沿用,便于历史数据平移:
- ipadress      每个 IP 一条记录(同一网段固定 2~254 共 253 条)
- ip_net_creator 网段创建人元信息(旧系统后补表,历史数据可能全空)

状态口径沿用旧值:未使用 / 已使用。列表筛选「可领用」= 未使用,
「已占用」= 状态为空或不是未使用(照旧 FilterByZt)。
"""

from datetime import date, datetime

from sqlalchemy import Column, DateTime, Index, Integer, String

from app.db.session import Base


def _s(v):
    return "" if v is None else v


def _dt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return v.isoformat() if isinstance(v, date) else None


class Ipadress(Base):
    __tablename__ = "ipadress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    netname = Column(String(50), index=True, comment="网络名称")
    bmid = Column(Integer, index=True, comment="登记部门 id -> departments.id")
    sqren = Column(String(10), comment="申请人(最近一次领用人)")
    net = Column(String(50), comment="网段,如 192.168.1")
    numb = Column(Integer, comment="主机位 2~254")
    didian = Column(String(50), comment="位置")
    syren = Column(String(20), comment="使用人")
    yongtu = Column(String(50), comment="用途")
    zt = Column(String(20), index=True, comment="状态:未使用/已使用")
    sqdate = Column(DateTime, comment="申请/操作日期")
    netdate = Column(DateTime, comment="登记/系统日期")

    __table_args__ = (Index("ix_ipadress_netname_numb", "netname", "numb"),)

    def to_dict(self):
        return {
            "id": self.id,
            "ID": self.id,
            "netname": _s(self.netname),
            "bmid": self.bmid,
            "sqren": _s(self.sqren),
            "net": _s(self.net),
            "numb": self.numb,
            "didian": _s(self.didian),
            "syren": _s(self.syren),
            "yongtu": _s(self.yongtu),
            "zt": _s(self.zt),
            "sqdate": _dt(self.sqdate),
            "netdate": _dt(self.netdate),
        }


class IpNetCreator(Base):
    __tablename__ = "ip_net_creator"

    netname = Column(String(100), primary_key=True, comment="网络名称")
    creator = Column(String(50), comment="创建人")
    createtime = Column(DateTime, comment="创建时间")

    def to_dict(self):
        return {
            "netname": self.netname,
            "creator": _s(self.creator),
            "createtime": _dt(self.createtime),
        }
