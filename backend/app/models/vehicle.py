"""车辆管理模型(表名/字段沿用旧库 db_plan.dbo.*,见 docs/数据迁移约定.md)。

主表是 cl_che(模块名叫 cheliangguanli),另外几张表是本模块列表统计/子表所需:
- cl_chetupian  车辆图片
- cl_chuxian / cl_cxTP  出险记录与出险图片(主表行展开子表)
- PlusOil       加油记录(年度合计升数、月度加油统计;油卡模块也用它)
- yongcherc     派车记录(年度派车次数)
- cl_wxdan      维修单(年度维修次数/金额、近五年统计)

油卡管理(oilcardman)补充:
- OilCard      油卡台账(旧库同名字段,carid 关联 cl_che.id)
车辆维修(chelwx)补充:
- cl_wxdw      维修单位
- cl_wxmx      维修明细(挂在 cl_wxdan 下)
- cl_wxdTP     维修单图片
保险/油耗/违章/费用等属于旧系统各自的独立模块,后续复刻时再迁。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)

from app.db.session import Base


def _d(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if isinstance(value, Decimal) else value


def _blank_nulls(d: dict, keys) -> dict:
    """旧库不少 varchar 列是 NULL,统一回成空串,前端表单/表格绑定更稳。"""
    for k in keys:
        if d.get(k) is None:
            d[k] = ""
    return d


CHE_TEXT_FIELDS = [
    "lx", "jiashiyuan", "telphone", "chehao", "pingshi", "zhoumo", "bm",
    "yongtu", "caozuo", "shenheren", "pinpai", "xinghao", "spren", "spzt",
    "oil", "oilcard", "jsz", "etc", "danganhao", "syxingzhi",
    "fadongjihao", "chejiahao", "pailiang",
]


class ClChe(Base):
    """车辆台账(旧库 cl_che)。delf: 1正常 / 2报废 / 0已删除(软删)。"""

    __tablename__ = "cl_che"
    __table_args__ = (
        Index("ix_clche_bmid", "bmid"),
        Index("ix_clche_chehao", "chehao"),
        Index("ix_clche_delf", "delf"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lx = Column(String(50), default="", comment="车辆类型")
    jiashiyuan = Column(String(50), default="", comment="使用人/驾驶员")
    telphone = Column(String(50), default="", comment="电话")
    chehao = Column(String(50), default="", comment="车号")
    chuchang = Column(Date, nullable=True, comment="注册日期(出厂日期,年检周期基准)")
    pingshi = Column(String(50), default="", comment="办公地点(平时)")
    zhoumo = Column(String(50), default="", comment="停放点(周末)")
    bmid = Column(Integer, nullable=True, comment="部门id(新库 departments.id,旧 bb_bumen.id 按名称重映射)")
    bm = Column(String(100), default="", comment="旧库部门名(新部门表无同名部门时保留文本,便于原样显示)")
    yongtu = Column(String(50), default="", comment="车辆用途")
    caozuo = Column(String(50), default="", comment="操作员")
    zuihoutime = Column(DateTime, nullable=True, comment="最后操作日期")
    shenheren = Column(String(20), default="", comment="审核人")
    delf = Column(SmallInteger, default=1, nullable=False, comment="1正常 2报废 0已删除")
    pinpai = Column(String(50), default="", comment="品牌")
    xinghao = Column(String(50), default="", comment="型号")
    spren = Column(String(16), default="", comment="审批人")
    spzt = Column(String(10), default="", comment="审批状态:待审批/审批通过")
    spdate = Column(DateTime, nullable=True, comment="审批日期")
    oil = Column(String(20), default="", comment="油品:92#/0#/95#/其他")
    oilcard = Column(String(50), default="", comment="油卡号")
    jsz = Column(String(50), default="", comment="驾照号")
    jiage = Column(Numeric(18, 2), nullable=True, comment="购置价格")
    grriqi = Column(Date, nullable=True, comment="购置日期")
    etc = Column(String(50), default="", comment="ETC")
    danganhao = Column(String(50), default="", comment="档案号")
    syxingzhi = Column(String(50), default="", comment="使用性质")
    zws = Column(Integer, nullable=True, comment="座位数")
    fadongjihao = Column(String(50), default="", comment="发动机号")
    chejiahao = Column(String(50), default="", comment="车架号")
    pailiang = Column(String(10), default="", comment="排量")
    LastReminderDate = Column(DateTime, nullable=True, comment="最后提醒日期")
    ReminderYear = Column(Integer, nullable=True, comment="提醒年份")
    ReminderLevel = Column(Integer, nullable=True, comment="提醒级别 0未提醒 1=90天 2=30天 3=7天 4已过期")
    IsInspected = Column(Boolean, nullable=True, default=False, comment="是否已年检")
    InspectionDate = Column(Date, nullable=True, comment="标注年检日期")
    NextInspectionDate = Column(Date, nullable=True, comment="下次年检日期")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id,
            "lx": self.lx, "jiashiyuan": self.jiashiyuan, "telphone": self.telphone,
            "chehao": self.chehao, "chuchang": _d(self.chuchang),
            "pingshi": self.pingshi, "zhoumo": self.zhoumo,
            "bmid": self.bmid, "bm": self.bm, "yongtu": self.yongtu,
            "caozuo": self.caozuo, "zuihoutime": _dt(self.zuihoutime),
            "shenheren": self.shenheren, "delf": self.delf,
            "pinpai": self.pinpai, "xinghao": self.xinghao,
            "spren": self.spren, "spzt": self.spzt, "spdate": _dt(self.spdate),
            "oil": self.oil, "oilcard": self.oilcard, "jsz": self.jsz,
            "jiage": _n(self.jiage), "grriqi": _d(self.grriqi),
            "etc": self.etc, "danganhao": self.danganhao, "syxingzhi": self.syxingzhi,
            "zws": self.zws, "fadongjihao": self.fadongjihao,
            "chejiahao": self.chejiahao, "pailiang": self.pailiang,
            "LastReminderDate": _dt(self.LastReminderDate),
            "ReminderYear": self.ReminderYear, "ReminderLevel": self.ReminderLevel,
            "IsInspected": bool(self.IsInspected) if self.IsInspected is not None else None,
            "InspectionDate": _d(self.InspectionDate),
            "NextInspectionDate": _d(self.NextInspectionDate),
        }, CHE_TEXT_FIELDS)


class ClChetupian(Base):
    """车辆图片(旧库 cl_chetupian)。url 为相对 /Upload/cheliangImages/ 的路径或新上传文件名。"""

    __tablename__ = "cl_chetupian"
    __table_args__ = (Index("ix_cltp_cheid", "cheid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    cheid = Column(Integer, nullable=True, comment="车辆id")
    url = Column(String(250), default="", comment="图片路径")
    file_name = Column(String(250), default="", comment="原始文件名")

    def to_dict(self):
        return {"id": self.id, "cheid": self.cheid, "url": self.url, "file_name": self.file_name or ""}


class ClChuxian(Base):
    """出险记录(旧库 cl_chuxian),主表行展开的子表。"""

    __tablename__ = "cl_chuxian"
    __table_args__ = (Index("ix_clcx_cheid", "cheid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    riqi = Column(Date, nullable=True, comment="出险日期")
    bm = Column(String(50), default="", comment="部门")
    cheid = Column(Integer, nullable=True, comment="车辆id")
    zeren = Column(String(20), default="", comment="责任")
    jiashiyuan = Column(String(50), default="", comment="责任人")
    jine = Column(Numeric(18, 2), nullable=True, comment="金额(元)")
    miaoshu = Column(String(500), default="", comment="描述")
    caozuo = Column(String(20), default="", comment="记录人")
    zuihou = Column(DateTime, nullable=True, comment="最后操作日期")
    dizhi = Column(String(250), default="", comment="地点")
    gongli = Column(Integer, nullable=True, comment="公里")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "riqi": _d(self.riqi), "bm": self.bm, "cheid": self.cheid,
            "zeren": self.zeren, "jiashiyuan": self.jiashiyuan, "jine": _n(self.jine),
            "miaoshu": self.miaoshu, "caozuo": self.caozuo, "zuihou": _dt(self.zuihou),
            "dizhi": self.dizhi, "gongli": self.gongli,
        }, ["bm", "zeren", "jiashiyuan", "miaoshu", "caozuo", "dizhi"])


class ClCxTP(Base):
    """出险图片(旧库 cl_cxTP)。"""

    __tablename__ = "cl_cxTP"
    __table_args__ = (Index("ix_clcxtp_cxid", "cxid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    cxid = Column(Integer, nullable=True, comment="出险记录id")
    url = Column(String(250), default="", comment="图片路径")

    def to_dict(self):
        return {"id": self.id, "cxid": self.cxid, "url": self.url}


class PlusOil(Base):
    """加油记录(旧库 PlusOil,注意 oill 双 l)。用于年度升数/月度加油统计。"""

    __tablename__ = "PlusOil"
    __table_args__ = (Index("ix_plusoil_cheid", "cheid"), Index("ix_plusoil_ptime", "ptime"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    oill = Column(Numeric(18, 2), nullable=True, comment="加油升数")
    lei = Column(String(10), default="", comment="油类:0#/92#/95#")
    jine = Column(Numeric(18, 2), nullable=True, comment="金额")
    ptime = Column(DateTime, nullable=True, comment="加油日期")
    kaid = Column(Integer, nullable=True, comment="油卡id")
    cheid = Column(Integer, nullable=True, comment="车辆id")
    addtime = Column(DateTime, nullable=True, comment="录入时间")
    bmid = Column(Integer, nullable=True, comment="部门id(新 departments.id)")
    didian = Column(String(250), default="", comment="地点")
    leibie = Column(String(50), default="", comment="油品类")

    def to_dict(self):
        return {
            "id": self.id, "oill": _n(self.oill), "lei": self.lei, "jine": _n(self.jine),
            "ptime": _dt(self.ptime), "kaid": self.kaid, "cheid": self.cheid,
            "addtime": _dt(self.addtime), "bmid": self.bmid,
            "didian": self.didian, "leibie": self.leibie,
        }


class OilCard(Base):
    """油卡台账(旧库 OilCard,模块名 OilCarMan)。

    carid 关联 cl_che.id;chehao 是旧库冗余列(已废弃,列表车号以 cl_che 为准)。
    yujing=1 表示余额预警(导入/余额更新时按车辆用途阈值写入,NOW 不实时计算)。
    """

    __tablename__ = "OilCard"
    __table_args__ = (
        Index("ix_oilcard_kanum", "kanum"),
        Index("ix_oilcard_carid", "carid"),
        Index("ix_oilcard_zt", "zt"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    kanum = Column(String(50), default="", comment="卡号")
    djdate = Column(DateTime, nullable=True, comment="登记日期")
    editdate = Column(DateTime, nullable=True, comment="编辑日期")
    chehao = Column(String(20), default="", comment="车号(冗余列,已废弃)")
    zt = Column(String(50), default="正常", comment="状态:正常/停用/注销")
    youpin = Column(String(10), default="", comment="油品:92#/0#/95#/其他")
    bfj = Column(Numeric(18, 2), nullable=True, comment="备付金")
    ye = Column(Numeric(18, 2), nullable=True, comment="余额")
    yujing = Column(Integer, nullable=True, comment="余额预警:1预警,空正常")
    carid = Column(Integer, nullable=True, comment="车辆id(cl_che.id)")
    handadd = Column(Numeric(18, 2), nullable=True, comment="手动充值金额")
    yanzhengma = Column(String(250), default="", comment="校验码")
    bz = Column(String(500), default="", comment="备注")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "kanum": self.kanum,
            "djdate": _dt(self.djdate), "editdate": _dt(self.editdate),
            "chehao": self.chehao, "zt": self.zt, "youpin": self.youpin,
            "bfj": _n(self.bfj), "ye": _n(self.ye), "yujing": self.yujing,
            "carid": self.carid, "handadd": _n(self.handadd),
            "yanzhengma": self.yanzhengma, "bz": self.bz,
        }, ["kanum", "chehao", "zt", "youpin", "yanzhengma", "bz"])


class Yongcherc(Base):
    """派车/用车日常记录(旧库 yongcherc)。列表只用 ksdate+cheid 统计年度派车次数。"""

    __tablename__ = "yongcherc"
    __table_args__ = (Index("ix_yongcherc_cheid", "cheid"), Index("ix_yongcherc_ksdate", "ksdate"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    ksdate = Column(DateTime, nullable=True, comment="开始时间")
    jsdate = Column(DateTime, nullable=True, comment="结束时间")
    ksgl = Column(Integer, nullable=True, comment="开始公里")
    jsgl = Column(Integer, nullable=True, comment="结束公里")
    yuanyin = Column(String(250), default="", comment="原因")
    beizhu = Column(String(250), default="", comment="备注")
    didian = Column(String(250), default="", comment="地点")
    usercar = Column(String(120), default="", comment="用车人")
    shenhe = Column(String(120), default="", comment="审核")
    bumenld = Column(String(120), default="", comment="部门领导")
    cheid = Column(Integer, nullable=True, comment="车辆id")
    cz = Column(DateTime, nullable=True, comment="操作时间")
    czy = Column(String(120), default="", comment="操作员")
    shenheqz = Column(String(120), default="", comment="审核签字")
    shenpi = Column(String(120), default="", comment="审批")
    shtime = Column(DateTime, nullable=True, comment="审核时间")
    sptime = Column(DateTime, nullable=True, comment="审批时间")
    tingfang = Column(String(50), default="", comment="停放")
    shenQingTime = Column(DateTime, nullable=True, comment="申请时间")
    ok = Column(Boolean, nullable=True, comment="是否通过")
    sj = Column(String(150), default="", comment="司机")

    def to_dict(self):
        gl = None
        if self.ksgl is not None and self.jsgl is not None:
            gl = self.jsgl - self.ksgl
        return _blank_nulls({
            "id": self.id,
            "ksdate": _dt(self.ksdate),
            "jsdate": _dt(self.jsdate),
            "ksgl": self.ksgl,
            "jsgl": self.jsgl,
            "gl": gl,
            "yuanyin": self.yuanyin,
            "beizhu": self.beizhu,
            "didian": self.didian,
            "usercar": self.usercar,
            "shenhe": self.shenhe,
            "bumenld": self.bumenld,
            "cheid": self.cheid,
            "cz": _dt(self.cz),
            "czy": self.czy,
            "shenheqz": self.shenheqz,
            "shenpi": self.shenpi,
            "shtime": _dt(self.shtime),
            "sptime": _dt(self.sptime),
            "tingfang": self.tingfang,
            "shenQingTime": _dt(self.shenQingTime),
            "ok": bool(self.ok) if self.ok is not None else None,
            "sj": self.sj,
        }, ["yuanyin", "beizhu", "didian", "usercar", "shenhe", "bumenld",
            "czy", "shenheqz", "shenpi", "tingfang", "sj"])


class YongchercTP(Base):
    """日常用车图片(旧库 yongchercTP)。url 形如 /Upload/yongchercimages/...。"""

    __tablename__ = "yongchercTP"
    __table_args__ = (Index("ix_yongcherctp_ycid", "yongchercid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(250), default="", comment="图片路径")
    yongchercid = Column(Integer, nullable=True, comment="用车记录id")

    def to_dict(self):
        return {"id": self.id, "url": self.url or "", "yongchercid": self.yongchercid}


class ClWxdan(Base):
    """维修单(旧库 cl_wxdan)。车辆管理列表年度统计用它,车辆维修模块(clwx)也用它做主表。"""

    __tablename__ = "cl_wxdan"
    __table_args__ = (Index("ix_clwxdan_cheid", "cheid"), Index("ix_clwxdan_jcriqi", "jcriqi"))

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    jcriqi = Column(Date, nullable=True, comment="进场日期")
    bxren = Column(String(50), default="", comment="报修人")
    gonglinum = Column(Integer, nullable=True, comment="公里数")
    xiangmu = Column(String(250), default="", comment="维修项目")
    jine = Column(Numeric(18, 4), nullable=True, comment="总金额")
    ccriqi = Column(Date, nullable=True, comment="出厂日期")
    cheid = Column(Integer, nullable=True, comment="车辆id")
    djriqi = Column(DateTime, nullable=True, comment="登记日期")
    username = Column(String(20), default="", comment="登记人")
    wxdw = Column(Integer, nullable=True, comment="维修单位id")
    gongshifei = Column(Numeric(18, 4), nullable=True, comment="工时费")
    peijianfei = Column(Numeric(18, 4), nullable=True, comment="配件费")
    zk = Column(Numeric(18, 4), nullable=True, comment="折扣")
    lx = Column(String(50), default="", comment="维保类型")
    sp = Column(Boolean, nullable=True, comment="是否审批")
    spren = Column(String(50), default="", comment="审批人")
    sptime = Column(DateTime, nullable=True, comment="审批时间")

    def to_dict(self):
        return {
            "id": self.id, "ID": self.id,
            "jcriqi": _d(self.jcriqi), "ccriqi": _d(self.ccriqi),
            "bxren": self.bxren or "", "gonglinum": self.gonglinum,
            "xiangmu": self.xiangmu or "", "jine": _n(self.jine),
            "cheid": self.cheid, "djriqi": _dt(self.djriqi),
            "username": self.username or "", "wxdw": self.wxdw,
            "gongshifei": _n(self.gongshifei), "peijianfei": _n(self.peijianfei),
            "zk": _n(self.zk), "lx": self.lx or "",
            "sp": bool(self.sp) if self.sp is not None else False,
            "spren": self.spren or "", "sptime": _dt(self.sptime),
        }


class ClWxdw(Base):
    """维修单位(旧库 cl_wxdw)。"""

    __tablename__ = "cl_wxdw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dwname = Column(String(150), default="", comment="维修单位名称")

    def to_dict(self):
        return {"id": self.id, "dwname": self.dwname or ""}


class ClWxmx(Base):
    """维修明细(旧库 cl_wxmx),挂在 cl_wxdan 下。"""

    __tablename__ = "cl_wxmx"
    __table_args__ = (
        Index("ix_clwxmx_wxdid", "wxdid"),
        Index("ix_clwxmx_cheid", "cheid"),
        Index("ix_clwxmx_djriqi", "djriqi"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wxdid = Column(BigInteger, nullable=True, comment="维修单id")
    xiangmu = Column(String(150), default="", comment="项目名称")
    danjia = Column(Numeric(18, 4), nullable=True, comment="折后单价")
    shuliang = Column(Float, nullable=True, comment="数量")
    zonge = Column(Numeric(18, 4), nullable=True, comment="总金额")
    pjorgs = Column(String(10), default="", comment="工时费/配件费")
    djriqi = Column(DateTime, nullable=True, comment="登记日期")
    username = Column(String(20), default="", comment="登记人")
    guige = Column(String(150), default="", comment="品牌规格型号")
    gjz = Column(String(50), default="", comment="项目关键字")
    cheid = Column(Integer, nullable=True, comment="车辆id")
    zkqiandanjia = Column(Numeric(18, 4), nullable=True, comment="原单价")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "wxdid": self.wxdid,
            "xiangmu": self.xiangmu, "danjia": _n(self.danjia),
            "shuliang": _n(self.shuliang), "zonge": _n(self.zonge),
            "pjorgs": self.pjorgs, "djriqi": _dt(self.djriqi),
            "username": self.username, "guige": self.guige,
            "gjz": self.gjz, "cheid": self.cheid,
            "zkqiandanjia": _n(self.zkqiandanjia),
        }, ["xiangmu", "pjorgs", "username", "guige", "gjz"])


class ClWxdTP(Base):
    """维修单图片(旧库 cl_wxdTP)。url 形如 /Upload/weixiudanImages/2021/7/28/x.jpg。"""

    __tablename__ = "cl_wxdTP"
    __table_args__ = (Index("ix_clwxtp_wxdid", "wxdid"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wxdid = Column(BigInteger, nullable=True, comment="维修单id")
    url = Column(String(250), default="", comment="图片路径")

    def to_dict(self):
        return {"id": self.id, "wxdid": self.wxdid, "url": self.url or ""}


class Tboil(Base):
    """整年公里提取结果(旧库 tboil)。日常用车「提取整年公里数」写入，供加油统计使用。"""

    __tablename__ = "tboil"
    __table_args__ = (Index("ix_tboil_cheid", "cheid"), Index("ix_tboil_oildate", "oildate"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    cheid = Column(Integer, nullable=True, comment="车辆id")
    oildate = Column(DateTime, nullable=True, comment="统计日期")
    oilnum = Column(Numeric(18, 2), nullable=True, comment="加油升数")
    lei = Column(String(20), default="", comment="油品")
    username = Column(String(50), default="", comment="操作人")
    riqi = Column(DateTime, nullable=True, comment="录入时间")
    glnum = Column(Integer, nullable=True, comment="公里数")
    nian = Column(Integer, nullable=True, comment="年")
    yue = Column(Integer, nullable=True, comment="月")
    bumen = Column(String(100), default="", comment="部门")
    oiljine = Column(Numeric(18, 2), nullable=True, comment="加油金额")


class ClBaoxian(Base):
    """车辆保险(旧库 cl_baoxian,对应旧模块 CLbaoxianController)。

    cheid 关联 cl_che.id(旧库迁移保留原 id,直接对应);lx 取值「商业车险/交强险」,
    历史数据存在「商业险」写法,前端回显时按关键字归并;djname 为登记人,
    旧口径:登记人为空的历史数据允许编辑,非登记人本人拒绝。
    """

    __tablename__ = "cl_baoxian"
    __table_args__ = (
        Index("ix_clbx_cheid", "cheid"),
        Index("ix_clbx_tbdate", "tbdate"),
        Index("ix_clbx_bdnumber", "bdnumber"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cheid = Column(Integer, nullable=True, comment="车辆id(cl_che.id)")
    tbdate = Column(Date, nullable=True, comment="投保日期")
    bdnumber = Column(String(50), default="", comment="保单号")
    lx = Column(String(20), default="", comment="保险种类:商业车险/交强险")
    jine = Column(Numeric(18, 4), nullable=True, comment="投保金额(元)")
    bxcom = Column(String(50), default="", comment="保险公司")
    dqdate = Column(Date, nullable=True, comment="保险到期")
    djname = Column(String(20), default="", comment="登记人")
    djdate = Column(DateTime, nullable=True, comment="登记日期")
    jingshou = Column(String(20), default="", comment="经手人")
    bz = Column(String(200), default="", comment="备注")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "cheid": self.cheid, "tbdate": _d(self.tbdate),
            "bdnumber": self.bdnumber, "lx": self.lx, "jine": _n(self.jine),
            "bxcom": self.bxcom, "dqdate": _d(self.dqdate),
            "djname": self.djname, "djdate": _dt(self.djdate),
            "jingshou": self.jingshou, "bz": self.bz,
        }, ["bdnumber", "lx", "bxcom", "djname", "jingshou", "bz"])


class ClWeizhang(Base):
    """车辆违章记录(旧库 clweizhang,对应旧模块 ClweizhangController)。

    字段完全沿用旧库;wzriqi 为违章日期,dj/zhriqi 记录登记人与最后更新时间。
    """

    __tablename__ = "clweizhang"
    __table_args__ = (
        Index("ix_clwz_cheid", "cheid"),
        Index("ix_clwz_wzriqi", "wzriqi"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cheid = Column(Integer, nullable=True, comment="车辆id(cl_che.id)")
    wzriqi = Column(Date, nullable=True, comment="违章日期")
    lu = Column(String(250), default="", comment="违章路段")
    jine = Column(Numeric(18, 2), nullable=True, comment="罚款金额")
    fen = Column(Integer, nullable=True, comment="扣分")
    xingming = Column(String(30), default="", comment="违章人")
    wz = Column(String(150), default="", comment="违章内容")
    dj = Column(String(20), default="", comment="登记人")
    djriqi = Column(DateTime, nullable=True, comment="登记日期")
    zhriqi = Column(DateTime, nullable=True, comment="最后更新日期")
    gongli = Column(Integer, nullable=True, comment="公里数")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "cheid": self.cheid, "wzriqi": _d(self.wzriqi),
            "lu": self.lu, "jine": _n(self.jine), "fen": self.fen,
            "xingming": self.xingming, "wz": self.wz, "dj": self.dj,
            "djriqi": _dt(self.djriqi), "zhriqi": _dt(self.zhriqi),
            "gongli": self.gongli,
        }, ["lu", "xingming", "wz", "dj"])


class ClFeiyong(Base):
    """车辆各类费用(旧库 cl_feiyong,对应旧模块 CLfeiyongController 「车辆各类费用表」)。

    cheid 关联 cl_che.id,部门取车辆 bmid(本表无 bmid 列);lx 固定「洗车/高速/停车」;
    jine 沿用旧库 money 的 4 位小数;username/djdate 是登记人与初始登记日期,
    zuihoudate 是最后编辑日期(旧 Editgz 只刷这一列,不改登记人)。
    """

    __tablename__ = "cl_feiyong"
    __table_args__ = (
        Index("ix_clfy_cheid", "cheid"),
        Index("ix_clfy_date", "feiyongdate"),
        Index("ix_clfy_lx", "lx"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cheid = Column(Integer, nullable=True, comment="车辆id(cl_che.id)")
    lx = Column(String(50), default="", comment="费用类别:洗车/高速/停车")
    jine = Column(Numeric(18, 4), nullable=True, comment="金额(元)")
    bz = Column(String(200), default="", comment="备注(旧库 nvarchar(50),新系统放宽)")
    username = Column(String(20), default="", comment="登记人姓名")
    djdate = Column(DateTime, nullable=True, comment="登记日期")
    zuihoudate = Column(DateTime, nullable=True, comment="最后操作日期")
    feiyongdate = Column(Date, nullable=True, comment="费用日期")
    dw = Column(String(100), default="", comment="收费单位")
    fangshi = Column(String(50), default="", comment="收费方式")
    jingshou = Column(String(50), default="", comment="经手人")

    def to_dict(self):
        return _blank_nulls({
            "id": self.id, "cheid": self.cheid, "lx": self.lx,
            "jine": _n(self.jine), "bz": self.bz, "username": self.username,
            "djdate": _dt(self.djdate), "zuihoudate": _dt(self.zuihoudate),
            "feiyongdate": _d(self.feiyongdate), "dw": self.dw,
            "fangshi": self.fangshi, "jingshou": self.jingshou,
        }, ["lx", "bz", "username", "dw", "fangshi", "jingshou"])

