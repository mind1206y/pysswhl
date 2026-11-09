"""加班申请审批模块模型(表名/字段沿用旧库 db_plan.dbo.overtime_*,见 docs/数据迁移约定.md)。

旧系统共 12 张 overtime_* 表,本文件全部建模,包含后期 ALTER 追加的列:
- overtime_apply: verify_time / verify_user_id / settle_type
- overtime_apply_detail: settle_type
- overtime_time_entry: is_full_day / shift_type
- overtime_dept / overtime_comp_leave 为后期整表新建

数据关系: Apply(申请单/个人记录头) -> Detail(人员维度) -> TimeEntry(加班时段)。
record_type='personal' 的是个人记录头; 另有一类"独立个人明细"没有头部(apply_id=NULL),
由批量新建/单条录入产生,查询时必须同时覆盖两种载体。

部门 id 说明(重要):
- overtime_dept 是旧系统自建的"加班部门镜像树",本模块保留原 id 空间,
  bb_bumen_id / apply_dept_id / parent_id 都指向 overtime_dept.id,迁移时不需要改。
- overtime_dept.sys_bumen_id / overtime_approval_level.mapped_bumen_id /
  overtime_approver.scope_bumen_id 才是旧 bb_bumen.id,迁移时用
  migration_reports/department_map.json 的 bmid_map 重映射到新 departments.id。
  新系统做数据权限时,通过 sys_bumen_id 与 dept_scope_ids() 的 departments.id 对齐。
- 各表 *user_id 是旧 bb_user.id,迁移时按 username 生成 user_map 重映射到新 users.id。

不建物理外键:旧库数据可能存在悬挂引用,且导入顺序难以保证;只建索引,由业务层保证一致性。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, DateTime, Index, Integer, Numeric, String

from app.db.session import Base


def _d(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, (date, datetime)) else None


def _dt(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else None


def _n(value):
    return float(value) if isinstance(value, Decimal) else value


class OvertimePersonnel(Base):
    """加班人员池(旧库 overtime_personnel)。"""

    __tablename__ = "overtime_personnel"
    __table_args__ = (
        Index("ix_otp_bumen", "bb_bumen_id"),
        Index("ix_otp_user", "bb_user_id"),
        Index("ix_otp_active", "is_active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, default="", comment="姓名")
    employee_no = Column(String(50), default="", comment="工号")
    bb_user_id = Column(Integer, nullable=True, comment="绑定系统用户(新库 users.id)")
    bb_bumen_id = Column(Integer, nullable=True, comment="加班部门(overtime_dept.id)")
    parent_id = Column(Integer, nullable=True, comment="人事链上级人员 id")
    daily_wage = Column(Numeric(10, 2), default=0, comment="日工资基数")
    is_active = Column(Boolean, default=True, nullable=False)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "employee_no": self.employee_no or "",
            "bb_user_id": self.bb_user_id,
            "bb_bumen_id": self.bb_bumen_id,
            "parent_id": self.parent_id,
            "daily_wage": _n(self.daily_wage),
            "is_active": bool(self.is_active),
            "create_time": _dt(self.create_time),
        }


class OvertimeDept(Base):
    """加班部门镜像树(旧库 overtime_dept)。full_path 用 / 分隔,根 level=1。"""

    __tablename__ = "overtime_dept"
    __table_args__ = (
        Index("ix_otd_parent", "parent_id"),
        Index("ix_otd_sys", "sys_bumen_id"),
        Index("ix_otd_path", "full_path"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, default="")
    parent_id = Column(Integer, nullable=True)
    sys_bumen_id = Column(Integer, nullable=True, comment="镜像的系统部门(新库 departments.id)")
    is_field = Column(Boolean, nullable=False, default=False,
                      comment="基层营业所标记:旧 bb_bumen._parentId==1,审批路由 field/hq 用")
    full_path = Column(String(200), nullable=False, default="")
    level = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "parent_id": self.parent_id,
            "sys_bumen_id": self.sys_bumen_id,
            "is_field": bool(self.is_field),
            "full_path": self.full_path or "",
            "level": self.level,
            "sort_order": self.sort_order,
            "is_active": bool(self.is_active),
            "create_time": _dt(self.create_time),
        }


class OvertimeApprovalLevel(Base):
    """审批层级(旧库 overtime_approval_level)。"""

    __tablename__ = "overtime_approval_level"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level_name = Column(String(100), nullable=False, default="")
    level_order = Column(Integer, nullable=False, default=0)
    parent_id = Column(Integer, nullable=True)
    dept_offset = Column(Integer, nullable=False, default=0, comment="-1指定部门 0本级 1~5上溯")
    mapped_bumen_id = Column(Integer, nullable=True, comment="指定部门(新库 departments.id)")
    approval_mode = Column(String(20), default="single", comment="single/any/all")
    route_type = Column(String(20), default="all", comment="all/field/hq")
    is_active = Column(Boolean, nullable=False, default=True)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "level_name": self.level_name or "",
            "level_order": self.level_order,
            "parent_id": self.parent_id,
            "dept_offset": self.dept_offset,
            "mapped_bumen_id": self.mapped_bumen_id,
            "approval_mode": self.approval_mode or "single",
            "route_type": self.route_type or "all",
            "is_active": bool(self.is_active),
            "create_time": _dt(self.create_time),
        }


class OvertimeApprover(Base):
    """审批人(旧库 overtime_approver)。work_type 在旧建表脚本缺失但实体/EDMX 中存在。"""

    __tablename__ = "overtime_approver"
    __table_args__ = (Index("ix_ota_level", "approval_level_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    bb_user_id = Column(Integer, nullable=True, comment="新库 users.id")
    approval_level_id = Column(Integer, nullable=True)
    scope_bumen_id = Column(Integer, nullable=True, comment="管辖部门(新库 departments.id),空=全局")
    work_type = Column(String(50), nullable=True, comment="加班类别,空=全部")
    is_active = Column(Boolean, nullable=False, default=True)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "bb_user_id": self.bb_user_id,
            "approval_level_id": self.approval_level_id,
            "scope_bumen_id": self.scope_bumen_id,
            "work_type": self.work_type or "",
            "is_active": bool(self.is_active),
            "create_time": _dt(self.create_time),
        }


class OvertimeMonthConfig(Base):
    """月份配置(旧库 overtime_month_config)。

    config_type='detail'/'apply' 用 start_day/end_day(默认 26/25);
    config_type='approval_switch' 只用 is_active 表示审批流开关。
    """

    __tablename__ = "overtime_month_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_type = Column(String(20), nullable=False, default="")
    start_day = Column(Integer, nullable=False, default=26)
    end_day = Column(Integer, nullable=False, default=25)
    description = Column(String(100), default="")
    is_active = Column(Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "config_type": self.config_type or "",
            "start_day": self.start_day,
            "end_day": self.end_day,
            "description": self.description or "",
            "is_active": bool(self.is_active),
        }


class OvertimeApply(Base):
    """加班申请单 / 个人记录头(旧库 overtime_apply)。"""

    __tablename__ = "overtime_apply"
    __table_args__ = (
        Index("ix_ota_status", "status"),
        Index("ix_ota_month", "apply_month"),
        Index("ix_ota_rtype_status", "record_type", "status"),
        Index("ix_ota_dept", "apply_dept_id"),
        Index("ix_ota_user", "apply_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    apply_no = Column(String(50), nullable=False, default="", unique=True, comment="GR-/JB- 前缀编号")
    record_type = Column(String(20), nullable=False, default="apply", comment="apply/personal")
    apply_month = Column(String(6), nullable=False, default="", comment="yyyyMM 所属月份(核算月)")
    work_type = Column(String(50), nullable=False, default="")
    apply_user_id = Column(Integer, nullable=True, comment="制单人(新库 users.id)")
    apply_dept_id = Column(Integer, nullable=True, comment="加班部门(overtime_dept.id)")
    apply_date = Column(DateTime, nullable=True)
    total_hours = Column(Numeric(10, 2), default=0)
    status = Column(String(20), default="draft")
    remark = Column(String(500), default="", comment="可内嵌 __SRC__[...] 源明细 id 编码")
    create_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, nullable=True)
    verify_time = Column(DateTime, nullable=True)
    verify_user_id = Column(Integer, nullable=True)
    settle_type = Column(String(20), nullable=False, default="加班费", comment="加班费/补休")

    def to_dict(self):
        return {
            "id": self.id,
            "apply_no": self.apply_no or "",
            "record_type": self.record_type or "apply",
            "apply_month": self.apply_month or "",
            "work_type": self.work_type or "",
            "apply_user_id": self.apply_user_id,
            "apply_dept_id": self.apply_dept_id,
            "apply_date": _d(self.apply_date),
            "total_hours": _n(self.total_hours),
            "status": self.status or "",
            "remark": self.remark or "",
            "create_time": _dt(self.create_time),
            "update_time": _dt(self.update_time),
            "verify_time": _dt(self.verify_time),
            "verify_user_id": self.verify_user_id,
            "settle_type": self.settle_type or "加班费",
        }


class OvertimeApplyDetail(Base):
    """申请单人员明细(旧库 overtime_apply_detail)。apply_id 为空=独立个人记录。"""

    __tablename__ = "overtime_apply_detail"
    __table_args__ = (
        Index("ix_otad_apply", "apply_id"),
        Index("ix_otad_personnel", "personnel_id"),
        Index("ix_otad_month", "apply_month"),
        Index("ix_otad_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    apply_id = Column(Integer, nullable=True)
    personnel_id = Column(Integer, nullable=True)
    accounting_month = Column(String(6), nullable=False, default="")
    total_hours = Column(Numeric(10, 2), default=0)
    sort_order = Column(Integer, default=0)
    work_type = Column(String(50), default="")
    apply_month = Column(String(6), default="")
    apply_user_id = Column(Integer, nullable=True)
    create_time = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=True, comment="独立个人记录: draft/submitted/grouped")
    settle_type = Column(String(20), nullable=False, default="加班费")

    def to_dict(self):
        return {
            "id": self.id,
            "apply_id": self.apply_id,
            "personnel_id": self.personnel_id,
            "accounting_month": self.accounting_month or "",
            "total_hours": _n(self.total_hours),
            "sort_order": self.sort_order,
            "work_type": self.work_type or "",
            "apply_month": self.apply_month or "",
            "apply_user_id": self.apply_user_id,
            "create_time": _dt(self.create_time),
            "status": self.status or "",
            "settle_type": self.settle_type or "加班费",
        }


class OvertimeTimeEntry(Base):
    """加班时段明细(旧库 overtime_time_entry)。"""

    __tablename__ = "overtime_time_entry"
    __table_args__ = (
        Index("ix_ote_detail", "detail_id"),
        Index("ix_ote_work_date", "work_date"),
        Index("ix_ote_month", "accounting_month"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    detail_id = Column(Integer, nullable=True)
    work_type = Column(String(50), nullable=False, default="")
    work_date = Column(Date, nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    raw_hours = Column(Numeric(10, 2), default=0, comment="原始时长")
    multiplier = Column(Numeric(4, 1), default=1.5)
    total_hours = Column(Numeric(10, 2), default=0, comment="折算时长=raw*multiplier")
    reason = Column(String(500), default="")
    daily_wage = Column(Numeric(10, 2), nullable=True)
    overtime_amount = Column(Numeric(10, 2), nullable=True)
    work_order_no = Column(String(50), default="")
    address = Column(String(200), default="")
    accounting_month = Column(String(6), default="")
    sort_order = Column(Integer, default=0)
    is_full_day = Column(Boolean, nullable=False, default=False)
    shift_type = Column(String(20), nullable=True, comment="白班/晚班/NULL")

    def to_dict(self):
        return {
            "id": self.id,
            "detail_id": self.detail_id,
            "work_type": self.work_type or "",
            "work_date": _d(self.work_date),
            "start_time": _dt(self.start_time),
            "end_time": _dt(self.end_time),
            "raw_hours": _n(self.raw_hours),
            "multiplier": _n(self.multiplier),
            "total_hours": _n(self.total_hours),
            "reason": self.reason or "",
            "daily_wage": _n(self.daily_wage),
            "overtime_amount": _n(self.overtime_amount),
            "work_order_no": self.work_order_no or "",
            "address": self.address or "",
            "accounting_month": self.accounting_month or "",
            "sort_order": self.sort_order,
            "is_full_day": bool(self.is_full_day),
            "shift_type": self.shift_type or "",
        }


class OvertimeApplyApproval(Base):
    """审批记录(旧库 overtime_apply_approval)。"""

    __tablename__ = "overtime_apply_approval"
    __table_args__ = (
        Index("ix_otaa_apply", "apply_id"),
        Index("ix_otaa_approver", "approver_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    apply_id = Column(Integer, nullable=True)
    step_order = Column(Integer, nullable=False, default=0)
    approval_level_id = Column(Integer, nullable=True)
    approver_id = Column(Integer, nullable=True, comment="审批人(新库 users.id)")
    status = Column(String(20), default="pending", comment="pending/approved/rejected/skipped")
    comment = Column(String(500), default="")
    approve_time = Column(DateTime, nullable=True)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "apply_id": self.apply_id,
            "step_order": self.step_order,
            "approval_level_id": self.approval_level_id,
            "approver_id": self.approver_id,
            "status": self.status or "",
            "comment": self.comment or "",
            "approve_time": _dt(self.approve_time),
            "create_time": _dt(self.create_time),
        }


class OvertimeCompLeave(Base):
    """补休登记(旧库 overtime_comp_leave)。"""

    __tablename__ = "overtime_comp_leave"
    __table_args__ = (Index("ix_otcl_personnel", "personnel_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    personnel_id = Column(Integer, nullable=True)
    leave_date = Column(Date, nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    hours = Column(Numeric(10, 2), nullable=False, default=0)
    leave_type = Column(String(20), default="全天")
    reason = Column(String(200), default="")
    create_user_id = Column(Integer, nullable=True)
    create_time = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "personnel_id": self.personnel_id,
            "leave_date": _d(self.leave_date),
            "start_time": _dt(self.start_time),
            "end_time": _dt(self.end_time),
            "hours": _n(self.hours),
            "leave_type": self.leave_type or "全天",
            "reason": self.reason or "",
            "create_user_id": self.create_user_id,
            "create_time": _dt(self.create_time),
        }


class OvertimeRecord(Base):
    """旧系统遗留表(旧库 overtime_record),当前业务未使用,保留以便历史数据完整迁移。"""

    __tablename__ = "overtime_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer, nullable=False, default=0)
    username = Column(String(50), nullable=False, default="")
    work_date = Column(Date, nullable=True)
    work_type = Column(Integer, nullable=False, default=0)
    remark = Column(String(200), default="")
    create_time = Column(DateTime, nullable=True)
    update_time = Column(DateTime, nullable=True)
    creater = Column(String(50), default="")


class OvertimeUser(Base):
    """旧系统遗留表(旧库 overtime_user),当前业务未使用。"""

    __tablename__ = "overtime_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), default="")
