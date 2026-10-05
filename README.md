# pysswhl — 新系统(Python + Vue3 + MySQL)

全新开发的管理系统骨架,后续业务模块在此基础上逐个添加。旧系统(ASP.NET)继续独立运行,不受影响。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 + PyMySQL |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router |
| 数据库 | MySQL 8+(本机已装 9.7.1,直接用) |
| 认证 | JWT(Bearer Token)+ bcrypt 密码哈希 |

## 目录结构

```
pysswhl/
├── backend/                 # 后端
│   ├── app/
│   │   ├── main.py          # FastAPI 入口,注册路由
│   │   ├── core/            # 配置(.env)、密码/JWT
│   │   ├── db/              # 数据库连接
│   │   ├── models/          # SQLAlchemy 表模型
│   │   └── api/routes/      # 接口:auth / users / departments / roles
│   ├── scripts/
│   │   └── init_db.py       # 建库建表 + 初始数据
│   └── requirements.txt
├── frontend/                # 前端
│   └── src/
│       ├── api/             # 接口调用封装
│       ├── stores/          # Pinia 状态(登录信息)
│       ├── router/          # 路由 + 登录拦截 + 权限拦截
│       ├── layout/          # 后台布局(侧边菜单)
│       └── views/           # 页面(system/ 下是系统管理)
└── docs/
    ├── 数据迁移约定.md       # 旧系统数据导入的规则
    ├── 权限控制机制.md       # 权限链路原理 + 新模块接入模板
    └── 部署清单.md           # 以后部署到 Linux 服务器时照着勾的清单
```

## 环境要求

- Python 3.10+(已装 3.12)
- Node.js 18+(已装 v24)
- MySQL 8+(本机已有,服务名 MySQL,端口 3306)

## 首次启动

### 1. 后端

```bash
cd E:/pysswhl/backend

# 创建虚拟环境(只需一次)
python -m venv .venv
.venv/Scripts/activate          # Git Bash 用 source .venv/Scripts/activate

pip install -r requirements.txt

# 配置数据库连接:复制 .env.example 为 .env,填入 MySQL 密码
cp .env.example .env

# 建库建表 + 创建管理员
python -m scripts.init_db

# 启动(开发模式)
uvicorn app.main:app --reload --port 8000
```

启动后可打开 http://127.0.0.1:8000/docs 查看接口文档(Swagger)。

### 2. 前端

```bash
cd E:/pysswhl/frontend
npm install
npm run dev
```

打开 http://localhost:5173,默认管理员账号:**admin / admin123**(登录后请尽快修改)。

## 账号与密码策略

