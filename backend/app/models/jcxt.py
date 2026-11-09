"""稽查系统(照旧 jcxt/spjicha/jcdan/JcJl 四模块、db_plan 的 jc_* 表 1:1 复刻)。

旧库表名、字段名全部沿用,便于历史数据平移:
- jc_jcxx       稽查信息主表(jcxt 建单 + spjicha 审批共用,spzt: 暂存/待审核/审核通过)
- jc_tupian     稽查图片(url 指向旧 /Upload/jcImages/,历史文件在旧生产服务器)
- jc_printcolum 用户自选导出列(userid -> users.id)
- jcdan         稽查单(可关联 jc_jcxx)
- jc_wzlb       违章类别字典
- jc_wzdw       违章单位字典(旧库 0 条)
- jcjiangli     月度奖励汇总(comput 生成;bmid 旧硬编码 1/4 -> 新 7/15)
- jcjiangliFp   奖励分配明细

金额列 DECIMAL(18,4) 保全旧库 money 4 位小数。chuliriqi/weizhangriqi 旧库是
date 类型,沿用 Date;spdate/caozuoriqi/zuihougengxin 是 datetime。
"""

from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, Numeric, String, Text

from app.db.session import Base

MONEY = Numeric(18, 4)


def _s(v):
    return "" if v is None else v


def _dt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return None


def _d(v):
    return v.strftime("%Y-%m-%d") if isinstance(v, (date, datetime)) else None


class JcJcxx(Base):
    __tablename__ = "jc_jcxx"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gongdanhao = Column(String(300), comment="工单号")
    caozuoriqi = Column(DateTime, comment="建单日期")
    chuliriqi = Column(Date, comment="处理日期")
    weizhangriqi = Column(Date, comment="违章日期")
    weizhangren = Column(String(350), comment="违章单位")
    weizhangdianhua = Column(String(380), comment="违章电话")
    weizhangdizhi = Column(String(350), comment="违章地址")
    zhuijiaoshuifei = Column(MONEY, comment="追缴水费")
    zhuijiaogongliaofei = Column(MONEY, comment="追缴工料费")
    jubaoren = Column(String(320), comment="举报人")
    ssbmid = Column(Integer, index=True, comment="所属部门 id -> departments.id")
    zhuijiaobm = Column(String(150), comment="追缴部门/人员")
    zuihougengxin = Column(DateTime, comment="最后更新")
    jbjiangli = Column(MONEY, comment="举报奖励")
    zhuijiaojiangli = Column(MONEY, comment="追缴奖励")
    zhuangtai = Column(String(120), comment="处理状态:处理中/已完结")
    zhixingqingkuang = Column(String(120), comment="执行情况:逃逸/已缴款/不处理/减免")
    lbid = Column(Integer, comment="违章类别 id(旧遗留,新数据用 wzleibie 名称)")
    caozuoname = Column(String(120), index=True, comment="操作员(建单人)")
    yingjiaoshuiliang = Column(Integer, comment="应收水量")
    yingjiaoshuifei = Column(MONEY, comment="应收水费")
    yingjiaogongliaofei = Column(MONEY, comment="应收工料费")
    beizhu = Column(Text, comment="备注")
    jubaoleibie = Column(String(120), comment="举报类别")
    xinxilaiyuan = Column(String(120), comment="信息来源")
    banjietianshu = Column(Integer, comment="办结天数")
    weizhangneirong = Column(Text, comment="违章内容")
    zhuijiaoshuiliang = Column(Integer, comment="追缴水量")
    guancai = Column(String(120), comment="管材")
    guanjing = Column(String(120), comment="管径")
    nongcunjicha = Column(String(120), comment="农村稽查")
    oldid = Column(Integer, comment="旧系统遗留 id")
    danjia = Column(MONEY, comment="水费单价")
    intguanjing = Column(Integer, comment="管径数值(大管过滤>=300用)")
    spren = Column(String(50), comment="提交人")
    spzt = Column(String(10), index=True, comment="审批状态:暂存/待审核/审核通过")
    spdate = Column(DateTime, comment="提交/审批时间")
    peibiaofei = Column(MONEY, comment="赔表费")
    wzleibie = Column(String(250), comment="违章类别名称")
    ssspren = Column(String(50), comment="售水审批人")
    jcdanid = Column(Integer, comment="关联稽查单 id -> jcdan.id")

    __table_args__ = (
        Index("ix_jcxx_weizhangriqi", "weizhangriqi"),
        Index("ix_jcxx_chuliriqi", "chuliriqi"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "ID": self.id,
            "gongdanhao": _s(self.gongdanhao),
            "caozuoriqi": _dt(self.caozuoriqi),
            "chuliriqi": _d(self.chuliriqi),
            "weizhangriqi": _d(self.weizhangriqi),
            "weizhangren": _s(self.weizhangren),
            "weizhangdianhua": _s(self.weizhangdianhua),
            "weizhangdizhi": _s(self.weizhangdizhi),
            "zhuijiaoshuiliang": self.zhuijiaoshuiliang,
            "jubaoren": _s(self.jubaoren),
            "ssbmid": self.ssbmid,
            "zhuijiaobm": _s(self.zhuijiaobm),
            "zuihougengxin": _dt(self.zuihougengxin),
            "zhuangtai": _s(self.zhuangtai),
            "zhixingqingkuang": _s(self.zhixingqingkuang),
            "lbid": self.lbid,
            "caozuoname": _s(self.caozuoname),
            "beizhu": _s(self.beizhu),
            "jubaoleibie": _s(self.jubaoleibie),
            "xinxilaiyuan": _s(self.xinxilaiyuan),
            "banjietianshu": self.banjietianshu,
            "weizhangneirong": _s(self.weizhangneirong),
            "guancai": _s(self.guancai),
            "guanjing": _s(self.guanjing),
            "nongcunjicha": _s(self.nongcunjicha),
            "intguanjing": self.intguanjing,
            "spren": _s(self.spren),
            "spzt": _s(self.spzt),
            "spdate": _dt(self.spdate),
            "wzleibie": _s(self.wzleibie),
            "ssspren": _s(self.ssspren),
            "jcdanid": self.jcdanid,
        }


class JcTupian(Base):
    __tablename__ = "jc_tupian"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(550), comment="图片相对路径")
    jcxxid = Column(Integer, index=True, comment="稽查信息 id -> jc_jcxx.id")


