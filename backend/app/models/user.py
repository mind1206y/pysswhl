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
    password_hash = Column(String(128), nullable=False, comment="bcrypt 哈希")
    real_name = Column(String(50), default="", comment="姓名")
    phone = Column(String(20), default="", comment="手机号")
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_superuser = Column(Boolean, default=False, comment="超级管理员,拥有全部权限")
    must_change_password = Column(Boolean, default=False, comment="登录后是否必须先修改初始密码")
    created_at = Column(DateTime, default=datetime.now)
    last_login_at = Column(DateTime, nullable=True)

    roles = relationship("Role", secondary=user_role, back_populates="users", lazy="selectin")
    departments = relationship(
        "Department", secondary=user_department, back_populates="users", lazy="selectin"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "real_name": self.real_name,
            "departments": [{"id": d.id, "name": d.name} for d in self.departments],
            "phone": self.phone,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "must_change_password": self.must_change_password,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login_at": self.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_login_at else None,
            "roles": [{"id": r.id, "name": r.name, "code": r.code} for r in self.roles],
        }


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, comment="部门名称")
    remark = Column(String(200), default="", comment="备注")
    created_at = Column(DateTime, default=datetime.now)

    users = relationship("User", secondary=user_department, back_populates="departments", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "remark": self.remark,
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
    remark = Column(String(200), default="")

    roles = relationship("Role", secondary=role_permission, back_populates="permissions", lazy="selectin")