- 管理员创建用户时只填**姓名 / 用户名**,并为用户勾选**部门**(可多选),不设密码;系统统一发初始密码 **abc123456**。
- 用户与部门是**多对多**关系;部门支持**多级树形结构**(上级部门在「部门管理」里维护),在用户管理里编辑/勾选关联。
- admin 的初始密码 admin123 也受强制改密约束:重新执行 `python -m scripts.init_db` 时,若检测到 admin 仍在用 admin123,会自动要求其下次登录先改密码。
- 登录页可勾选「记住用户名」(只记用户名,不记密码);30 分钟无任何操作会自动退出登录(公用电脑防护)。
- 登录和改密请求中的密码使用 **RSA-OAEP 加密传输**:后端经 `/api/auth/public-key` 下发公钥,前端用浏览器 WebCrypto 加密,私钥仅存在后端内存(重启自动更换,前端会自动重新获取)。注意这是防明文泄露的补充手段,不能替代 HTTPS。
- 密码连续错误 **5 次,账号锁定 10 分钟**(在线防爆破);锁定到期自动解锁并重新计数,登录成功即清零。提示语会显示已错次数和剩余机会。
- **密码哈希:Argon2id + pepper**(v1)。pepper 是只存在于 `backend/.env` 的秘密随机串(`PASSWORD_PEPPER`),即使数据库整库泄露,只要 `.env` 没泄露,离线破解无从下手。旧 bcrypt 哈希(v0)在用户下次登录成功时自动透明升级,无需重置密码。**重要:`PASSWORD_PEPPER` 一旦设置切勿更改或删除,否则所有用户无法登录。**
- **MySQL 加固**:仅监听本机 127.0.0.1(`E:\mysql-9.7.1-winx64\...\my.ini`),局域网无法直连;后端使用专用低权限账号 `sswhl_app`(只授权本项目库)连接,root 口令已换为强随机串(备份在 `.env` 注释里)。局域网电脑中毒也拖不走数据库了。
- 用户名填错(如手机号输错一位)在用户管理中**删除后重建**即可:删除会连同角色、部门关联一起清除,且不可恢复;自己和超级管理员账号不可删除。
- 用户用初始密码登录后,会被强制跳转到修改密码页,改完才能进入系统。
- 新密码必须为**复杂密码**:至少 8 位,且同时包含大写字母、小写字母、数字和符号(前后端双重校验)。
- 「重置密码」会把该用户重置回初始密码 abc123456,并要求其下次登录先改密码。
- 初始密码可在 `backend/.env` 里通过 `INITIAL_PASSWORD` 覆盖。
- 各页面菜单项按用户被分配的角色权限显示(无权限的菜单不出现);角色能勾选哪些功能权限,在「角色权限」页面维护,新功能权限(如部门管理 `system:dept:manage`)登记在 `scripts/init_db.py` 的 DEFAULT_PERMISSIONS 中,重新执行 init_db 后即可勾选。

## 日常启动(批处理)

配置过一次之后,日常启动直接双击 `E:\pysswhl` 下的批处理即可:

| 文件 | 作用 |
|---|---|
| `start-all.bat` | 一键启动:开两个窗口分别跑前后端,并自动打开浏览器 |
| `start-backend.bat` | 只启动后端 |
| `start-frontend.bat` | 只启动前端 |

关掉对应窗口(或 Ctrl+C)即停止服务。可以把 `start-all.bat` 右键发送到桌面快捷方式。

## 以后怎么加一个业务模块(标准流程)

以"车辆管理"为例:

1. **建表**:`app/models/` 下新增模型文件,旧库有对应表的话,表名/字段名尽量沿用(见数据迁移约定)。
2. **建表进库**:改 `scripts/init_db.py` 或新增迁移脚本,重新执行。
3. **写接口**:`app/api/routes/` 下新增路由文件,需要权限就在依赖里写 `require_permission("xxx:manage")`,并在 `init_db.py` 的 DEFAULT_PERMISSIONS 里登记该权限。
4. **注册路由**:`app/main.py` 里 `app.include_router(...)`。
5. **前端页面**:`frontend/src/api/` 加接口封装,`src/views/` 加页面。
6. **挂菜单**:`src/router/index.js` 加路由(meta 里带 perm),`src/layout/MainLayout.vue` 的 menuItems 加菜单项。

> 权限链路的完整原理、粒度约定和接入模板见 [docs/权限控制机制.md](docs/权限控制机制.md)。

## 备份(Git 双远程)

参照旧系统的方案,配置了两个远程,日常双击 `E:\pysswhl\push.bat` 一键推送:

| 远程 | 地址 | 推送 |
|---|---|---|
| `origin` | `E:/pysswhl-backup.git`(本地裸仓库) | `main` |
| `github` | `git@github.com:mind1206y/pysswhl.git` | `main:github-clean` |

同时会把 `backend/.env` / `.env.example` 复制一份到 `E:\pysswhl-backup\` 做文件备份(`.env` 含数据库密码,不进 git)。

## Docker

开发阶段不需要。以后若部署到 Linux 服务器,照 [docs/部署清单.md](docs/部署清单.md) 逐项执行(裸机部署步骤 + 安全清单);需要时再补一套 docker-compose(api + mysql + nginx)即可,代码不需要任何改动。
