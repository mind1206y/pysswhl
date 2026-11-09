"""年度计划模块数据模型(照旧 db_plan 复刻)。

覆盖旧系统的 4 个页面:
- 正式计划 gxdxljihua      -> gx_gxgz / gx_jindu / gx_user_gxgz / gx_jilu / gx_jiluTupian
- 实施单表 jhssdb          -> jh_ssdb
- 实施汇总 jhsshz          -> jh_ssdb(同表) + shuifeixitong_log
- 营业所发起 jhyyfaqi      -> jh_yyfq + jh_ssdbpz(上报历史快照)

表名、列名沿用旧库,便于历史数据平移。用户/部门外键列保留旧 id 数值,
另加 *name 快照列:新系统用户表是重建的,旧用户名无法全部映射,
但列表/抽屉需要按旧名展示,因此导入时把 bb_user.username 写入快照列。
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Index, Integer, Numeric, String, Text

from app.db.session import Base


def _dt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return None


def _d(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return None


class GxGxgz(Base):
    """正式计划主表(旧 gx_gxgz)。金额单位:元。"""

    __tablename__ = "gx_gxgz"

    id = Column(Integer, primary_key=True, autoincrement=True)
    xh = Column(String(50), comment="计划号")
    name = Column(Text, comment="项目名称")
    bz = Column(Text, comment="项目说明")
    jine = Column(Float, comment="计划总投资(元)")
    lb = Column(String(50), index=True, comment="计划类别")
    zb = Column(String(50), comment="主办单位")
    fzr = Column(String(50), comment="负责人")
    bm = Column(String(50), comment="所属部门名称")
    nd = Column(Integer, index=True, comment="年度")
    ssusers = Column(String(200), comment="已关注用户名,| 分隔")
    rongyu = Column(String(50), comment="最新进度/荣誉")
    zongji = Column(Numeric(18, 4), comment="总付(元)")
    bmid = Column(Integer, index=True, comment="所属部门 id -> departments.id")
    xmbz = Column(String(450), comment="项目备注")
    nxuhao = Column(Integer, comment="数字序号")
    zgy = Column(String(50), index=True, comment="专管员姓名")
    zbj = Column(Numeric(18, 2), comment="质保金")
    zbjrq = Column(Date, comment="质保金到期日期")
    zbjdjr = Column(String(50), comment="质保金登记人")
    zbjdjriqi = Column(DateTime, comment="质保金登记日期")
    khbj = Column(Boolean, default=False, nullable=False, comment="考核标记")

    def to_dict(self):
        return {
            "id": self.id,
            "xh": self.xh or "",
            "name": self.name or "",
            "bz": self.bz or "",
            "jine": self.jine,
            "lb": self.lb or "",
            "zb": self.zb or "",
            "fzr": self.fzr or "",
            "bm": self.bm or "",
            "nd": self.nd,
            "ssusers": self.ssusers or "",
            "rongyu": self.rongyu or "",
            "zongji": float(self.zongji) if self.zongji is not None else None,
            "bmid": self.bmid,
            "xmbz": self.xmbz or "",
            "nxuhao": self.nxuhao,
            "zgy": self.zgy or "",
            "zbj": float(self.zbj) if self.zbj is not None else None,
            "zbjrq": _d(self.zbjrq),
            "zbjdjr": self.zbjdjr or "",
            "zbjdjriqi": _dt(self.zbjdjriqi),
            "khbj": bool(self.khbj),
        }


class GxJindu(Base):
    """进度状态字典(旧 gx_jindu)。value 10~100 用于进度条,1000+ 为补充状态。"""

    __tablename__ = "gx_jindu"

    id = Column(Integer, primary_key=True, autoincrement=True)
    leixing = Column(String(50), comment="进度类型")
    value = Column(Integer, comment="百分比值")

    def to_dict(self):
        return {"id": self.id, "leixing": self.leixing or "", "value": self.value}


class GxUserGxgz(Base):
    """计划关注人(旧 gx_user_gxgz)。"""

    __tablename__ = "gx_user_gxgz"

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer, index=True, comment="关注人旧 bb_user.id / 新 users.id")
    gxgzid = Column(Integer, index=True, comment="计划 id -> gx_gxgz.id")
    rongyu1 = Column(String(50))
    rongyu2 = Column(String(50))
    username = Column(String(50), index=True, comment="关注人姓名快照")

    def to_dict(self):
        return {
            "id": self.id,
            "userid": self.userid,
            "gxgzid": self.gxgzid,
            "username": self.username or "",
        }


class GxJilu(Base):
    """计划进度记录(旧 gx_jilu)。"""

    __tablename__ = "gx_jilu"

    id = Column(Integer, primary_key=True, autoincrement=True)
    miaoshu = Column(String(250), comment="描述")
    beizhu = Column(String(250), comment="备注")
    caozuotime = Column(DateTime, comment="操作时间")
    riqi = Column(Date, index=True, comment="进度日期")
    guanzhuid = Column(Integer, index=True, comment="关注记录 id -> gx_user_gxgz.id")
    zhuangtaiid = Column(Integer, index=True, comment="进度状态 id -> gx_jindu.id")
    fukuan = Column(Float, comment="付款金额(元)")
    jindu = Column(String(250), comment="遗留文本进度")

    def to_dict(self):
        return {
            "id": self.id,
            "miaoshu": self.miaoshu or "",
            "beizhu": self.beizhu or "",
            "caozuotime": _dt(self.caozuotime),
            "riqi": _d(self.riqi),
            "guanzhuid": self.guanzhuid,
            "zhuangtaiid": self.zhuangtaiid,
            "fukuan": self.fukuan,
        }


class GxJiluTupian(Base):
    """进度记录附件(旧 gx_jiluTupian)。url 为旧服务器相对路径。"""

    __tablename__ = "gx_jiluTupian"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(250))
    jiuid = Column(Integer, index=True, comment="进度记录 id -> gx_jilu.id")

    def to_dict(self):
        return {"id": self.id, "url": self.url or "", "jiuid": self.jiuid}


class JhYyfq(Base):
    """营业所发起计划(旧 jh_yyfq)。金额单位:万元。"""

    __tablename__ = "jh_yyfq"

    id = Column(Integer, primary_key=True, autoincrement=True)
    faqiname = Column(String(500), index=True, comment="项目名称")
    bz = Column(Text, comment="项目说明")
    jine = Column(Float, comment="计划总投资(万元)")
    zgy = Column(Integer, index=True, comment="专管员旧 bb_user.id")
    zgy_name = Column(String(50), index=True, comment="专管员姓名快照")
    jhlb = Column(String(50), index=True, comment="计划类别")
    zt = Column(String(50), index=True, comment="状态")
    opid = Column(Integer, index=True, comment="发起人旧 bb_user.id")
    opname = Column(String(50), comment="发起人姓名快照")
    niandu = Column(Integer, index=True, comment="年度")
    bmid = Column(Integer, index=True, comment="所属部门 id")
    fqtimep = Column(DateTime, comment="最后操作时间")
    lastop = Column(String(50), comment="最后操作人")
    beginTime = Column(DateTime, comment="初始日期")
    startjine = Column(Float, comment="年初金额(万元)")
    zongtouzi = Column(Float, comment="本年计划投资(万元)")
    kgny = Column(String(20), comment="开工年月")
    jgny = Column(String(20), comment="竣工年月")
    xjxl = Column(String(10), comment="新建/续建")

    def to_dict(self):
        return {
            "id": self.id,
            "faqiname": self.faqiname or "",
            "bz": self.bz or "",
            "jine": self.jine,
            "zgy": self.zgy,
            "zgy_name": self.zgy_name or "",
            "jhlb": self.jhlb or "",
            "zt": self.zt or "",
            "opid": self.opid,
            "opname": self.opname or "",
            "niandu": self.niandu,
            "bmid": self.bmid,
            "fqtimep": _dt(self.fqtimep),
            "lastop": self.lastop or "",
            "beginTime": _dt(self.beginTime),
            "startjine": self.startjine,
            "zongtouzi": self.zongtouzi,
            "kgny": self.kgny or "",
            "jgny": self.jgny or "",
            "xjxl": self.xjxl or "",
        }


class JhSsdb(Base):
    """实施单表 / 汇总共用主表(旧 jh_ssdb)。金额单位:万元。"""

    __tablename__ = "jh_ssdb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    xuhao = Column(String(50), comment="计划号/序号")
    daibanname = Column(String(500), index=True, comment="项目名称")
    bz = Column(Text, comment="项目说明")
    jine = Column(Float, comment="计划总投资(万元)")
    zb = Column(Integer, index=True, comment="主办部门 id")
    fzr = Column(String(50), comment="负责人")
    niandu = Column(Integer, index=True, comment="年度")
    jhlb = Column(String(50), index=True, comment="计划类别")
    zt = Column(String(50), index=True, comment="状态")
    zhuanguan = Column(Integer, index=True, comment="专管员旧 bb_user.id")
    zhuanguan_name = Column(String(50), index=True, comment="专管员姓名快照")
    opname = Column(String(50), comment="上报员")
    bumenid = Column(Integer, index=True, nullable=False, comment="所属部门 id")
    faqiid = Column(Integer, index=True, comment="营业所发起记录 id -> jh_yyfq.id")
    dbtimep = Column(DateTime, index=True, comment="最后操作时间")
    kstimep = Column(DateTime, comment="初始日期")
    pizhu = Column(String(500), comment="批注")
    lastop = Column(String(50), comment="最后操作人")
    nxuhao = Column(Integer, comment="数字序号")
    yincang = Column(String(50))
    leibie = Column(String(20), comment="小类别")
    startjine = Column(Float, comment="年初金额(万元)")
    zongtouzi = Column(Float, comment="本年计划投资(万元)")
    kgny = Column(String(20), comment="开工年月")
    jgny = Column(String(20), comment="竣工年月")
    xjxl = Column(String(10), comment="新建/续建")
    FlowInstanceId = Column(Integer)
    FlowStatus = Column(String(50))

    def to_dict(self):
        return {
            "id": self.id,
            "xuhao": self.xuhao or "",
            "daibanname": self.daibanname or "",
            "bz": self.bz or "",
            "jine": self.jine,
            "zb": self.zb,
            "fzr": self.fzr or "",
            "niandu": self.niandu,
            "jhlb": self.jhlb or "",
            "zt": self.zt or "",
            "zhuanguan": self.zhuanguan,
            "zhuanguan_name": self.zhuanguan_name or "",
            "opname": self.opname or "",
            "bumenid": self.bumenid,
            "faqiid": self.faqiid,
            "dbtimep": _dt(self.dbtimep),
            "kstimep": _dt(self.kstimep),
            "pizhu": self.pizhu or "",
            "lastop": self.lastop or "",
            "nxuhao": self.nxuhao,
            "leibie": self.leibie or "",
            "startjine": self.startjine,
            "zongtouzi": self.zongtouzi,
            "kgny": self.kgny or "",
            "jgny": self.jgny or "",
            "xjxl": self.xjxl or "",
        }


class JhSsdbPz(Base):
    """营业所上报历史快照(旧 jh_ssdbpz)。dbid 为旧库自增主键。"""

    __tablename__ = "jh_ssdbpz"

    dbid = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(Integer, index=True, comment="售水待办 id")
    xuhao = Column(String(50))
    daibanname = Column(String(500))
    bz = Column(Text)
    jine = Column(Float)
    zb = Column(Integer)
    fzr = Column(String(50))
    niandu = Column(Integer, index=True)
    jhlb = Column(String(50))
    zt = Column(String(50))
    zhuanguan = Column(Integer)
    zhuanguan_name = Column(String(50))
    opname = Column(String(50))
    bumenid = Column(Integer, nullable=False)
    faqiid = Column(Integer, index=True)
    dbtimep = Column(DateTime)
    kstimep = Column(DateTime)
    pizhu = Column(String(500))
    lastop = Column(String(50))
    nxuhao = Column(Integer)
    yincang = Column(String(50))
    leibie = Column(String(20))
    startjine = Column(Float)
    zongtouzi = Column(Float)
    kgny = Column(String(20))
    jgny = Column(String(20))
    xjxl = Column(String(10))


class ConsolTb(Base):
    """系统开关(旧 consolTb)。conName 为开关名,val 为开关值。"""

    __tablename__ = "consol_tb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conName = Column(String(50), unique=True, index=True)
    val = Column(Boolean, default=False)
    intval = Column(Integer)
