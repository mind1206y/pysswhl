"""工单系统-材料库(照旧 MaterialLibraryController / whl.Model 复刻)。

旧库表名、字段名沿用(SQL Server 驼峰 -> MySQL 小写下划线),便于历史数据平移:
- material_library  材料库存主表(名称/规格/型号类别/库存数/预警数/大口径/别名)
- in_stock_record   入库/调整库存/盘点调整流水(lei 区分类型)
- material_record   工单领料出库明细(工单模块写入,本模块只读出库记录)
- material_image    材料图片(旧库 FilePath 形如 /Upload/MaterialImages/2026/03/xxx.jpg,
                    历史文件在旧生产服务器,缺文件时接口返回 404 提示)
- work_order        工单主表(出库记录关联工单号/创建人/备注;完整工单模块后续复刻共用此表)

库存数 num / 预警数 yujing 一律四舍五入保留 1 位小数(照旧 Math.Round(x,1))。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, Numeric, SmallInteger, String

from app.db.session import Base


def _s(v):
    return "" if v is None else v


def _r1(v):
    return None if v is None else round(float(v), 1)


class MaterialLibrary(Base):
    __tablename__ = "material_library"
    __table_args__ = (
        Index("ix_matlib_bmid", "bmid"),
        Index("ix_matlib_name", "material_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_name = Column(String(100), default="", comment="材料名称")
    spec = Column(String(100), default="", comment="规格")
    remark = Column(String(500), default="", comment="备注")
    num = Column(Numeric(18, 1), comment="库存数(1位小数)")
    unit = Column(String(20), default="", comment="单位")
    biaoji = Column(String(50), default="", comment="拼音首字母")
    yujing = Column(Numeric(18, 1), comment="预警数(库存低于它触发预警)")
    dakoujing = Column(String(10), comment="大口径:旧系统开关值 'on' 或 NULL")
    model = Column(String(100), default="", comment="型号类别")
    lastdanjia = Column(Numeric(18, 4), comment="上次单价(保留字段)")
    bmid = Column(Integer, nullable=True, comment="归属部门 id -> departments.id")
    alias1 = Column(String(100), default="", comment="别名1")
    alias2 = Column(String(100), default="", comment="别名2")
    alias3 = Column(String(100), default="", comment="别名3")

    @property
    def is_dakoujing(self):
        return (self.dakoujing or "") == "on"

    def to_dict(self):
        return {
            "id": self.id,
            "Id": self.id,
            "MaterialName": _s(self.material_name),
            "biaoji": _s(self.biaoji),
            "Model": _s(self.model),
            "Spec": _s(self.spec),
            "dakoujing": self.dakoujing,
            "num": _r1(self.num) or 0.0,
            "yujing": _r1(self.yujing) if self.yujing is not None else None,
            "Unit": _s(self.unit),
            "Remark": _s(self.remark),
            "Alias1": _s(self.alias1),
            "Alias2": _s(self.alias2),
            "Alias3": _s(self.alias3),
        }


class InStockRecord(Base):
    __tablename__ = "in_stock_record"
    __table_args__ = (Index("ix_instock_material", "material_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, nullable=False, index=True, comment="材料 id -> material_library.id")
    quantity = Column(Numeric(18, 1), nullable=False, comment="数量(1位小数,+入/-出)")
    operator = Column(String(50), default="", comment="操作人(用户名,限本人编辑/删除)")
    in_stock_time = Column(DateTime, comment="入库/操作时间")
    remark = Column(String(500), default="", comment="备注")
    lei = Column(String(20), default="入库", comment="类型:入库/调整库存/盘点调整")
    lingliao_detail_id = Column(Integer, nullable=True, comment="领料明细 id(领料入库回写,预留)")

    def to_dict(self):
        return {
            "id": self.id,
            "Id": self.id,
            "MaterialId": self.material_id,
            "Quantity": _r1(self.quantity),
            "Operator": _s(self.operator),
            "InStockTime": self.in_stock_time.strftime("%Y-%m-%d %H:%M") if self.in_stock_time else None,
            "Remark": _s(self.remark),
            "lei": _s(self.lei),
            "LingliaoDetailId": self.lingliao_detail_id,
        }


class MaterialRecord(Base):
    """工单领料出库(旧 MaterialRecord):工单模块写入,材料库只读。"""

    __tablename__ = "material_record"
    __table_args__ = (
        Index("ix_matrec_material", "material_id"),
        Index("ix_matrec_workorder", "work_order_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_id = Column(Integer, nullable=False, comment="工单 id -> work_order.id")
    receiver = Column(String(50), default="", comment="领料人")
    material_id = Column(Integer, nullable=False, comment="材料 id -> material_library.id")
    quantity = Column(Numeric(18, 1), comment="领料数量")
    create_time = Column(DateTime, comment="记录时间")
    status = Column(SmallInteger, comment="状态(工单模块用)")
    receive_time = Column(DateTime, comment="确认领料时间(工单模块用)")


class MaterialImage(Base):
    __tablename__ = "material_image"
    __table_args__ = (Index("ix_matimg_material", "material_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, nullable=False, comment="材料 id -> material_library.id")
    file_name = Column(String(200), default="", comment="原始文件名")
    file_path = Column(String(300), default="", comment="原图相对路径(/Upload/MaterialImages/...)")
    file_size = Column(Integer, nullable=True, comment="文件大小")
    thumb_path = Column(String(300), default="", comment="缩略图相对路径")
    remark = Column(String(200), default="", comment="备注")
    create_time = Column(DateTime, default=datetime.now, comment="创建时间")


class WorkOrder(Base):
    """工单主表(旧 WorkOrder):材料库出库记录关联;完整工单模块后续复刻共用此表。"""

    __tablename__ = "work_order"
    __table_args__ = (
        Index("ix_wo_no", "work_order_no"),
        Index("ix_wo_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_no = Column(String(50), default="", comment="工单号")
    creator = Column(String(50), default="", comment="创建人")
    create_time = Column(DateTime, comment="创建时间")
    remark = Column(String(500), default="", comment="备注(材料库出库列表显示此列)")
    banzu = Column(String(50), default="", comment="班组")
    wk_create_time = Column(DateTime, comment="工单创建时间(旧 WkCreateTime)")
    beizhu = Column(String(500), default="", comment="备注2(旧 beizhu)")
    editor = Column(String(50), default="", comment="修改人")
    edittime = Column(DateTime, comment="修改时间")
    bmid = Column(Integer, nullable=True, comment="部门 id -> departments.id")
    is_used = Column(SmallInteger, comment="IsUsed(工单模块用)")
    lingliaotype = Column(String(20), default="", comment="领料类型(工单模块用)")
