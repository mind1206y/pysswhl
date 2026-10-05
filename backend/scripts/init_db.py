"""初始化数据库:建库、建表、写入初始数据(管理员/角色/权限)。

用法:在 backend 目录下运行
    python -m scripts.init_db
"""

import pymysql
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import Base, SessionLocal, engine
from app.models.user import Department, Permission, Role, User

DEFAULT_PERMISSIONS = [
    ("system:user:manage", "用户管理"),
    ("system:dept:manage", "部门管理"),
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
