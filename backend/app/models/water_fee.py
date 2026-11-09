"""水费系统(特殊群体水费优惠管理)模型。表名/字段沿用旧库 db_plan,废弃旧 *T 字符串辅助列,日期用正规列。"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.db.session import Base


def _fmt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _fmt_day(value):
    # 优惠起止/受理等按年月管理的日期,展示到日即可(旧系统展示月,由前端控制)
    return value.strftime("%Y-%m-%d") if value else None


class Shuifeixitong(Base):
    """用水户优惠档案主表(沿用旧库 shuifeixitong)。"""

    __tablename__ = "shuifeixitong"
    __table_args__ = (Index("ix_sft_nd", "nd"), Index("ix_sft_yonghuhao", "yonghuhao"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    shi = Column(String(50), default="", comment="市")
    quxian = Column(String(50), default="", comment="区县")
    xiangzhen = Column(String(50), default="", comment="乡镇")
    cun = Column(String(100), default="", comment="村")
    shixiang = Column(String(100), default="", comment="事项(如低保户等群体类别)")
    xingming = Column(String(50), default="", comment="姓名")
    sfz = Column(String(50), default="", comment="身份证号", index=True)
    juzhudizhi = Column(String(250), default="", comment="居住地址")
    dianhua = Column(String(150), default="", comment="电话")
    kaihuming = Column(String(150), default="", comment="开户名")
    yinhangzhanghao = Column(String(150), default="", comment="银行账号")
    kaihuhang = Column(String(150), default="", comment="开户行")
    kaihushenfenzheng = Column(String(150), default="", comment="开户身份证")
    yinhangbeizhu = Column(String(150), default="", comment="银行备注")
    ksbriqi = Column(DateTime, nullable=True, comment="保障开始年月")
    jsbriqi = Column(DateTime, nullable=True, comment="保障结束年月")
    tekunlei = Column(String(150), default="", comment="特困类别")
    gongyangfangshi = Column(String(150), default="", comment="供水方式")
    gongyangjigou = Column(String(150), default="", comment="供水机构")
    bm = Column(String(100), default="", comment="营业所名(导入文件原文)")
    caozuo = Column(String(50), default="", comment="最后操作人")
    caozuoriqi = Column(DateTime, nullable=True, comment="最后操作日期")
    yonghuhao = Column(String(150), default="", comment="用户号(唯一必填标识)")
    qitayongshui = Column(String(150), default="", comment="其他用水情况")
    beizhu = Column(Text, nullable=True, comment="备注")
    shouliriqi = Column(DateTime, nullable=True, comment="受理日期")
    youhuiksriqi = Column(DateTime, nullable=True, comment="优惠开始年月")
    youhuijsriqi = Column(DateTime, nullable=True, comment="优惠结束年月")
    wushuifeihetui = Column(DateTime, nullable=True, comment="污水费核退时间")
    daoruqingkuang = Column(String(150), default="", comment="系统导入情况")
    fanhuiminzhengju = Column(String(100), default="", comment="返民政局情况")
    guitaishouli = Column(String(150), default="", comment="柜台受理情况")
    nd = Column(Integer, nullable=True, comment="年度")
    bmid = Column(Integer, nullable=True, comment="部门id(关联 departments 表;导入按 bm+营业所 名称映射)")
    yueshu = Column(Integer, nullable=True, comment="优惠月数")
    biaoming = Column(String(100), default="", comment="导入Excel表名")
    wenjianxuhao = Column(Integer, nullable=True, comment="导入Excel文件序号列")
    quxiaoriqi = Column(DateTime, nullable=True, comment="取消日期(非空即已取消)")

    def to_dict(self):
        return {
            "id": self.id, "shi": self.shi, "quxian": self.quxian, "xiangzhen": self.xiangzhen,
            "cun": self.cun, "shixiang": self.shixiang, "xingming": self.xingming, "sfz": self.sfz,
            "juzhudizhi": self.juzhudizhi, "dianhua": self.dianhua, "kaihuming": self.kaihuming,
            "yinhangzhanghao": self.yinhangzhanghao, "kaihuhang": self.kaihuhang,
            "kaihushenfenzheng": self.kaihushenfenzheng, "yinhangbeizhu": self.yinhangbeizhu,
            "ksbriqi": _fmt_day(self.ksbriqi), "jsbriqi": _fmt_day(self.jsbriqi),
            "tekunlei": self.tekunlei, "gongyangfangshi": self.gongyangfangshi,
            "gongyangjigou": self.gongyangjigou, "bm": self.bm, "caozuo": self.caozuo,
            "caozuoriqi": _fmt(self.caozuoriqi), "yonghuhao": self.yonghuhao,
            "qitayongshui": self.qitayongshui, "beizhu": self.beizhu,
            "shouliriqi": _fmt_day(self.shouliriqi), "youhuiksriqi": _fmt_day(self.youhuiksriqi),
            "youhuijsriqi": _fmt_day(self.youhuijsriqi), "wushuifeihetui": _fmt_day(self.wushuifeihetui),
            "daoruqingkuang": self.daoruqingkuang, "fanhuiminzhengju": self.fanhuiminzhengju,
            "guitaishouli": self.guitaishouli, "nd": self.nd, "bmid": self.bmid, "yueshu": self.yueshu,
            "biaoming": self.biaoming, "wenjianxuhao": self.wenjianxuhao,
            "quxiaoriqi": _fmt_day(self.quxiaoriqi),
        }


class ShuifeixitongBiandong(Base):
    """变动历史记录(沿用旧库 shuifeixitongbiandong,zhuid 指向主表)。"""

    __tablename__ = "shuifeixitongbiandong"
    __table_args__ = (Index("ix_sftbd_zhuid", "zhuid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    zhuid = Column(Integer, nullable=True, comment="主表id,对应 shuifeixitong.id")
    biandongriqi = Column(DateTime, nullable=True, comment="变动日期")
    yonghuhao = Column(String(150), default="", comment="用户号")
    qitayongshui = Column(String(150), default="", comment="其他用水情况")
    beizhu = Column(Text, nullable=True, comment="备注")
    youhuiksriqi = Column(DateTime, nullable=True, comment="优惠开始年月")
    youhuijsriqi = Column(DateTime, nullable=True, comment="优惠结束年月")
    wushuifeihetui = Column(DateTime, nullable=True, comment="污水费核退时间")
    daoruqingkuang = Column(String(150), default="", comment="系统导入情况")
    fanhuiminzhengju = Column(String(100), default="", comment="返民政局情况")
    guitaishouli = Column(String(150), default="", comment="柜台受理情况")
    yueshu = Column(Integer, nullable=True, comment="优惠月数")
    caozuo = Column(String(150), default="", comment="操作人")
    shoulishijian = Column(DateTime, nullable=True, comment="受理时间")
    juzhudizhi = Column(String(250), default="", comment="居住地址")

    def to_dict(self):
        return {
            "id": self.id, "zhuid": self.zhuid, "biandongriqi": _fmt(self.biandongriqi),
            "yonghuhao": self.yonghuhao, "qitayongshui": self.qitayongshui, "beizhu": self.beizhu,
            "youhuiksriqi": _fmt_day(self.youhuiksriqi), "youhuijsriqi": _fmt_day(self.youhuijsriqi),
            "wushuifeihetui": _fmt_day(self.wushuifeihetui), "daoruqingkuang": self.daoruqingkuang,
            "fanhuiminzhengju": self.fanhuiminzhengju, "guitaishouli": self.guitaishouli,
            "yueshu": self.yueshu, "caozuo": self.caozuo, "shoulishijian": _fmt(self.shoulishijian),
            "juzhudizhi": self.juzhudizhi,
        }


class ShuifeixitongQuxiao(Base):
    """取消名单表(沿用旧库 shuifeixitongquxiao,主表字段副本+取消/审核存档列;审核流程旧系统未实现,列仅存档)。"""

    __tablename__ = "shuifeixitongquxiao"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shi = Column(String(50), default="", comment="市")
    quxian = Column(String(50), default="", comment="区县")
    xiangzhen = Column(String(50), default="", comment="乡镇")
    cun = Column(String(100), default="", comment="村")
    shixiang = Column(String(100), default="", comment="事项")
    xingming = Column(String(50), default="", comment="姓名")
    sfz = Column(String(50), default="", comment="身份证号", index=True)
    juzhudizhi = Column(String(250), default="", comment="居住地址")
    dianhua = Column(String(150), default="", comment="电话")
    kaihuming = Column(String(150), default="", comment="开户名")
    yinhangzhanghao = Column(String(150), default="", comment="银行账号")
    kaihuhang = Column(String(150), default="", comment="开户行")
    kaihushenfenzheng = Column(String(150), default="", comment="开户身份证")
    yinhangbeizhu = Column(String(150), default="", comment="银行备注")
    ksbriqi = Column(DateTime, nullable=True, comment="保障开始年月")
    jsbriqi = Column(DateTime, nullable=True, comment="保障结束年月")
    tekunlei = Column(String(150), default="", comment="特困类别")
    gongyangfangshi = Column(String(150), default="", comment="供水方式")
    gongyangjigou = Column(String(150), default="", comment="供水机构")
    bm = Column(String(150), default="", comment="营业所名")
    caozuo = Column(String(150), default="", comment="操作人")
    caozuoriqi = Column(DateTime, nullable=True, comment="操作日期")
    yonghuhao = Column(String(150), default="", comment="用户号")
    qitayongshui = Column(String(150), default="", comment="其他用水情况")
    beizhu = Column(Text, nullable=True, comment="备注")
    shouliriqi = Column(DateTime, nullable=True, comment="受理日期")
    youhuiksriqi = Column(DateTime, nullable=True, comment="优惠开始年月")
    youhuijsriqi = Column(DateTime, nullable=True, comment="优惠结束年月")
    wushuifeihetui = Column(DateTime, nullable=True, comment="污水费核退时间")
    daoruqingkuang = Column(String(150), default="", comment="系统导入情况")
    fanhuiminzhengju = Column(String(100), default="", comment="返民政局情况")
    guitaishouli = Column(String(150), default="", comment="柜台受理情况")
    nd = Column(Integer, nullable=True, comment="年度", index=True)
    bmid = Column(Integer, nullable=True, comment="部门id")
    yueshu = Column(Integer, nullable=True, comment="优惠月数")
    biaoming = Column(String(100), default="", comment="导入Excel表名")
    wenjianxuhao = Column(Integer, nullable=True, comment="文件序号")
    quxiaoyuanyin = Column(String(500), default="", comment="取消原因")
    quxiaoren = Column(String(50), default="", comment="取消人")
    quxiaoriqi = Column(DateTime, nullable=True, comment="取消日期")
    yuanyinid = Column(Integer, nullable=True, comment="取消原因id(存档列)")
    quxiaoshenheren = Column(String(50), default="", comment="取消审核人(存档列,未实现流程)")
    quxiaoshenheshijian = Column(DateTime, nullable=True, comment="取消审核时间(存档列,未实现流程)")
    quxiaozhuangtai = Column(String(50), default="", comment="取消状态(存档列,未实现流程)")

    def to_dict(self):
        return {
            "id": self.id, "shi": self.shi, "quxian": self.quxian, "xiangzhen": self.xiangzhen,
            "cun": self.cun, "shixiang": self.shixiang, "xingming": self.xingming, "sfz": self.sfz,
            "juzhudizhi": self.juzhudizhi, "dianhua": self.dianhua, "kaihuming": self.kaihuming,
            "yinhangzhanghao": self.yinhangzhanghao, "kaihuhang": self.kaihuhang,
            "kaihushenfenzheng": self.kaihushenfenzheng, "yinhangbeizhu": self.yinhangbeizhu,
            "ksbriqi": _fmt_day(self.ksbriqi), "jsbriqi": _fmt_day(self.jsbriqi),
            "tekunlei": self.tekunlei, "gongyangfangshi": self.gongyangfangshi,
            "gongyangjigou": self.gongyangjigou, "bm": self.bm, "caozuo": self.caozuo,
            "caozuoriqi": _fmt(self.caozuoriqi), "yonghuhao": self.yonghuhao,
            "qitayongshui": self.qitayongshui, "beizhu": self.beizhu,
            "shouliriqi": _fmt_day(self.shouliriqi), "youhuiksriqi": _fmt_day(self.youhuiksriqi),
            "youhuijsriqi": _fmt_day(self.youhuijsriqi), "wushuifeihetui": _fmt_day(self.wushuifeihetui),
            "daoruqingkuang": self.daoruqingkuang, "fanhuiminzhengju": self.fanhuiminzhengju,
            "guitaishouli": self.guitaishouli, "nd": self.nd, "bmid": self.bmid, "yueshu": self.yueshu,
            "biaoming": self.biaoming, "wenjianxuhao": self.wenjianxuhao,
            "quxiaoyuanyin": self.quxiaoyuanyin, "quxiaoren": self.quxiaoren,
            "quxiaoriqi": _fmt_day(self.quxiaoriqi), "yuanyinid": self.yuanyinid,
            "quxiaoshenheren": self.quxiaoshenheren,
            "quxiaoshenheshijian": _fmt(self.quxiaoshenheshijian),
            "quxiaozhuangtai": self.quxiaozhuangtai,
        }


class ShuifeixitongLog(Base):
    """字段级修改日志(沿用旧库 shuifeixitong_log)。source: shuifeixitong=主表, shuifeixitongbiandong=变动表。"""

    __tablename__ = "shuifeixitong_log"
    __table_args__ = (Index("ix_sftlog_main", "main_id", "source"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    main_id = Column(Integer, nullable=True, comment="主表或变动表记录id")
    field_name = Column(String(50), default="", comment="字段中文名")
    old_value = Column(Text, nullable=True, comment="旧值")
    new_value = Column(Text, nullable=True, comment="新值")
    update_user = Column(String(150), default="", comment="操作人")
    update_time = Column(DateTime, nullable=True, comment="操作时间")
    source = Column(String(50), default="", comment="记录来源:shuifeixitong主表/shuifeixitongbiandong变动表")

    def to_dict(self):
        return {
            "id": self.id, "main_id": self.main_id, "field_name": self.field_name,
            "old_value": self.old_value, "new_value": self.new_value,
            "update_user": self.update_user, "update_time": _fmt(self.update_time),
            "source": self.source,
        }
