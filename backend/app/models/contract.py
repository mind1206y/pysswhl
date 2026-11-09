"""合同登记/合同归集模型。表名、字段名沿用旧库 db_plan(ht_add / ht_tp / ht_zb_supplier)。

旧系统用户表没有导入,历史合同里的 djuser/spuserid 可能无法映射到新 users.id,
因此额外保留 djuser_name / spuserid_name 快照列,列表与筛选不依赖用户关联也能显示提交人。
"""

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, Numeric, String, Text

from app.db.session import Base


class HtAdd(Base):
    """合同主表(沿用旧库 ht_add)。"""

    __tablename__ = "ht_add"
    __table_args__ = (
        Index("ix_ht_add_djuser", "djuser"),
        Index("ix_ht_add_bumen_nd", "bumenid", "niandu"),
        Index("ix_ht_add_allbh", "allbh"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=True, comment="合同名称")
    nr = Column(Text, nullable=True, comment="简要内容")
    bz = Column(Text, nullable=True, comment="归集备注")
    djdate = Column(DateTime, nullable=True, comment="登记日期")
    editdate = Column(DateTime, nullable=True, comment="最后编辑日期")
    djuser = Column(Integer, nullable=True, comment="提交人 users.id(历史数据可能为空)")
    djuser_name = Column(String(50), default="", comment="提交人姓名快照(历史数据/新数据都写)")
    spuserid = Column(Integer, nullable=True, comment="归集人 users.id")
    spuserid_name = Column(String(50), default="", comment="归集人姓名快照")
    zt = Column(String(50), default="待归集", comment="归集状态:待归集/已归集")
    niandu = Column(Integer, nullable=True, comment="合同年度")
    bh = Column(Integer, nullable=True, comment="年度内序号")
    spdate = Column(DateTime, nullable=True, comment="归集日期")
    locked = Column(Integer, nullable=True, comment="非空=已锁定")
    jine = Column(Numeric(16, 2), nullable=True, comment="合同金额(元)")
    allbh = Column(String(50), nullable=True, comment="合同编号")
    leibie = Column(String(50), nullable=True, comment="合同类别")
    duixiang = Column(String(500), nullable=True, comment="签订对象")
    biaodi = Column(String(1000), nullable=True, comment="合同标的")
    zzdate = Column(DateTime, nullable=True, comment="终止时间")
    lvxingqingkuang = Column(String(50), nullable=True, comment="履行情况")
    jingbanren = Column(String(10), nullable=True, comment="经办人(存档)")
    qddate = Column(DateTime, nullable=True, comment="签订时间")
    ssdate = Column(DateTime, nullable=True, comment="实施时间")
    gjtime = Column(DateTime, nullable=True, comment="归集时间(存档)")
    bumenid = Column(Integer, nullable=True, comment="部门id(关联 departments)")
    beizhu = Column(String(1000), nullable=True, comment="备注描述")
    zhaobiaofangshi = Column(String(50), nullable=True, comment="招标方式")
    kongzhijia = Column(Numeric(16, 2), nullable=True, comment="控制价(元)")
    sfwjdw = Column(Boolean, nullable=True, comment="是否属于单次采购5-10万元(含)非直接采购项目")


class HtTp(Base):
    """合同附件(沿用旧库 ht_tp)。url 存 /Upload/htdjPDF/... 形式。"""

    __tablename__ = "ht_tp"
    __table_args__ = (Index("ix_ht_tp_htid", "htid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(255), nullable=True, comment="文件路径")
    htid = Column(Integer, nullable=True, comment="合同id")
    oldname = Column(String(250), nullable=True, comment="原文件名")
    fsize = Column(Numeric(16, 2), nullable=True, comment="文件大小(字节)")


class HtZbSupplier(Base):
    """招标供应商报价明细(沿用旧库 ht_zb_supplier)。"""

    __tablename__ = "ht_zb_supplier"
    __table_args__ = (Index("ix_ht_zb_supplier_htid", "htid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    htid = Column(Integer, nullable=True, comment="合同id")
    gongyingshang = Column(String(200), nullable=True, comment="供应商名称")
    toubiaojia = Column(Numeric(16, 2), nullable=True, comment="投标报价")
    zuizhongjia = Column(Numeric(16, 2), nullable=True, comment="最终出价")
    paixu = Column(Integer, nullable=True, comment="排序")
    sfzb = Column(Boolean, nullable=True, comment="是否中标")
    swfs = Column(Numeric(16, 2), nullable=True, comment="商务项分数")
    jsfs = Column(Numeric(16, 2), nullable=True, comment="技术项分数")
    jgfs = Column(Numeric(16, 2), nullable=True, comment="价格项分数")
    zfs = Column(Numeric(16, 2), nullable=True, comment="总分")
    beizhu = Column(String(500), nullable=True, comment="备注")
