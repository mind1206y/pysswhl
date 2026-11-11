"""初始化数据库:建库、建表、写入初始数据(管理员/角色/权限)。

用法:在 backend 目录下运行
    python -m scripts.init_db
"""

import pymysql
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import Base, SessionLocal, engine
from app.models.celou import CelouTb, CLdui  # noqa: F401  测漏成果
from app.models.contract import HtAdd, HtTp, HtZbSupplier  # noqa: F401  合同登记/归集
from app.models.finance import (  # noqa: F401  财务管理(固定资产/清理报告/物资采购申请 7 表)
    Wzcgsq, WzcgsqMx, ZcBaofeidan, ZcBaofeitp, ZcCw, ZcLb, ZcNd,
)
from app.models.gongdan import (  # noqa: F401  工单信息录入(热线工单镜像 + 2 张字典表)
    Gongdan, GongdanCaizhiDict, GongdanNeirongDict,
)
from app.models.ipadress import Ipadress, IpNetCreator  # noqa: F401  IP地址管理
from app.models.jiaban import Jiaban, JiabanAttachment, JiabanRenyuan  # noqa: F401  维抢修加班
from app.models.jcxt import (  # noqa: F401  稽查系统(jcxt/spjicha/jcdan/JcJl 8 张表)
    JcJcxx, JcPrintcolum, JcTupian, Jcdan, JcWzdw, JcWzlb, Jcjiangli, JcjiangliFp,
)
from app.models.jiesuandan import (  # noqa: F401  领料结算(结算单/明细/附件 3 张表)
    CailiaoFujian, JiesuanCailiao, JiesuanDetail,
)
from app.models.leak import LeakFile, LeakRecord  # noqa: F401  测漏笔记
from app.models.lingliao import LingLiao, LingLiaoDetail, LingLiaoFile  # noqa: F401  领料申请(3 表)
from app.models.material import (  # noqa: F401  工单材料库(材料/入库/领料/图片/工单 5 表)
    InStockRecord, MaterialImage, MaterialLibrary, MaterialRecord, WorkOrder,
)
from app.models.phone import (  # noqa: F401  手机管理(shouji 4 表 + sim 查号表)
    Shouji,
    ShoujiAttachment,
    ShoujiEditLog,
    ShoujiHuishou,
    Sim,
)
from app.models.plan import (  # noqa: F401  年度计划(正式计划/实施单表/汇总/营业所发起)
    ConsolTb, GxGxgz, GxJilu, GxJiluTupian, GxJindu, GxUserGxgz,
    JhSsdb, JhSsdbPz, JhYyfq,
)
from app.models.overtime import (  # noqa: F401  加班申请审批(12 张表)
    OvertimeApply,
    OvertimeApplyApproval,
    OvertimeApplyDetail,
    OvertimeApprovalLevel,
    OvertimeApprover,
    OvertimeCompLeave,
    OvertimeDept,
    OvertimeMonthConfig,
    OvertimePersonnel,
    OvertimeRecord,
    OvertimeTimeEntry,
    OvertimeUser,
)
from app.models.project import Gongchenggl  # noqa: F401  注册到 Base.metadata 以便 create_all 建表
from app.models.road_repair import (  # noqa: F401  路面修复管理(4 表 + 强修人员字典)
    Qiangxiurenyuan,
    RoadPrice,
    RoadRepair,
    RoadRepairAttachment,
    RoadRepairProgress,
)
from app.models.simcard import (  # noqa: F401  SIM 卡管理
    Feiyong, Linshi, SimCard, SimEditLog, SimTaocan, SimVpn, SimWangluo, SimZhuangtai,
)
from app.models.sms import SmsContact, SmsRecord  # noqa: F401  短信记录/联系人目录
from app.models.vehicle import (  # noqa: F401
    ClBaoxian, ClChe, ClChetupian, ClChuxian, ClCxTP, ClFeiyong, ClWeizhang, ClWxdan, ClWxdTP,
    ClWxdw, ClWxmx, OilCard, PlusOil, Tboil, Yongcherc, YongchercTP,
)
from app.models.water_fee import (  # noqa: F401
    Shuifeixitong,
    ShuifeixitongBiandong,
    ShuifeixitongLog,
    ShuifeixitongQuxiao,
)
from app.models.workorder import (  # noqa: F401  工单领料(gongdancailiao + 附件表)
    GongdanCailiao, WorkOrderAttachment,
)
from app.models.user import Department, Permission, Role, User

