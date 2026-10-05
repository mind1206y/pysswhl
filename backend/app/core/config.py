from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """配置项,从 backend/.env 读取(参考 .env.example)"""

    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "sswhl_new"

    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720

    # 管理员创建/重置用户时使用的初始密码,用户登录后会被强制要求修改
    INITIAL_PASSWORD: str = "abc123456"

    # 密码哈希胡椒:参与哈希计算的秘密随机串,只存本文件(.env),不进数据库。
    # 一旦设置就不要更改;留空等于不启用该层保护。
    PASSWORD_PEPPER: str = ""

    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"


settings = Settings()
