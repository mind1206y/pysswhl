from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.routes import (
    auth, baoxian, celou, chelfytj, chuxian, clfeiyong, contracts, departments, gongdan, ipadress,
    jcjl, jcxt, jiesuan, jiesuandan, jiaban, leak, lingliao, material, oilcard, oiltj, overtime,
    overtime_config,
    overtime_flow, phone, plus_oil, project_details, projects, repair, roadrepair, roles,
    simcard, simfee, users, vehicle, vehicle_daily, water_fee, weizhang, workorder, jcdan,
    spjicha, gxdxljihua, jhssdb, jhsshz, jhyyfaqi,
    gdzc, baofeizc, wzcgsq,
)
from app.core.config import settings

app = FastAPI(
    title="售水业务管理系统",
    version="0.1.0",
    # 生产环境 .env 里 ENABLE_DOCS=false 可关闭接口文档,避免接口信息泄露
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """基础安全响应头:防点击劫持/嗅探,收窄 referrer。"""
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    return response


@app.exception_handler(OperationalError)
def db_error_handler(request: Request, exc: OperationalError):
    return JSONResponse(
        status_code=500,
        content={"detail": "数据库连接失败,请检查 MySQL 是否启动以及 backend/.env 配置"},
    )


app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/users", tags=["用户管理"])
app.include_router(departments.router, prefix="/api/departments", tags=["部门管理"])
app.include_router(roles.router, prefix="/api/roles", tags=["角色管理"])
app.include_router(ipadress.router, prefix="/api/ipadress", tags=["IP地址管理"])
app.include_router(projects.router, prefix="/api/projects", tags=["工程管理"])
app.include_router(project_details.router, prefix="/api/projects", tags=["工程管理-进度/问题/附件"])
app.include_router(water_fee.router, prefix="/api/waterfee", tags=["特殊群体管理"])
app.include_router(vehicle.router, prefix="/api/vehicles", tags=["车辆管理"])
app.include_router(chuxian.router, prefix="/api/chuxian", tags=["车辆管理-出险信息"])
app.include_router(weizhang.router, prefix="/api/weizhang", tags=["车辆管理-违章信息"])
app.include_router(clfeiyong.router, prefix="/api/clfeiyong", tags=["车辆管理-各类费用"])
app.include_router(baoxian.router, prefix="/api/baoxian", tags=["车辆管理-车辆保险"])
app.include_router(chelfytj.router, prefix="/api/chelfytj", tags=["车辆管理-费用明细统计"])
app.include_router(oilcard.router, prefix="/api/oilcards", tags=["车辆管理-油卡管理"])
app.include_router(plus_oil.router, prefix="/api/plusoil", tags=["车辆管理-加油明细"])
app.include_router(oiltj.router, prefix="/api/oiltj", tags=["车辆管理-油量统计"])
app.include_router(vehicle_daily.router, prefix="/api/vehicle-daily", tags=["日常用车"])
app.include_router(repair.router, prefix="/api/repairs", tags=["车辆维修"])
app.include_router(roadrepair.router, prefix="/api/roadrepair", tags=["路面修复管理"])
app.include_router(phone.router, prefix="/api/phones", tags=["手机管理"])
app.include_router(celou.router, prefix="/api/celou", tags=["测漏成果汇总"])
app.include_router(leak.router, prefix="/api/leak", tags=["测漏笔记"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["合同登记/归集"])
app.include_router(overtime.router, prefix="/api/overtime", tags=["加班申请审批"])
app.include_router(overtime_flow.router, prefix="/api/overtime", tags=["加班申请审批-流程"])
app.include_router(overtime_config.router, prefix="/api/overtime", tags=["加班申请审批-配置"])
app.include_router(simcard.router, prefix="/api/simcard", tags=["SIM卡管理"])
app.include_router(simfee.router, prefix="/api/simfees", tags=["通信费"])
app.include_router(jcxt.router, prefix="/api/jcxt", tags=["稽查系统"])
app.include_router(spjicha.router, prefix="/api/spjicha", tags=["审批稽查"])
app.include_router(jcdan.router, prefix="/api/jcdan", tags=["稽查单"])
app.include_router(jcjl.router, prefix="/api/jcjl", tags=["稽查奖励"])
app.include_router(material.router, prefix="/api/materials", tags=["工单材料库"])
app.include_router(workorder.router, prefix="/api/workorder", tags=["工单领料管理"])
app.include_router(lingliao.router, prefix="/api/lingliao", tags=["领料申请"])
app.include_router(jiesuandan.router, prefix="/api/jiesuandan", tags=["领料结算"])
app.include_router(jiesuan.router, prefix="/api/jiesuan", tags=["材料结算单查看"])
app.include_router(gongdan.router, prefix="/api/gongdan", tags=["工单信息录入"])
app.include_router(jiaban.router, prefix="/api/jiaban", tags=["维抢修加班"])
app.include_router(gxdxljihua.router, prefix="/api/plan", tags=["年度计划-正式计划"])
app.include_router(jhssdb.router, prefix="/api/jhssdb", tags=["年度计划-实施单表"])
app.include_router(jhsshz.router, prefix="/api/jhsshz", tags=["年度计划-实施汇总"])
app.include_router(jhyyfaqi.router, prefix="/api/jhyyfaqi", tags=["年度计划-营业所发起"])
app.include_router(gdzc.router, prefix="/api/gdzc", tags=["财务管理-固定资产"])
app.include_router(baofeizc.router, prefix="/api/baofeizc", tags=["财务管理-清理报告"])
app.include_router(wzcgsq.router, prefix="/api/wzcgsq", tags=["财务管理-物资采购申请"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
