"""路面修复管理(照旧 RoadRepairController / whl.Model/road_*.cs 1:1 复刻)。

旧库表名、字段名全部沿用,便于历史数据平移:
- road_repair            主表(道路维修记录)
- road_repair_progress   进度历史(每次状态变更插一条)
- road_price             路面类型价格字典(单位可空=通用)
- road_repair_attachment 附件记录(物理文件在旧生产服务器 ~/Uploads/Repair/)
- qiangxiurenyuan        强修人员(班组下拉,与工单模块共用字典,旧 Gongdanqiangxiurenyuan)

状态口径沿用旧值:新建 / 已报账 / 已付款 / 已完账(历史数据仅出现过 新建/已完账)。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String

from app.db.session import Base


def _s(v):
    return "" if v is None else v


def _dt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else None


def _d(v):
    return None if v is None else float(v)


class RoadRepair(Base):
    __tablename__ = "road_repair"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(200), comment="地址")
    dig_date = Column(DateTime, comment="开挖日期(旧库为 date)")
    road_type = Column(String(50), comment="道路类型")
    reason = Column(String(200), comment="维修原因")
    remark = Column(String(500), comment="备注")
    area = Column(Numeric(18, 3), comment="面积(㎡)")
    final_area = Column(Numeric(18, 3), comment="决算面积(㎡)")
    price = Column(Numeric(18, 2), comment="单价(元/㎡)")
    total = Column(Numeric(18, 2), comment="总额(元)")
    company = Column(String(50), comment="单位:大市政/湖里市政/思明市政/公路局")
    current_progress = Column(String(50), comment="当前状态:新建/已报账/已付款/已完账")
    operator_name = Column(String(50), comment="操作员")
    operate_time = Column(DateTime, comment="操作时间")
    banzu = Column(String(50), comment="班组(强修人员)")

    def to_dict(self):
        return {
            "id": self.id,
            "address": _s(self.address),
            "dig_date": self.dig_date.strftime("%Y-%m-%d") if self.dig_date else None,
            "road_type": _s(self.road_type),
            "reason": _s(self.reason),
            "remark": _s(self.remark),
            "area": _d(self.area),
            "final_area": _d(self.final_area),
            "price": _d(self.price),
            "total": _d(self.total),
            "company": _s(self.company),
            "current_progress": _s(self.current_progress),
            "operator_name": _s(self.operator_name),
            "operate_time": _dt(self.operate_time),
            "banzu": _s(self.banzu),
        }


class RoadRepairProgress(Base):
    __tablename__ = "road_repair_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repair_id = Column(Integer, index=True, comment="-> road_repair.id")
    progress = Column(String(50), comment="进度状态")
    progress_date = Column(DateTime, comment="进度日期")
    operator_name = Column(String(50), comment="操作人")

    def to_dict(self):
        return {
            "id": self.id,
            "repair_id": self.repair_id,
            "progress": _s(self.progress),
            "progress_date": _dt(self.progress_date),
            "operator_name": _s(self.operator_name),
        }


class RoadPrice(Base):
    __tablename__ = "road_price"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company = Column(String(50), comment="适用单位,空=通用")
    road_type = Column(String(50), comment="路面类型")
    price = Column(Numeric(18, 2), comment="单价(元)")
    operator_name = Column(String(50), comment="操作员")
    operate_time = Column(DateTime, comment="操作时间")

    def to_dict(self):
        return {
            "id": self.id,
            "company": _s(self.company),
            "road_type": _s(self.road_type),
            "price": _d(self.price),
            "operator_name": _s(self.operator_name),
            "operate_time": _dt(self.operate_time),
        }


class RoadRepairAttachment(Base):
    __tablename__ = "road_repair_attachment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repair_id = Column(Integer, index=True, comment="-> road_repair.id")
    file_name = Column(String(255), comment="原始文件名")
    file_path = Column(String(500), comment="存储相对路径(旧 ~/Uploads/Repair/...)")
    file_size = Column(Integer, comment="字节数")
    upload_time = Column(DateTime, comment="上传时间")
    operator_name = Column(String(50), comment="上传人")

    def to_dict(self):
        return {
            "id": self.id,
            "repair_id": self.repair_id,
            "file_name": _s(self.file_name),
            "file_path": _s(self.file_path),
            "file_size": self.file_size,
            "upload_time": _dt(self.upload_time),
            "operator_name": _s(self.operator_name),
        }


class Qiangxiurenyuan(Base):
    """强修人员字典(旧 Gongdanqiangxiurenyuan/GetList 数据源,工单模块共用)。"""

    __tablename__ = "qiangxiurenyuan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), comment="人员姓名(班组名)")
    bmid = Column(Integer, comment="部门 id -> departments.id")

    def to_dict(self):
        return {"id": self.id, "name": _s(self.name), "bmid": self.bmid}
