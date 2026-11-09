from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)

from app.db.session import Base

# 工程状态枚举(沿用旧系统 db_plan 的取值)
STATUS_MAP = {
    0: "未开工",
    1: "施工中",
    2: "已敷设",
    3: "已试压",
    4: "已通水",
    5: "已验收",
    6: "已移交",
    7: "已归档",
}


def _fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _fmt_date(value):
    return value.strftime("%Y-%m-%d") if value else None


class Gongchenggl(Base):
    """工程管理台账(表名/字段沿用旧库 db_plan.dbo.gongchenggl)。"""

    __tablename__ = "gongchenggl"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bmid = Column(Integer, nullable=True, comment="部门id(关联 departments 表;迁移时按旧 bb_bumen 部门名重映射)")
    pianqu = Column(String(100), default="", comment="片区")
    xiangmuname = Column(String(200), default="", comment="项目名称")
    xiangmudizhi = Column(String(300), default="", comment="项目地址")
    xiangmuyezhu = Column(String(100), default="", comment="项目业主")
    daijiandanwei = Column(String(200), default="", comment="代建单位")
    shejidanwei = Column(String(200), default="", comment="设计单位")
    jianlidanwei = Column(String(200), default="", comment="监理单位")
    shigongdanwei = Column(String(200), default="", comment="施工单位")
    lianxiren = Column(String(50), default="", comment="联系人")
    dianhua = Column(String(50), default="", comment="电话")
    shenbaoriqi = Column(DateTime, nullable=True, comment="申报日期")
    isyijiao = Column(Boolean, default=False, comment="是否已移交")
    yijiaoriqi = Column(DateTime, nullable=True, comment="移交日期")
    isguidang = Column(Boolean, default=False, comment="是否已归档")
    guidangriqi = Column(DateTime, nullable=True, comment="归档日期")
    CreateTime = Column(DateTime, default=datetime.now, comment="创建时间")
    CreateUser = Column(String(50), default="", comment="创建人")
    xmleibie = Column(String(100), default="", comment="项目类别")
    zijinleixing = Column(String(100), default="", comment="资金类型")
    Status = Column(Integer, default=0, comment="状态:0未开工 1施工中 2已敷设 3已试压 4已通水 5已验收 6已移交 7已归档")
    StatusRemark = Column(String(300), default="", comment="状态备注")
    LastUpdateTime = Column(DateTime, nullable=True, comment="最后更新时间")
    updateUser = Column(String(50), default="", comment="更新人")
    Remark = Column(Text, nullable=True, comment="备注")

    def to_dict(self):
        return {
            "id": self.id,
            "bmid": self.bmid,
            "pianqu": self.pianqu,
            "xiangmuname": self.xiangmuname,
            "xiangmudizhi": self.xiangmudizhi,
            "xiangmuyezhu": self.xiangmuyezhu,
            "daijiandanwei": self.daijiandanwei,
            "shejidanwei": self.shejidanwei,
            "jianlidanwei": self.jianlidanwei,
            "shigongdanwei": self.shigongdanwei,
            "lianxiren": self.lianxiren,
            "dianhua": self.dianhua,
            "shenbaoriqi": _fmt_date(self.shenbaoriqi),
            "isyijiao": self.isyijiao,
            "yijiaoriqi": _fmt_date(self.yijiaoriqi),
            "isguidang": self.isguidang,
            "guidangriqi": _fmt_date(self.guidangriqi),
            "CreateTime": _fmt(self.CreateTime),
            "CreateUser": self.CreateUser,
            "xmleibie": self.xmleibie,
            "zijinleixing": self.zijinleixing,
            "Status": self.Status,
            "status_name": STATUS_MAP.get(self.Status, str(self.Status)),
            "StatusRemark": self.StatusRemark,
            "LastUpdateTime": _fmt(self.LastUpdateTime),
            "updateUser": self.updateUser,
            "Remark": self.Remark,
        }


class GongchengglJindu(Base):
    """工程进度记录(表名/字段沿用旧库 db_plan.dbo.gongchenggl_jindu)。"""

    __tablename__ = "gongchenggl_jindu"
    __table_args__ = (Index("ix_jindu_gcglid", "gcglid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    gcglid = Column(Integer, nullable=True, comment="所属工程id,对应 gongchenggl.id")
    jindu = Column(Text, nullable=True, comment="进度描述")
    riqi = Column(DateTime, nullable=True, comment="记录日期")
    jinduzhuangtai = Column(Integer, nullable=True, comment="进度状态,0-7 同主表 Status 枚举")
    CreateUser = Column(String(50), default="", comment="创建人")
    UpdateUser = Column(String(50), default="", comment="更新人")
    UpdateTime = Column(DateTime, nullable=True, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "gcglid": self.gcglid,
            "jindu": self.jindu,
            "riqi": _fmt(self.riqi),
            "jinduzhuangtai": self.jinduzhuangtai,
            "status_name": STATUS_MAP.get(self.jinduzhuangtai, str(self.jinduzhuangtai)),
            "CreateUser": self.CreateUser,
            "UpdateUser": self.UpdateUser,
            "UpdateTime": _fmt(self.UpdateTime),
        }


class GongchengglJianguan(Base):
    """工程问题监管记录(沿用旧库 gongchenggl_jianguan;chulshuoming 旧系统已废弃,仅保留列)。"""

    __tablename__ = "gongchenggl_jianguan"
    __table_args__ = (Index("ix_jianguan_gcglid", "gcglid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    gcglid = Column(Integer, nullable=True, comment="所属工程id")
    qingkuangshuoming = Column(Text, nullable=True, comment="情况说明(问题)")
    riqi = Column(DateTime, nullable=True, comment="记录日期")
    chulshuoming = Column(Text, nullable=True, comment="处理说明(旧系统已废弃,未使用)")
    isjiejue = Column(Boolean, default=False, comment="是否解决")
    CreateUser = Column(String(50), default="", comment="创建人")
    UpdateUser = Column(String(50), default="", comment="更新人")
    UpdateTime = Column(DateTime, nullable=True, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "gcglid": self.gcglid,
            "qingkuangshuoming": self.qingkuangshuoming,
            "riqi": _fmt(self.riqi),
            "chulshuoming": self.chulshuoming,
            "isjiejue": self.isjiejue,
            "CreateUser": self.CreateUser,
            "UpdateUser": self.UpdateUser,
            "UpdateTime": _fmt(self.UpdateTime),
        }


class GongchengglFujian(Base):
    """工程附件(沿用旧库 gongchenggl_fujian;url 为新系统下载路径)。"""

    __tablename__ = "gongchenggl_fujian"
    __table_args__ = (Index("ix_fujian_gcglid", "gcglid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    gcglid = Column(Integer, nullable=True, comment="所属工程id")
    url = Column(String(300), default="", comment="存储路径(磁盘相对路径)")
    wjname = Column(String(300), default="", comment="原始文件名")
    size = Column(BigInteger, nullable=True, comment="文件大小(字节)")
    CreateTime = Column(DateTime, default=datetime.now, comment="上传时间")
    CreateUser = Column(String(50), default="", comment="上传人")

    def to_dict(self):
        return {
            "id": self.id,
            "gcglid": self.gcglid,
            "url": self.url,
            "wjname": self.wjname,
            "size": self.size,
            "CreateTime": _fmt(self.CreateTime),
            "CreateUser": self.CreateUser,
        }
