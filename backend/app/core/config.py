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

    # 附件上传根目录(工程管理附件等存放于此)
    UPLOAD_DIR: str = str(BASE_DIR / "uploads")

    # 测漏热力图离线底图瓦片目录(结构 {z}/{x}/{y}.png,GCJ-02 高德瓦片)。
    # 留空时依次探测 backend/assets/tiles 与旧系统 Content/Tiles;
    # 部署到独立机器时把瓦片复制进 backend/assets/tiles 即可,无需外网与 key。
    CELOU_TILE_DIR: str = ""

    # 测漏笔记 115 远程文件服务器(照旧 LeakController 的硬编码地址,可在 .env 覆盖)
    LEAK_REMOTE_UPLOAD_URL: str = "http://172.16.80.115:8081/upload.ashx"
    LEAK_REMOTE_DELETE_URL: str = "http://172.16.80.115:8081/Delete.ashx"
    LEAK_REMOTE_TIMEOUT: int = 120
    # 视频压缩用的 ffmpeg 路径;留空则自动查找 PATH 与旧系统 Tools/ffmpeg/ffmpeg.exe
    LEAK_FFMPEG_PATH: str = ""

    # 短信网关(照旧 SmsSender.cs:内部 ISW 控制台 RPC,AES-128-ECB)
    SMS_ENABLED: bool = True
    SMS_API_URL: str = "http://172.16.110.170:8002/isw/wechat/api/console/rpc.jhtml"
    SMS_AES_KEY: str = "__XM_SWJT__ISW__"
    SMS_TIMEOUT: int = 8

    # 外部工单系统(旧站代理口溯源后的原始上游地址),旧站停运后直接调上游。
    # 工单详情:/ImageProxy/GetByNo -> getFlowInfoById(旧 WorkOrderNoService)
    WORKORDER_FLOW_URL: str = "http://172.16.73.91/flowIntefaceCx/getFlowInfoById"
    WORKORDER_FLOW_APP_ID: str = "EDA2AF854ECE454CB783563537EC9D97"
    WORKORDER_FLOW_VERSION: str = "1.0"
    WORKORDER_FLOW_TIMEOUT: int = 5

    # 工单现场图片:/ImageProxy/GetWorkOrderImages -> appServeApi?state=formImageList
    # /ImageProxy/GetImage 只是图片直链代理,直链域名由 IMAGE_ALLOWED_HOST 白名单限制。
    WORKORDER_IMAGE_URL: str = (
        "http://172.16.80.129/appServe/appServeApi.do?state=formImageList"
    )
    WORKORDER_IMAGE_APP_ID: str = "xmsw20260506"
    WORKORDER_IMAGE_VERSION: str = "1.0"
    WORKORDER_IMAGE_ALLOWED_HOST: str = "172.16.80.129"
    WORKORDER_IMAGE_TIMEOUT: int = 8
    WORKORDER_IMAGE_MAX_BYTES: int = 10 * 1024 * 1024

    # 生产环境建议设为 false:关闭 /docs /openapi.json 接口文档,避免接口信息泄露
    ENABLE_DOCS: bool = True

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
