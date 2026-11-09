"""工单领料 WorkOrder 模块新增表(照旧 db_plan 复刻)。

已有表复用,勿重复声明:
- app/models/material.py 的 WorkOrder / MaterialRecord / MaterialLibrary
  (work_order 10976 行、material_record 31194 行已由 import_materials.py 迁移)
- app/models/road_repair.py 的 Qiangxiurenyuan(班组下拉 14 行,已由 import_roadrepair.py 迁移)

本文件新增:
- gongdancailiao       工单材料登记(旧 19689 行)。旧 WorkOrder 列表的「已领用 IsUsed」
                       由 `EXISTS(gongdanhao == WorkOrderNo)` 动态计算,WorkOrder.IsUsed 是死列。
                       整表导入只为还原该判定,后续 Gongdan 模块复刻时直接复用,勿重导。
- work_order_attachment 工单附件(旧库 0 条,新上传写入 ~/Uploads/WorkOrderAttachments/yyyyMM/)
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.db.session import Base


class GongdanCailiao(Base):
    """旧 gongdancailiao:工单材料登记(只读用于 IsUsed 判定)。"""

    __tablename__ = "gongdancailiao"
    __table_args__ = (Index("ix_gdc_gongdanhao", "gongdanhao"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    ksriqi = Column(DateTime, comment="开始日期")
    jsriqi = Column(DateTime, comment="结束日期")
    shijian = Column(Integer, comment="时长(分钟)")
    dizhi = Column(String(150), comment="地址")
    neirong = Column(String(50), comment="内容")
    caizhi = Column(String(50), comment="材质")
    guanjing = Column(String(50), comment="管径")
    gongdanhao = Column(String(50), comment="工单号 -> work_order.work_order_no")
    tingshui = Column(String(50), comment="停水")
    shuiliang = Column(Integer, comment="水量")
    cailiao = Column(Text, comment="材料文本")
    shuliang = Column(String(50), comment="数量文本")
    qiangxiurenyuan = Column(String(50), comment="抢修班组")
    djriqi = Column(DateTime, comment="登记日期")
    zuihouriqi = Column(DateTime, comment="最后日期")
    djren = Column(String(50), comment="登记人")
    pipesize = Column(Integer, comment="管径数字")
    beizhu = Column(String(500), comment="备注")
    bmid = Column(Integer, nullable=True, comment="部门 id -> departments.id")


class WorkOrderAttachment(Base):
    """旧 WorkOrder_attachment:工单附件(旧库无历史数据)。"""

    __tablename__ = "work_order_attachment"
    __table_args__ = (Index("ix_woatt_order", "workorderid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workorderid = Column(Integer, nullable=False, comment="工单 id -> work_order.id")
    filename = Column(String(255), default="", comment="原始文件名")
    filepath = Column(String(500), default="", comment="相对 UPLOAD_DIR 的存储路径")
    filesize = Column(Integer, nullable=True, comment="字节数")
    uploadtime = Column(DateTime, default=datetime.now, comment="上传时间")
    operator_name = Column(String(50), default="", comment="上传人(仅本人可删)")

    def to_dict(self, can_delete: bool = False, token: str = "") -> dict:
        size = int(self.filesize or 0)
        if size < 1024:
            size_str = f"{size} B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / 1024 / 1024:.1f} MB"
        return {
            "id": self.id,
            "filename": self.filename or "",
            "fileSize": size,
            "fileSizeStr": size_str,
            "uploadTime": self.uploadtime.strftime("%Y-%m-%d %H:%M:%S") if self.uploadtime else "",
            "operator_name": self.operator_name or "",
            "canDelete": can_delete,
            "downloadUrl": f"/api/workorder/attachments/download?token={token}" if token else "",
        }
