"""领料结算(照旧 whl.Model jiesuancailiao / jiesuandetail / cailiao_fujian 复刻)。

旧表名与字段名沿用(SQL Server 驼峰 -> MySQL 小写下划线):
- jiesuancailiao   结算单主表(单号/供应商/结算日期/总额/审核状态/创建人/部门/备注)
- jiesuandetail    结算明细(结算单 id + 领料明细 id + 数量/单价/金额)
- cailiao_fujian   结算单附件(旧文件在旧生产服务器 Uploads/Jiesuan/,新库仅保留记录)

金额一律 Numeric(18,4),照旧 money 类型保留 4 位小数。
"""

from sqlalchemy import Column, DateTime, Index, Integer, Numeric, String

from app.db.session import Base


def _s(v):
    return "" if v is None else str(v)


def _r4(v):
    return None if v is None else round(float(v), 4)


class JiesuanCailiao(Base):
    __tablename__ = "jiesuancailiao"
    __table_args__ = (
        Index("ix_jsd_danno", "jiesuandanno"),
        Index("ix_jsd_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    jiesuandanno = Column(String(50), default="", comment="结算单号 JSyyyyMMddHHmmss")
    gongyingshang = Column(String(150), default="", comment="供应商")
    jiesuanriqi = Column(DateTime, comment="结算日期")
    zonge = Column(Numeric(18, 4), comment="结算总额(按明细自动汇总)")
    shzt = Column(Integer, nullable=True, comment="审核状态(旧系统未使用)")
    shriqi = Column(DateTime, comment="最后操作日期")
    shren = Column(String(50), default="", comment="审核人(旧系统未使用)")
    createuser = Column(String(50), default="", comment="创建人(登录名)")
    bmid = Column(Integer, nullable=True, comment="部门 id -> departments.id")
    beizhu = Column(String(850), default="", comment="备注")

    def to_dict(self, fujian_count: int = 0) -> dict:
        return {
            "id": self.id,
            "jiesuandanno": _s(self.jiesuandanno),
            "gongyingshang": _s(self.gongyingshang),
            "jiesuanriqi": self.jiesuanriqi.strftime("%Y-%m-%d") if self.jiesuanriqi else "",
            "zonge": _r4(self.zonge) or 0.0,
            "createuser": _s(self.createuser),
            "beizhu": _s(self.beizhu),
            "shriqi": self.shriqi.strftime("%Y-%m-%d %H:%M:%S") if self.shriqi else "",
            "fujianCount": fujian_count,
            "bmid": self.bmid,
        }


class JiesuanDetail(Base):
    __tablename__ = "jiesuandetail"
    __table_args__ = (
        Index("ix_jsdd_jiesuanid", "jiesuanid"),
        Index("ix_jsdd_lingliaodetailid", "lingliaodetailid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    jiesuanid = Column(Integer, nullable=True, comment="结算单 id -> jiesuancailiao.id")
    lingliaodetailid = Column(Integer, nullable=True, comment="领料明细 id -> lingliaodetail.id")
    num = Column(Numeric(18, 4), comment="结算数量")
    danjia = Column(Numeric(18, 4), comment="单价")
    jine = Column(Numeric(18, 4), comment="金额 = num * danjia")


class CailiaoFujian(Base):
    __tablename__ = "cailiao_fujian"
    __table_args__ = (Index("ix_cf_jiesuanid", "jiesuancailiao_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    jiesuancailiao_id = Column(Integer, nullable=False, comment="结算单 id -> jiesuancailiao.id")
    filename = Column(String(200), nullable=False, default="", comment="原始文件名")
    filepath = Column(String(500), nullable=False, default="", comment="相对 UPLOAD_DIR 的路径")
    filesize = Column(Integer, nullable=True, comment="字节数")
    uploaduser = Column(String(50), default="", comment="上传人")
    uploadtime = Column(DateTime, comment="上传时间")
