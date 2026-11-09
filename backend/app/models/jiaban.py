"""维抢修加班 Jiaban 模块 3 张表(照旧 db_plan 复刻,列名与旧库一一对应便于迁移)。

- jiaban             加班记录(3095 行),按人员(nameid→jiabanrenyuan.id)挂账
- jiabanrenyuan      加班人员(51 行),单价 danjia 用于工资汇总表
- jiaban_attachment  加班附件(508 行,按年月归档;旧服务器文件本机缺失,下载走 404 提示)

外部工单信息不落库:工单号带出/详情走 app/services/workorder_external.py(与
jcxt/gongdan/workorder 同源);工单历史记录复用 models/workorder.py 的 GongdanCailiao。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String

from app.db.session import Base


class Jiaban(Base):
    """旧 jiaban:维抢修加班记录。"""

    __tablename__ = "jiaban"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nameid = Column(Integer, index=True, nullable=False, comment="加班人员 jiabanrenyuan.id")
    riqi = Column(DateTime, comment="工单日期")
    gongdanNo = Column("gongdanNo", String(50), index=True, comment="工单号")
    kjshijian = Column(String(50), comment="起止时间文本,如 15:00-17:00")
    dizhi = Column(String(200), comment="地址")
    neirong = Column(String(500), comment="工作内容")
    shijian = Column(Numeric(18, 4), default=0, comment="加班时长(小时)")
    beishu = Column(Numeric(18, 4), default=0, comment="倍数")
    zongshu = Column(Numeric(18, 4), default=0, comment="总时长 = 时长 × 倍数")
    username = Column(String(50), comment="录入人(删除权限按此判断)")
    createtime = Column(DateTime, default=datetime.now, comment="创建时间")
    kstime = Column(DateTime, comment="开始时间(冲突检测用)")
    jstime = Column(DateTime, comment="结束时间(结束<=开始时按跨天+1天)")
    lei = Column(Integer, comment="1=以地址统计 0=非地址统计(旧 bit 可空)")


class JiabanRenyuan(Base):
    """旧 jiabanrenyuan:加班人员字典。"""

    __tablename__ = "jiabanrenyuan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, comment="姓名(全局查重)")
    bmlb = Column(String(50), nullable=False, comment="部门类别(自由文本,如 110联动队(1))")
    danjia = Column(Numeric(18, 4), default=0, comment="单价(元/工日)")
    gonghao = Column(String(50), comment="工号(导出给加班申请模块用)")


class JiabanAttachment(Base):
    """旧 jiaban_attachment:加班附件(按加班年月归档)。"""

    __tablename__ = "jiaban_attachment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jiabanDate = Column("jiabanDate", DateTime, comment="所属加班年月(取当月1日)")
    file_name = Column(String(200), comment="原始文件名")
    filePath = Column("filePath", String(300), comment="相对存储路径")
    fileSize = Column("fileSize", Integer, comment="字节数")
    uploadTime = Column("uploadTime", DateTime, default=datetime.now, comment="上传时间")
    operator_name = Column(String(50), comment="上传人(删除权限按此判断)")
