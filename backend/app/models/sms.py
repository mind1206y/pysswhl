"""短信模块数据模型(照旧 db_plan.dbo.SmsRecord)。

SmsRecord 记录每次短信发送的内容/接收人/网关返回,供追溯。
SmsContact 是旧 bb_user 的联系人快照:新系统 users 是重建的,
历史计划里的专管员/发起人多数没有新账号,发送短信时按姓名回退查这里。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.db.session import Base


class SmsRecord(Base):
    __tablename__ = "sms_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lb = Column(String(50), comment="短信类别")
    riqi = Column(DateTime, default=datetime.now, index=True, comment="发送时间")
    nr = Column(String(500), comment="短信内容")
    tel = Column(String(20), comment="接收手机号")
    ren = Column(String(50), comment="接收人姓名")
    zt = Column(String(310), comment="网关返回/失败原因")
    sender = Column(String(50), comment="发送人")

    def to_dict(self):
        return {
            "id": self.id,
            "lb": self.lb or "",
            "riqi": self.riqi.strftime("%Y-%m-%d %H:%M:%S") if self.riqi else "",
            "nr": self.nr or "",
            "tel": self.tel or "",
            "ren": self.ren or "",
            "zt": self.zt or "",
            "sender": self.sender or "",
        }


class SmsContact(Base):
    """旧 bb_user 联系人目录,保留旧主键 id。"""

    __tablename__ = "sms_contact"

    id = Column(Integer, primary_key=True, autoincrement=False, comment="旧 bb_user.id")
    username = Column(String(50), index=True, comment="旧登录名(计划里保存的姓名快照)")
    real_name = Column(String(50), index=True, comment="旧 bb_user.unames")
    phone = Column(String(20), comment="手机号")
    zw = Column(String(50), comment="职务")
    otherqx = Column(String(200), comment="旧系统其他权限标签")
