"""领料申请模块(照旧 whl.Model lingliao / lingliaodetail / lingliao_file 复刻)。

旧表名与字段名基本沿用(SQL Server 驼峰 -> MySQL 小写下划线):
- lingliao         领料单主表(单号/部门/申请人/申请日期/审核状态/供应商/用途说明)
- lingliaodetail   领料明细(材料/型号/规格/单位/申请数量/实发数量/结算字段)
- lingliao_file    领料单附件(编辑页临时上传后转存 ~/uploads/LingLiao,列表页可直接上传)

审核状态 shzt: 0 草稿 / 1 已提交 / 2 已审核 / 3 已驳回 / 4 已作废 / 5 部分结算 / 6 全部结算。
旧系统「领料单审核」pdqx 在新系统折算为 lingliao:audit,超管自动拥有。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, Numeric, String, Text

from app.db.session import Base


class LingLiao(Base):
    __tablename__ = "lingliao"
    __table_args__ = (
        Index("ix_ll_danno", "danno"),
        Index("ix_ll_bmid", "bmid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    danno = Column(String(50), default="", comment="单号 LLyyyyMMdd0001")
    bm = Column(String(100), default="", comment="部门名称(申请时快照)")
    sqren = Column(String(50), default="", comment="申请人(登录名)")
    sqriqi = Column(DateTime, comment="申请日期")
    shzt = Column(Integer, default=0, comment="审核状态:0草稿/1已提交/2已审核/3已驳回/4已作废/5部分结算/6全部结算")
    gongyingshang = Column(String(200), default="", comment="供应商")
    modriqi = Column(DateTime, comment="最后修改时间")
    modren = Column(String(50), default="", comment="最后修改人")
    shren = Column(String(50), default="", comment="审核/驳回人")
    shriqi = Column(DateTime, comment="审核/驳回日期")
    shuoming = Column(String(500), default="", comment="用途说明")
    bmid = Column(Integer, nullable=True, comment="部门 id -> departments.id")

    def to_dict(self, file_count: int = 0) -> dict:
        return {
            "id": self.id,
            "danno": self.danno or "",
            "bm": self.bm or "",
            "sqren": self.sqren or "",
            "sqriqi": self.sqriqi.strftime("%Y-%m-%d") if self.sqriqi else "",
            "shren": self.shren or "",
            "shriqi": self.shriqi.strftime("%Y-%m-%d") if self.shriqi else "",
            "gongyingshang": self.gongyingshang or "",
            "shuoming": self.shuoming or "",
            "shzt": self.shzt if self.shzt is not None else 0,
            "bmid": self.bmid,
            "fileCount": file_count,
        }


class LingLiaoDetail(Base):
    __tablename__ = "lingliaodetail"
    __table_args__ = (
        Index("ix_lld_lingliaoid", "lingliaoid"),
        Index("ix_lld_material", "material_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sqriqi = Column(DateTime, comment="申请日期(冗余)")
    llname = Column(String(100), default="", comment="材料名称(从 materialname 第一段取)")
    shuoming = Column(String(500), default="", comment="说明")
    materialname = Column(String(300), default="", comment="材料库下拉展示文本 名称/型号/规格")
    model = Column(String(100), default="", comment="型号")
    spec = Column(String(100), default="", comment="规格")
    unit = Column(String(20), default="", comment="单位")
    num = Column(Numeric(18, 2), comment="申请数量")
    renum = Column(Numeric(18, 2), comment="实发数量")
    material_id = Column(Integer, nullable=True, comment="材料 id -> material_library.id")
    jiesuannum = Column(Numeric(18, 2), default=0, comment="已结算数量")
    lingliaoid = Column(Integer, nullable=True, comment="领料单 id -> lingliao.id")
    jiesuanzt = Column(Integer, default=0, comment="结算状态:0未结算/1部分结算/2全部结算")
    zfsj = Column(DateTime, comment="作废时间")
    beizhu = Column(String(300), default="", comment="备注")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "MaterialId": self.material_id,
            "llname": self.llname or "",
            "materialname": self.materialname or "",
            "model": self.model or "",
            "spec": self.spec or "",
            "unit": self.unit or "",
            "num": _r2(self.num),
            "renum": _r2(self.renum),
            "jiesuannum": _r2(self.jiesuannum) or 0.0,
            "jiesuanzt": self.jiesuanzt if self.jiesuanzt is not None else 0,
            "beizhu": self.beizhu or "",
        }


class LingLiaoFile(Base):
    __tablename__ = "lingliao_file"
    __table_args__ = (Index("ix_llf_lingliaoid", "lingliaoid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    lingliaoid = Column(Integer, nullable=False, comment="领料单 id -> lingliao.id")
    filename = Column(String(255), default="", comment="原始文件名")
    filepath = Column(String(500), default="", comment="相对 UPLOAD_DIR 的存储路径")
    filesize = Column(Integer, nullable=True, comment="字节数")
    uploadtime = Column(DateTime, default=datetime.now, comment="上传时间")
    operator_name = Column(String(50), default="", comment="上传人(可删除自己上传的附件)")

    def to_dict(self, can_delete: bool = False, download_url: str = "") -> dict:
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
            "filepath": self.filepath or "",
            "filesize": size,
            "filesizeStr": size_str,
            "uploadtime": self.uploadtime.strftime("%Y-%m-%d %H:%M:%S") if self.uploadtime else "",
            "operator_name": self.operator_name or "",
            "canDelete": can_delete,
            "downloadUrl": download_url,
        }


def _r2(v):
    return None if v is None else round(float(v), 2)
