"""手机管理模型(照旧 shoujiController / shoujiService 复刻)。

表名/字段沿用旧库 db_plan.dbo.*:
- shouji            手机台账(编号 PDAxxx / 品牌 / 规格 / 启用日期 / 使用人 / 号码 / 状态 ...)
- shouji_attachment 附件(PDF/图片,物理文件在旧库 Uploads/ShoujiAttachments/<id>/)
- shouji_huishou    回收登记
- shouji_edit_log   字段级修改日志

编辑手机时按号码查卡信息,直接读 SIM 卡管理模块(app.models.simcard.SimCard)的 sim 表。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Index, Integer, Numeric, String

from app.db.session import Base
from app.models.simcard import SimCard as Sim


def _d(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if isinstance(value, Decimal) else value


def _blank_nulls(d: dict, keys) -> dict:
    for k in keys:
        if d.get(k) is None:
            d[k] = ""
    return d


SHOUJI_TEXT_FIELDS = [
    "bh", "pinpai", "guige", "caozuo", "shiyongren", "yongtu", "haoma",
    "huishouuser", "querenuser", "bz", "djuser", "zt", "liyou",
]


class Shouji(Base):
    """手机台账(旧库 shouji)。bmid 关联新库 departments.id。"""

    __tablename__ = "shouji"
    __table_args__ = (
        Index("ix_shouji_bmid", "bmid"),
        Index("ix_shouji_bh", "bh"),
        Index("ix_shouji_haoma", "haoma"),
        Index("ix_shouji_qiyongdate", "qiyongdate"),
        Index("ix_shouji_zt", "zt"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bh = Column(String(50), default="", comment="手机编号(PDAxxx)")
    pinpai = Column(String(50), default="", comment="品牌")
    guige = Column(String(100), default="", comment="规格")
    qiyongdate = Column(Date, nullable=True, comment="启用日期")
    jiage = Column(Numeric(18, 2), nullable=True, comment="价格")
    caozuotime = Column(DateTime, nullable=True, comment="最后编辑时间")
    caozuo = Column(String(50), default="", comment="最后编辑人")
    bmid = Column(Integer, nullable=True, comment="部门id(departments.id)")
    shiyongren = Column(String(50), default="", comment="使用人")
    yongtu = Column(String(50), default="", comment="用途")
    haoma = Column(String(50), default="", comment="号码(关联 sim.kahao)")
    huishoudate = Column(DateTime, nullable=True, comment="回收日期")
    huishouuser = Column(String(50), default="", comment="回收人")
    querendate = Column(DateTime, nullable=True, comment="确认报废日期")
    querenuser = Column(String(50), default="", comment="确认报废人")
    bz = Column(String(255), default="", comment="备注")
    djuser = Column(String(50), default="", comment="登记人")
    djtime = Column(DateTime, nullable=True, comment="登记时间")
    zt = Column(String(30), default="", comment="状态:正常使用/待领用/确认报废/已回收")
    liyou = Column(String(50), default="", comment="购置原因:新增/更新")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id,
            "bh": self.bh,
            "pinpai": self.pinpai,
            "guige": self.guige,
            "qiyongdate": _d(self.qiyongdate),
            "jiage": _n(self.jiage),
            "caozuotime": _dt(self.caozuotime),
            "caozuo": self.caozuo,
            "bmid": self.bmid,
            "shiyongren": self.shiyongren,
            "yongtu": self.yongtu,
            "haoma": self.haoma,
            "huishoudate": _dt(self.huishoudate),
            "huishouuser": self.huishouuser,
            "querendate": _dt(self.querendate),
            "querenuser": self.querenuser,
            "bz": self.bz,
            "djuser": self.djuser,
            "djtime": _dt(self.djtime),
            "zt": self.zt,
            "liyou": self.liyou,
        }, SHOUJI_TEXT_FIELDS)


class ShoujiAttachment(Base):
    """手机附件(旧库 shouji_attachment)。file_path 形如 ~/Uploads/ShoujiAttachments/<id>/<file>。"""

    __tablename__ = "shouji_attachment"
    __table_args__ = (Index("ix_shouji_att_sid", "shouji_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    shouji_id = Column(Integer, nullable=False, comment="手机id")
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_path = Column(String(500), nullable=False, comment="旧库相对路径")
    file_size = Column(Integer, nullable=True, comment="文件大小(字节)")
    upload_time = Column(DateTime, nullable=True, comment="上传时间")
    operator_name = Column(String(100), default="", comment="上传人")

    def to_dict(self):
        return {
            "id": self.id,
            "shouji_id": self.shouji_id,
            "file_name": self.file_name or "",
            "file_path": self.file_path or "",
            "file_size": self.file_size,
            "upload_time": _dt(self.upload_time),
            "operator_name": self.operator_name or "",
        }


class ShoujiHuishou(Base):
    """回收登记(旧库 shouji_huishou)。"""

    __tablename__ = "shouji_huishou"
    __table_args__ = (Index("ix_shouji_hs_bmid", "bmid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    huishoudate = Column(DateTime, nullable=True, comment="回收日期")
    bmid = Column(Integer, nullable=True, comment="营业所id(departments.id)")
    huishouren = Column(String(100), default="", comment="回收人")
    shuliang = Column(Integer, nullable=True, comment="数量")
    shuoming = Column(String(500), default="", comment="说明")
    djuser = Column(String(100), default="", comment="登记人")
    djtime = Column(DateTime, nullable=True, comment="登记时间")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id,
            "huishoudate": _dt(self.huishoudate),
            "bmid": self.bmid,
            "huishouren": self.huishouren,
            "shuliang": self.shuliang,
            "shuoming": self.shuoming,
            "djuser": self.djuser,
            "djtime": _dt(self.djtime),
        }, ["huishouren", "shuoming", "djuser"])


class ShoujiEditLog(Base):
    """字段级修改日志(旧库 shouji_edit_log)。field_name 存实体字段名。"""

    __tablename__ = "shouji_edit_log"
    __table_args__ = (Index("ix_shouji_log_sid", "shouji_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    shouji_id = Column(Integer, nullable=False, comment="手机id")
    field_name = Column(String(200), nullable=False, comment="字段名")
    old_value = Column(String(1000), default="", comment="旧值")
    new_value = Column(String(1000), default="", comment="新值")
    edit_user = Column(String(100), default="", comment="操作人")
    edit_time = Column(DateTime, nullable=True, comment="操作时间")
    edit_type = Column(String(50), default="edit", comment="操作类型")