class JcPrintcolum(Base):
    __tablename__ = "jc_printcolum"

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer, index=True, comment="用户 id -> users.id")
    printcolum = Column(String(50), comment="导出列字段名")


class Jcdan(Base):
    __tablename__ = "jcdan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gongdanhao = Column(String(50), comment="工单号")
    weizhangdanwei = Column(String(350), comment="违章单位(者)")
    bmid = Column(Integer, index=True, comment="登记部门 id -> departments.id")
    bianhao = Column(String(50), index=True, comment="稽查单编号(唯一)")
    jbren = Column(String(50), comment="举报人")
    fstime = Column(DateTime, comment="发生时间")
    didian = Column(String(350), comment="违章地点")
    nr = Column(Text, comment="违章情况描述")
    wzren = Column(String(20), comment="违章签收人")
    usname = Column(String(50), comment="登记人")
    bz = Column(Text, comment="备注")
    jbleibie = Column(String(50), comment="举报类别")
    addtime = Column(DateTime, comment="建单日期")
    edtime = Column(DateTime, comment="编辑日期")
    kpren = Column(String(50), comment="开票人")
    weizhangdianhua = Column(String(50), comment="违章电话")
    jcxxid = Column(Integer, comment="关联稽查信息 id -> jc_jcxx.id")

    def to_dict(self):
        return {
            "id": self.id,
            "ID": self.id,
            "gongdanhao": _s(self.gongdanhao),
            "weizhangdanwei": _s(self.weizhangdanwei),
            "bmid": self.bmid,
            "bianhao": _s(self.bianhao),
            "jbren": _s(self.jbren),
            "fstime": _dt(self.fstime),
            "didian": _s(self.didian),
            "nr": _s(self.nr),
            "wzren": _s(self.wzren),
            "usname": _s(self.usname),
            "bz": _s(self.bz),
            "jbleibie": _s(self.jbleibie),
            "addtime": _dt(self.addtime),
            "edtime": _dt(self.edtime),
            "kpren": _s(self.kpren),
            "weizhangdianhua": _s(self.weizhangdianhua),
            "jcxxid": self.jcxxid,
        }


class JcWzlb(Base):
    __tablename__ = "jc_wzlb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lbname = Column(String(50), comment="类别名")
    ssname = Column(String(50), comment="大类别名")


class JcWzdw(Base):
    __tablename__ = "jc_wzdw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    weizhangren = Column(String(350), comment="违章单位")


class Jcjiangli(Base):
    __tablename__ = "jcjiangli"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bmid = Column(Integer, index=True, comment="部门 id(旧硬编码 1/4 -> 新 7/15)")
    nd = Column(Integer, comment="年度")
    yue = Column(Integer, comment="月份")
    jianglijine = Column(MONEY, comment="奖励金额")
    zjshuifei = Column(MONEY, comment="追缴水费合计")
    zjbutie = Column(MONEY, comment="追缴补贴(带小数)")
    jbjiangli = Column(MONEY, comment="举报奖励合计")
    usname = Column(String(50), comment="操作用户")
    utime = Column(DateTime, comment="操作日期")
    zjbutie_int = Column(Integer, comment="追缴补贴(取整)")

    def to_dict(self):
        return {
            "id": self.id,
            "ID": self.id,
            "bmid": self.bmid,
            "nd": self.nd,
            "yue": self.yue,
            "usname": _s(self.usname),
            "utime": _dt(self.utime),
            "zjbutie_int": self.zjbutie_int,
        }


class JcjiangliFp(Base):
    __tablename__ = "jcjiangliFp"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fpname = Column(String(50), comment="被分配人姓名")
    jlid = Column(Integer, index=True, comment="奖励记录 id -> jcjiangli.id")
    bmid = Column(Integer, comment="部门 id")
    fpjine = Column(MONEY, comment="分配金额")
    uname = Column(String(50), comment="操作人")
    utime = Column(DateTime, comment="操作时间")
    xmu = Column(String(50), comment="项目")

    def to_dict(self):
        return {
            "id": self.id,
            "fpname": _s(self.fpname),
            "jlid": self.jlid,
            "bmid": self.bmid,
            "uname": _s(self.uname),
            "utime": _dt(self.utime),
            "xmu": _s(self.xmu),
        }
