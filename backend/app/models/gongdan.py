"""工单信息录入 Gongdan 模块新增表(照旧 db_plan 复刻)。

已有表复用,勿重复声明、勿重导:
- app/models/workorder.py 的 GongdanCailiao(gongdancailiao 19689 行,本模块主表)
- app/models/road_repair.py 的 Qiangxiurenyuan(qiangxiurenyuan 14 行,抢修班组下拉)
- app/models/material.py 的 WorkOrder / MaterialRecord / MaterialLibrary(领料明细)

本文件新增 3 张表:
- gongdan               热线工单本地镜像(76870 行)。⛔与内网 flow 工单是两套数据,
                        仅用于旧 GetGongdanCount 的计数,不参与工单号带出/详情(口径不混用)
- gongdan_neirong_dict  工作内容字典(72 行,use_count 排序,前端可删选项)
- gongdan_caizhi_dict   材质字典(21 行,同上)
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.session import Base


class Gongdan(Base):
    """旧 gongdan:热线工单镜像表(只读,数据保全)。"""

    __tablename__ = "gongdan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gongdanid = Column(String(50), index=True, comment="工单号")
    chuangjiandanwei = Column(String(50), comment="创建单位")
    shouliren = Column(String(50), comment="受理人")
    diaodupingtai = Column(String(50), comment="调度平台")
    chuangjianriqi = Column(DateTime, comment="创建日期")
    laidianhao = Column(String(50), comment="来电号")
    lianxidianhua = Column(String(50), comment="联系电话")
    leixing = Column(String(50), comment="类型")
    zileixing = Column(String(50), comment="子类型")
    jinji = Column(String(50), comment="紧急程度")
    chuliren = Column(String(50), comment="处理人")
    dizhi = Column(String(150), comment="地址")
    yonghuhao = Column(String(50), comment="用户号")
    wentimiaoshu = Column(Text, comment="问题描述")
    laiyuan = Column(String(50), comment="来源")
    caozuoriqi = Column(DateTime, comment="操作日期")
    jindu = Column(String(50), comment="进度")
    cuibancishu = Column(String(50), comment="催办次数")
    zuihouneirong = Column(Text, comment="最后内容")
    jiedanfangshi = Column(String(50), comment="接单方式")
    jiedanren = Column(String(50), comment="接单人")
    jiedanbm = Column(String(250), comment="接单部门")
    zuihouriqi = Column(DateTime, comment="最后日期")
    pipesize = Column(Integer, comment="管径数字")


class GongdanNeirongDict(Base):
    """旧 gongdan_neirong_dict:工作内容下拉字典。"""

    __tablename__ = "gongdan_neirong_dict"

    id = Column(Integer, primary_key=True, autoincrement=True)
    neirong = Column(String(200), nullable=False, unique=True, comment="工作内容")
    use_count = Column(Integer, default=0, nullable=False, comment="使用次数")
    last_used_time = Column(DateTime, default=datetime.now, comment="最后使用时间")


class GongdanCaizhiDict(Base):
    """旧 gongdan_caizhi_dict:材质下拉字典。"""

    __tablename__ = "gongdan_caizhi_dict"

    id = Column(Integer, primary_key=True, autoincrement=True)
    caizhi = Column(String(100), nullable=False, unique=True, comment="材质")
    use_count = Column(Integer, default=0, nullable=False, comment="使用次数")
    last_used_time = Column(DateTime, default=datetime.now, comment="最后使用时间")