# (权限码, 名称, 分类) — 分类用于「角色权限」页面按模块分组展示,模块多时靠它导航
DEFAULT_PERMISSIONS = [
    ("system:user:manage", "用户管理", "系统管理"),
    ("system:dept:manage", "部门管理", "系统管理"),
    ("system:role:manage", "角色权限管理", "系统管理"),
    ("project:view", "工程查看", "工程管理"),
    ("project:manage", "工程管理", "工程管理"),
    ("waterfee:view", "特殊群体查看", "特殊群体管理"),
    ("waterfee:manage", "特殊群体管理", "特殊群体管理"),
    ("ipadress:view", "IP地址查看", "IP地址管理"),
    ("ipadress:manage", "IP地址管理", "IP地址管理"),
    ("vehicle:view", "车辆查看", "车辆业务"),
    ("vehicle:manage", "车辆管理", "车辆业务"),
    # 车辆保险:旧系统仅菜单控制访问,view 覆盖查询/增删改/导入/导出全部日常操作
    ("baoxian:view", "车辆保险查看", "车辆业务"),
    ("oilcard:view", "油卡查看", "车辆业务"),
    ("oilcard:manage", "油卡管理", "车辆业务"),
    ("plusoil:view", "加油明细查看", "车辆业务"),
    ("oiltj:view", "油量统计查看", "车辆业务"),
    # 车辆费用明细统计:旧系统仅菜单控制访问,只读报表,单个 view 码
    ("chelfytj:view", "车辆费用统计查看", "车辆业务"),
    ("repair:view", "车辆维修查看", "车辆业务"),
    ("repair:manage", "车辆维修管理", "车辆业务"),
    ("repair:audit", "车辆维修审批", "车辆业务"),
    ("phone:view", "手机管理查看", "手机管理"),
    ("phone:manage", "手机管理", "手机管理"),
    ("phone:huishou", "手机回收管理", "手机管理"),
    ("celou:view", "测漏成果查看", "测漏管理"),
    ("celou:manage", "测漏成果管理", "测漏管理"),
    ("leak:view", "测漏笔记查看", "测漏管理"),
    ("leak:manage", "测漏笔记管理", "测漏管理"),
    ("contract:view", "合同登记查看", "合同管理"),
    ("contract:manage", "合同登记管理", "合同管理"),
    ("contract:collect", "合同归集移交", "合同管理"),
    # 加班申请审批:菜单入口对全员开放(我的加班人人可用),下面 5 个权限码控制各 Tab 与后端写接口。
    # 旧系统 otherqx 的 admin / HR / 加班管理 三种标签在新系统折算为这些权限码,超管自动全有。
    ("overtime:view", "加班申请查看", "加班申请审批"),
    ("overtime:apply", "加班申请单管理", "加班申请审批"),
    ("overtime:verify", "加班核销管理", "加班申请审批"),
    ("overtime:hr", "加班汇总管理", "加班申请审批"),
    ("overtime:manage", "加班模块管理", "加班申请审批"),
    ("simcard:view", "SIM卡查看", "通信管理"),
    ("simcard:manage", "SIM卡管理", "通信管理"),
    ("simfee:view", "通信费查看", "通信管理"),
    # 稽查系统:旧系统按菜单控制访问,无细分权限,每个模块一个 view 码。
    ("jcxt:view", "稽查系统查看", "稽查管理"),
    ("spjicha:view", "审批稽查查看", "稽查管理"),
    ("jcdan:view", "稽查单查看", "稽查管理"),
    ("jcjl:view", "稽查奖励查看", "稽查管理"),
    # 路面修复管理:旧系统仅菜单控制访问,无细分权限,只设一个 view 码。
    ("roadrepair:view", "路面修复查看", "工程管理"),
    # 工单系统:材料库人人可查/入库/盘点,manage 对应旧 pdqx(user,"工单管理")
    ("material:view", "工单材料库查看", "工单系统"),
    ("material:manage", "工单材料库管理", "工单系统"),
    # 工单领料:旧系统仅菜单控制,view 覆盖日常全部操作;manage 单独管删除领料单(库存回滚)
    ("workorder:view", "工单领料查看", "工单系统"),
    ("workorder:manage", "工单领料管理", "工单系统"),
    # 领料申请:旧系统「领料单审核」折算为 audit;view 覆盖本人申请单全部日常操作,超管自动全有
    ("lingliao:view", "领料申请查看", "工单系统"),
    ("lingliao:audit", "领料申请审核", "工单系统"),
    # 领料结算:旧系统仅菜单控制,view 覆盖查询/新增/编辑本人单/删除本人单/明细/导出/打印/附件;
    # manage 只用于删除他人上传的附件(超管自动全有)
    ("jiesuandan:view", "领料结算查看", "工单系统"),
    ("jiesuandan:manage", "领料结算管理", "工单系统"),
    # 材料结算单查看:旧系统仅菜单控制,只读,单个 view 权限码
    ("jiesuan:view", "材料结算单查看", "工单系统"),
    # 工单信息录入:旧系统仅菜单控制,view 覆盖查询/新增/编辑/导出/字典/班组;
    # manage 单独守物理删除工单材料记录(不可恢复)
    ("gongdan:view", "工单信息录入查看", "工单系统"),
    ("gongdan:manage", "工单信息录入管理", "工单系统"),
    # 维抢修加班:旧系统仅菜单控制,view 覆盖记录/人员/导出/附件全部日常操作;
    # 删除类操作按旧逻辑限制为本人录入(记录按 username、附件按 operator_name)
    ("jiaban:view", "维抢修加班查看", "加班申请审批"),
    # 年度计划:四个页面分别授权;正式计划 manage 覆盖关注/进度/质保金/复制待办;
    # 汇总 admin 对应旧系统 otherqx 含 admin(复制到正式计划),
    # 营业所发起 summary 对应旧系统 otherqx 含「计划汇总」(跨部门只读查看)。
    ("plan:view", "正式计划查看", "年度计划"),
    ("plan:manage", "正式计划管理", "年度计划"),
    ("jhssdb:view", "实施单表查看", "年度计划"),
    ("jhssdb:manage", "实施单表管理", "年度计划"),
    ("jhsshz:view", "实施汇总查看", "年度计划"),
    ("jhsshz:manage", "实施汇总管理", "年度计划"),
    ("jhsshz:admin", "实施汇总管理员", "年度计划"),
    ("jhyyfaqi:view", "营业所发起查看", "年度计划"),
    ("jhyyfaqi:manage", "营业所发起管理", "年度计划"),
    ("jhyyfaqi:summary", "营业所发起计划汇总", "年度计划"),
    # 财务管理:旧系统三个模块都只有菜单级权限,各用一个 view 码覆盖查询/增删改/导入导出
    ("gdzc:view", "固定资产查看", "财务管理"),
    ("baofeizc:view", "清理报告查看", "财务管理"),
    ("wzcgsq:view", "物资采购申请查看", "财务管理"),
]


