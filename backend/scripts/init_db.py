"""初始化数据库:建库、建表、写入初始数据(管理员/角色/权限)。

用法:在 backend 目录下运行
    python -m scripts.init_db
"""

import pymysql
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models.user import Permission, Role, User

DEFAULT_PERMISSIONS = [
    ("system:user:manage", "用户管理"),
    ("system:role:manage", "角色权限管理"),
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
    """轻量迁移:给已存在的 users 表补齐后加的列(create_all 不会修改老表结构)。"""
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as conn:
        if "department" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN department VARCHAR(50) NOT NULL DEFAULT '' COMMENT '部门'"
            ))
            print("已补列 users.department")
        if "must_change_password" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) "
                "NOT NULL DEFAULT 0 COMMENT '登录后是否必须先修改初始密码'"
            ))
            print("已补列 users.must_change_password")


def main():
    create_database()
    Base.metadata.create_all(engine)
    ensure_columns()

    db = SessionLocal()
    try:
        for code, name in DEFAULT_PERMISSIONS:
            if not db.query(Permission).filter(Permission.code == code).first():
                db.add(Permission(code=code, name=name))
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
                    real_name="系统管理员",
                    is_superuser=True,
                    is_active=True,
                )
            )
            db.commit()
            print("已创建管理员账号  用户名: admin  密码: admin123 (登录后请尽快修改)")
        else:
            print("管理员账号已存在,跳过")
    finally:
        db.close()
    print("数据库初始化完成")


if __name__ == "__main__":
    main()
