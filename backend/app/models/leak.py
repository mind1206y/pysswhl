"""测漏笔记(照旧系统 LeakController / whl.Model/LeakRecord.cs、LeakFile.cs 复刻)。

旧库表名、字段名全部沿用,便于历史数据平移:
- LeakRecord: 测漏记录主表
- LeakFile  : 记录附件表(图片/视频/文档,ThumbUrl 存视频封面)
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, Index, Integer, Numeric, String

from app.db.session import Base


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def _dt(v):
    return v.isoformat(sep=" ", timespec="seconds") if isinstance(v, datetime) else None


def _d(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return v.isoformat() if isinstance(v, date) else None


class LeakRecord(Base):
    __tablename__ = "LeakRecord"

    id = Column("Id", Integer, primary_key=True, autoincrement=True)
    title = Column("Title", String(200), nullable=False, comment="测漏点名称")
    location = Column("Location", String(300), default="", comment="详细位置")
    pipeline_info = Column("PipelineInfo", String(500), default="", comment="管线信息")
    detect_time = Column("DetectTime", DateTime, index=True, comment="维修日期")
    detect_user = Column("DetectUser", String(100), default="", comment="测漏人")
    pressure = Column("Pressure", Numeric(18, 3), comment="压力(MPa)")
    area = Column("Area", Numeric(18, 2), comment="面积(cm2)")
    flow_rate = Column("FlowRate", Numeric(18, 2), comment="最终漏量(m3/h)")
    remark = Column("Remark", String(2000), default="", comment="备注")
    creator = Column("Creator", String(100), index=True, comment="记录人")
    create_time = Column("CreateTime", DateTime, default=datetime.now, comment="记录时间")
    area_expression = Column("AreaExpression", String(2000), default="", comment="计算公式")
    leak_method = Column("LeakMethod", String(30), default="coefficient", comment="计量方法")
    time1 = Column("Time1", Numeric(18, 2), comment="时间1(s)")
    time2 = Column("Time2", Numeric(18, 2), comment="时间2(s)")
    time3 = Column("Time3", Numeric(18, 2), comment="时间3(s)")
    avg_time = Column("AvgTime", Numeric(18, 2), comment="平均时间(s)")
    bucket_liters = Column("BucketLiters", Numeric(18, 2), comment="定量桶(L)")
    paicha = Column("paicha", String(50), default="", comment="旧字段")
    paicha_type = Column("PaichaType", String(50), default="", comment="排查类型")
    meter_time = Column("MeterTime", Numeric(18, 2), comment="计读时间(s)")
    meter_volume = Column("MeterVolume", Numeric(18, 3), comment="计读流量(m3)")
    experience_desc = Column("ExperienceDesc", String(2000), default="", comment="破口描述")
    experience_flow = Column("ExperienceFlow", Numeric(18, 2), comment="估量原始漏量(m3/h)")
    detect_com = Column("DetectCom", String(200), index=True, comment="测漏队伍")
    quantify_time = Column("QuantifyTime", String(10), default="", comment="定量时间(HH:MM)")
    flow_meta = Column("FlowMeta", String(1000), default="", comment="配合排查折算信息(JSON)")

    __table_args__ = (
        Index("ix_LeakRecord_creator_detect_time", "Creator", "DetectTime"),
        Index("ix_LeakRecord_detect_com", "DetectCom"),
    )

    def to_dict(self):
        """字段名与旧系统 /Leak/GetList、/Leak/GetDetail 返回保持一致。"""
        return {
            "Id": self.id,
            "Title": self.title or "",
            "Location": self.location or "",
            "PipelineInfo": self.pipeline_info or "",
            "DetectTime": _d(self.detect_time),
            "DetectUser": self.detect_user or "",
            "Pressure": _num(self.pressure),
            "Area": _num(self.area),
            "FlowRate": _num(self.flow_rate),
            "Remark": self.remark or "",
            "Creator": self.creator or "",
            "CreateTime": _dt(self.create_time),
            "AreaExpression": self.area_expression or "",
            "LeakMethod": self.leak_method or "",
            "Time1": _num(self.time1),
            "Time2": _num(self.time2),
            "Time3": _num(self.time3),
            "AvgTime": _num(self.avg_time),
            "BucketLiters": _num(self.bucket_liters),
            "paicha": self.paicha or "",
            "PaichaType": self.paicha_type or "",
            "MeterTime": _num(self.meter_time),
            "MeterVolume": _num(self.meter_volume),
            "ExperienceDesc": self.experience_desc or "",
            "ExperienceFlow": _num(self.experience_flow),
            "DetectCom": self.detect_com or "",
            "QuantifyTime": self.quantify_time or "",
            "FlowMeta": self.flow_meta or "",
        }


class LeakFile(Base):
    __tablename__ = "LeakFile"

    id = Column("Id", Integer, primary_key=True, autoincrement=True)
    leak_id = Column("LeakId", Integer, index=True, comment="测漏记录 id")
    file_type = Column("FileType", String(20), default="other", comment="image/video/pdf/word/excel/other")
    file_url = Column("FileUrl", String(500), comment="文件地址(本地相对路径或历史远程 URL)")
    file_name = Column("FileName", String(300), default="", comment="原始文件名")
    create_time = Column("CreateTime", DateTime, default=datetime.now)
    file_id = Column("FileId", Integer, comment="旧系统文件 id")
    thumb_url = Column("ThumbUrl", String(500), default="", comment="视频封面地址")

    __table_args__ = (Index("ix_LeakFile_leak_id", "LeakId"),)

    def to_dict(self):
        return {
            "Id": self.id,
            "LeakId": self.leak_id,
            "FileType": self.file_type or "other",
            "FileUrl": self.file_url or "",
            "FileName": self.file_name or "",
            "CreateTime": _dt(self.create_time),
            "FileId": self.file_id,
            "ThumbUrl": self.thumb_url or "",
        }