def create_database():
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()


def ensure_columns():
    """轻量迁移:create_all 不会修改已存在表的结构,这里补齐/清理字段。"""
    user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "must_change_password" not in user_cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) "
                "NOT NULL DEFAULT 0 COMMENT '登录后是否必须先修改初始密码'"
            ))
            print("已补列 users.must_change_password")
        if "failed_attempts" not in user_cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN failed_attempts INT NOT NULL DEFAULT 0 "
                "COMMENT '连续密码错误次数'"
            ))
            print("已补列 users.failed_attempts")
        if "locked_until" not in user_cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN locked_until DATETIME NULL "
                "COMMENT '账号锁定截止时间,空为未锁定'"
            ))
            print("已补列 users.locked_until")
        if "password_version" not in user_cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN password_version INT NOT NULL DEFAULT 0 "
                "COMMENT '密码哈希版本:0=bcrypt,1=Argon2id+pepper'"
            ))
            print("已补列 users.password_version")
        if "zw" not in user_cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN zw VARCHAR(50) NOT NULL DEFAULT '' "
                "COMMENT '职务(旧系统 bb_user.zw,如专管员)'"
            ))
            print("已补列 users.zw")
        if "department" in user_cols:
            # 部门已改为独立表 + 多对多关联:先把旧文本值迁移成关联,再删列
            old_rows = conn.execute(
                text("SELECT id, department FROM users WHERE department IS NOT NULL AND department <> ''")
            ).fetchall()
            for uid, dept_name in old_rows:
                conn.execute(text(
                    "INSERT IGNORE INTO departments (name, remark, created_at) "
                    "VALUES (:name, '由旧部门字段迁移', NOW())"
                ), {"name": dept_name})
                dept_id = conn.execute(
                    text("SELECT id FROM departments WHERE name = :name"), {"name": dept_name}
                ).scalar()
                conn.execute(text(
                    "INSERT IGNORE INTO user_department (user_id, department_id) VALUES (:uid, :did)"
                ), {"uid": uid, "did": dept_id})
            conn.execute(text("ALTER TABLE users DROP COLUMN department"))
            print(f"已迁移 {len(old_rows)} 条旧部门数据并删除 users.department 列")

    if "departments" in inspect(engine).get_table_names():
        dept_cols = {c["name"] for c in inspect(engine).get_columns("departments")}
        if "parent_id" not in dept_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE departments ADD COLUMN parent_id INT NULL COMMENT '上级部门id,空为顶级'"
                ))
            print("已补列 departments.parent_id")
        if "htdaihao" not in dept_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE departments ADD COLUMN htdaihao VARCHAR(20) NOT NULL DEFAULT '' "
                    "COMMENT '合同编号部门代号(如 ssgs)'"
                ))
            print("已补列 departments.htdaihao")
        if "xuhaotou" not in dept_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE departments ADD COLUMN xuhaotou INT NULL "
                    "COMMENT '旧系统部门排序号/计划编号前缀'"
                ))
            print("已补列 departments.xuhaotou")
        if "dnnum" not in dept_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE departments ADD COLUMN dnnum INT NOT NULL DEFAULT 0 "
                    "COMMENT '旧系统主办部门标记,>0 为主办部门'"
                ))
            print("已补列 departments.dnnum")
        if "zg" not in dept_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE departments ADD COLUMN zg VARCHAR(50) NOT NULL DEFAULT '' "
                    "COMMENT '部门负责人'"
                ))
            print("已补列 departments.zg")

    if "sim" in inspect(engine).get_table_names():
        # SIM 卡主表先由手机管理模型建表(字段偏短),这里按旧库最大长度补齐,
        # 避免长地点/用途写入时被截断或报 Data too long。
        sim_cols = {c["name"]: c for c in inspect(engine).get_columns("sim")}
        desired = {
            "kahao": 150, "xuliehao": 150, "imhao": 150, "ip": 150, "vpn": 150,
            "taocan": 150, "zt": 150, "yongtu": 350, "didian": 550,
            "wangluo": 120, "dengjiren": 120, "bianjiren": 120, "glren": 120,
            "syren": 120, "zhanghu": 150,
        }
        with engine.begin() as conn:
            for col, length in desired.items():
                if col not in sim_cols:
                    continue
                current_len = getattr(sim_cols[col]["type"], "length", None) or 0
                if current_len < length:
                    conn.execute(text(
                        f"ALTER TABLE sim MODIFY COLUMN `{col}` VARCHAR({length}) NULL"
                    ))
                    print(f"已扩展 sim.{col} 到 VARCHAR({length})")

    if "jh_ssdbpz" in inspect(engine).get_table_names():
        pz_cols = {c["name"]: c for c in inspect(engine).get_columns("jh_ssdbpz")}
        if "lastop" in pz_cols:
            current = getattr(pz_cols["lastop"]["type"], "length", None) or 0
            if current < 50:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE jh_ssdbpz MODIFY COLUMN lastop VARCHAR(50) NULL "
                        "COMMENT '最后操作人'"
                    ))
                print("已扩展 jh_ssdbpz.lastop 到 VARCHAR(50)")

    if "permissions" in inspect(engine).get_table_names():
        perm_cols = {c["name"] for c in inspect(engine).get_columns("permissions")}
        if "category" not in perm_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE permissions ADD COLUMN category VARCHAR(50) NOT NULL DEFAULT '' "
                    "COMMENT '所属分类,角色权限页面按此分组展示'"
                ))
            print("已补列 permissions.category")

    # 测漏成果:坐标内联编辑后记录修改人/时间
    if "celouTb" in inspect(engine).get_table_names():
        celou_cols = {c["name"] for c in inspect(engine).get_columns("celouTb")}
        if "xgusername" not in celou_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE celouTb ADD COLUMN xgusername VARCHAR(15) NOT NULL DEFAULT '' "
                    "COMMENT '坐标修改人'"
                ))
            print("已补列 celouTb.xgusername")
        if "xgdatetime" not in celou_cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE celouTb ADD COLUMN xgdatetime DATETIME NULL "
                    "COMMENT '坐标修改时间'"
                ))
            print("已补列 celouTb.xgdatetime")


