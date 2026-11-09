from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import relationship

from app.db.session import Base

user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_department = Table(
    "user_department",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "department_id", Integer, ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True
    ),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True, comment="登录名")
    password_hash = Column(String(256), nullable=False, comment="密码哈希")
    password_version = Column(Integer, default=0, comment="密码哈希版本:0=bcrypt旧版,1=Argon2id+pepper")
    real_name = Column(String(50), default="", comment="姓名")
    phone = Column(String(20), default="", comment="手机号")
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_superuser = Column(Boolean, default=False, comment="超级管理员,拥有全部权限")
    must_change_password = Column(Boolean, default=False, comment="登录后是否必须先修改初始密码")
    failed_attempts = Column(Integer, default=0, comment="连续密码错误次数")
    locked_until = Column(DateTime, nullable=True, comment="账号锁定截止时间,空为未锁定")
    created_at = Column(DateTime, default=datetime.now)
    last_login_at = Column(DateTime, nullable=True)

    roles = relationship("Role", secondary=user_role, back_populates="users", lazy="selectin")
    departments = relationship(
        "Department",
        secondary=user_department,
        back_populates="users",
        lazy="selectin",
        # 固定按 id 排序:多部门用户的"第一个部门"必须确定(归属默认值/前端回显依赖此顺序)
        order_by="Department.id",
    )

    def to_dict(self):
        from datetime import datetime as _dt

        return {
            "id": self.id,
            "username": self.username,
            "real_name": self.real_name,
            "departments": [{"id": d.id, "name": d.name} for d in self.departments],
            "phone": self.phone,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "must_change_password": self.must_change_password,
            # 是否处于登录锁定中(密码连续错误超阈值)
            "is_locked": bool(self.locked_until and self.locked_until > _dt.now()),
            "locked_until": self.locked_until.strftime("%Y-%m-%d %H:%M:%S") if self.locked_until else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login_at": self.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_login_at else None,
            "roles": [{"id": r.id, "name": r.name, "code": r.code} for r in self.roles],
        }


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, comment="部门名称")
    parent_id = Column(Integer, ForeignKey("departments.id"), nullable=True, comment="上级部门id,空为顶级")
    remark = Column(String(200), default="", comment="备注")
    htdaihao = Column(String(20), default="", comment="合同编号部门代号(如 ssgs),合同登记用")
    xuhaotou = Column(Integer, nullable=True, comment="旧系统部门排序号/计划编号前缀(年度计划模块用)")
    dnnum = Column(Integer, default=0, comment="旧系统主办部门标记,>0 为主办部门(年度计划模块用)")
    zg = Column(String(50), default="", comment="部门负责人(年度计划负责人字段来源)")
    created_at = Column(DateTime, default=datetime.now)

    users = relationship("User", secondary=user_department, back_populates="departments", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "remark": self.remark,
            "htdaihao": self.htdaihao,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, comment="角色名称")
    code = Column(String(50), unique=True, nullable=False, comment="角色编码,如 admin")
    remark = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.now)

    users = relationship("User", secondary=user_role, back_populates="roles", lazy="selectin")
    permissions = relationship(
        "Permission", secondary=role_permission, back_populates="roles", lazy="selectin"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "remark": self.remark,
            "permissions": [{"id": p.id, "code": p.code, "name": p.name} for p in self.permissions],
        }


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, comment="权限标识,如 system:user:manage")
    name = Column(String(100), nullable=False, comment="权限名称")
    category = Column(String(50), default="", comment="所属分类,角色权限页面按此分组展示")
    remark = Column(String(200), default="")

    roles = relationship("Role", secondary=role_permission, back_populates="permissions", lazy="selectin")
