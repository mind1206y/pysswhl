from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.routes import auth, roles, users
from app.core.config import settings

app = FastAPI(title="水司业务管理系统", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
def db_error_handler(request: Request, exc: OperationalError):
    return JSONResponse(
        status_code=500,
        content={"detail": "数据库连接失败,请检查 MySQL 是否启动以及 backend/.env 配置"},
    )


app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/users", tags=["用户管理"])
app.include_router(roles.router, prefix="/api/roles", tags=["角色管理"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