def flag_initial_password_users():
    """仍在使用播种初始密码的账号(如 admin/admin123),自动打上强制改密标志。"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if admin and verify_password("admin123", admin.password_hash):
            if not admin.must_change_password:
                admin.must_change_password = True
                db.commit()
                print("admin 仍在使用初始密码 admin123,已设置下次登录强制修改")
        else:
            print("admin 已修改过密码或不存在,跳过")
    finally:
        db.close()


def main():
    create_database()
    Base.metadata.create_all(engine)
    ensure_columns()

    db = SessionLocal()
    try:
        for item in DEFAULT_PERMISSIONS:
            code, name = item[0], item[1]
            category = item[2] if len(item) > 2 else ""
            perm = db.query(Permission).filter(Permission.code == code).first()
            if not perm:
                db.add(Permission(code=code, name=name, category=category))
            else:
                # 名称/分类以代码登记为准:改了 DEFAULT_PERMISSIONS 后重跑 init_db 即同步
                if perm.name != name:
                    print(f"权限 {code} 名称已同步:「{perm.name}」→「{name}」")
                    perm.name = name
                if perm.category != category:
                    print(f"权限 {code} 分类已同步:「{perm.category}」→「{category}」")
                    perm.category = category
        db.commit()
        if not db.query(Role).filter(Role.code == "admin").first():
            db.add(Role(name="系统管理员", code="admin", remark="拥有系统管理权限"))
        if not db.query(Role).filter(Role.code == "common").first():
            db.add(Role(name="普通用户", code="common", remark="默认角色,暂无管理权限"))
        db.commit()

        if not db.query(User).filter(User.username == "admin").first():
            db.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    password_version=1,
                    real_name="系统管理员",
                    is_superuser=True,
                    is_active=True,
                    must_change_password=True,
                )
            )
            db.commit()
            print("已创建管理员账号  用户名: admin  密码: admin123 (首次登录将强制修改密码)")
        else:
            print("管理员账号已存在,跳过")
    finally:
        db.close()
    flag_initial_password_users()
    print("数据库初始化完成")


if __name__ == "__main__":
    main()
