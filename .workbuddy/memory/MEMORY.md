# 项目长期记忆（pysswhl 旧系统迁移）

> 旧库 SQL Server `db_plan` / 新库 MySQL `sswhl_new` / 新系统 FastAPI+Vue3 / 旧源码 `sswhl/`。复刻 = 1:1 还原旧功能 + 旧数据全量迁移。
> **模块表（19 个已复刻模块的行数/SUM/权限）、踩坑清单、冒烟基线 全在 `memory/MODULES.md` —— 动某个模块前先读它。**

## 一、全局约定

### 部门 id / bmid
- 旧 `bb_bumen`(38) 与 `departments` id **不对应且撞车**：一律读 `backend/scripts/migration_reports/department_map.json`，⛔勿按名称现算；旧 bmid=10 无映射→NULL+告警。常用：2→8 厦门、5→10 集美、6→16 杏林、7→9 海沧、8→12 同安、9→13 翔安、4→15 售水本部、18→22 特水、30→32 制水。
- 一次原子 `CASE WHEN ... END WHERE bmid IN (...)`；⛔逐条 UPDATE 循环会链式污染。工具：`import_departments.py`（幂等补齐）、`repair_bmid_from_old.py`（只更 IS NULL）、`build_bmid_map`；`fix_waterfee_bmid.py` 已退役。旧库仍有 ~40 张带 bmid 表未迁。
- 数据权限：`bmid`→`departments.id` 含 parent_id 子树，共用 `app/api/deps.py` 的 `dept_scope_ids`/`dept_name_map`；新增取登录人部门（多部门限本人部门内选、超管自由），非超管编辑不得挪出本人部门；前端 `formDeptOptions`。

### 迁移与验证
- `scripts/import_xxx.py`：逐表 TRUNCATE 可重导、`--dry-run`、保留旧 id 并重设自增、金额 `DECIMAL(18,4)`；⚠️重跑会清共享表，先看 TRUNCATE 范围。
- 校验：新旧行数/SUM(金额) 对齐；`smoke_xxx.py` TestClient 全链路（临时超管自动建删、登录 RSA-OAEP + `/api/auth/public-key`）；前端 `npm run build`，必要时 Chrome CDP 真机回归。
- 权限码 `scripts/init_db.py`；菜单/路由 `router/index.js` + `MainLayout.vue`；文档 `docs/权限控制机制.md`、`docs/数据迁移约定.md`。图片：旧 `/Upload/...` 多缺失→占位/404；列表图走短令牌 URL（`create_short_token`），⛔登录令牌别进 URL；黑名单照 UploadGuard、10MB。

### Git 备份 / 双远程推送（2026-11-09）
- 入口 `E:\pysswhl\push.bat`（纯 ASCII + CRLF），桌面 `push-pysswhl.bat` 只 `call` 它。流程：缺则建裸库 `E:/pysswhl-backup.git` 并把 HEAD 指 `refs/heads/main`（原 HEAD=master→clone 出空分支；2026-11-16 起改为**静默前置**，不占步骤号）→ `git add -A` + 时间戳提交 → push `origin main` → push `github main:github-clean`（`mind1206y/pysswhl.git`）→ 备份 `backend/.env`、`.env.example`、`rsa_key.pem` 到 `E:\pysswhl-backup\`，并 `robocopy deploy\import` + 根目录 `*.tar.gz`/`*.sql.gz` 到 `E:\pysswhl-backup\artifacts`（2026-11-16 起）。
- ⛔ **数据库 dump / 发版包一律不进 Git**（`.gitignore` 已加 `*.sql`、`*.sql.gz`、`*.tar.gz`、`deploy/import/`）：`deploy/import/sswhl_new.sql` 122MB 撞 GitHub 100MB 硬限，第一次只在 push 的最后一步炸（接收端 pre-receive 校验，本地无提示）。再遇到同类报错：只改 tip 提交（`reset --soft HEAD~1` → `git rm -r --cached` → 重新 commit → 裸库打标签留档再 `-f` 推 origin），别急着重写全历史。
- ⛔本环境 Bash/PowerShell 均禁 `cmd /c`，.bat 无法代跑，只能人工双击验证。`.vscode/`、`.zcode/`、`*.bak`、`*.log` 已忽略；`.workbuddy/` 入库（项目记忆随备份走）。

### 弹窗表单样式（2026-11-09 定稿）
- 基准 = Gongdan `.gd-dialog` / **可复用基类 `.std-dialog`（`App.vue` 全局非 scoped）**：控件 32px 高/16px 胶囊、灰底 `#f3f2f0` 无边框 12px 白卡、52px 紫题头贴顶贴边 + 14px 上圆角、白圆关闭钮、56px 白 footer（flex 垂直居中）+ 32px 按钮、`--el-color-primary:#533afd`；任意表单弹窗挂 `class="std-dialog"` 即用（工程管理 4 个已用），白卡自动套 `body > .el-form` / `.preview-body`。别再复制 CSS。
- 加班弹窗全 `class="ot-dialog"`（`views/overtime/overtime.css` 全局 import）；jcxt 三表单 `class="jc-form-dialog"`（规则在 `App.vue`）。el-dialog teleport 到 body → 跨页样式必须全局 + 类名前缀，页面级 `.xxx-page` 够不到；弹窗根节点要补 CSS 变量。
- ⚠️ `.el-input__wrapper` 默认 `content-box`：只写 `height:32px` 会变 34px，必须 `box-sizing:border-box`；`.el-select__wrapper` 本身 32px；date-editor/input-number 别强改 padding；textarea 不锁高。footer 定高必须 flex + `align-items:center`（只写 min-height 按钮贴顶），内部包一层 div 给 `> div{flex:1}`，按钮 `margin:0`。
- ⛔别统一设深 `.el-select__placeholder`：只对 `.is-transparent` 设 placeholder 色，已选值仍 `#1b1d21`。`.gd-dialog` 必须 `padding:0`、header `position:relative`；⛔弹窗不放部门下拉（旧系统无），`bmid` 由后端 `_default_bmid(...,None)` 兜底、编辑不改。加班主色 `#533afd`，工单 `#5645d4`（对齐尺寸/布局而非主色）。Gongdan 日期框缩短 + 74px「时:分」按钮（`el-popover` 84 格、`syncDt` 合成 `yyyy-MM-dd HH:mm:ss`）。

### 左侧菜单（2026-11-09）
- `<el-menu>` 已开 `unique-opened`（点一个分组收其它，sub-menu index 用中文分组标题），当前路由父分组仍自动展开。`MainLayout.vue` 用 `:deep()`：`.menu` 上 `--el-menu-level-padding:40px`（子项 padding-left=60px）、`.el-menu--inline` 背景 `#0b2238`（父 `#001529`）+ 2px 上下 padding + inset 细线；子项文字 `#b6bfcb` + 46px 处 5px 圆点，hover 白字+7% 白底，active `rgba(83,58,253,.28)` + inset 3px `#8b7bff` 左竖条。
- **紧凑行高（2026-11-11）**：`.menu` 上设官方变量 `--el-menu-item-height:40px`（一级项/分组标题，默认 56）+ `--el-menu-sub-item-height:34px`（展开子项，默认 50）；⛔别写死 `.el-menu-item{height}`，变量会同时带动 line-height、居中与折叠动画。`.logo` 与 `.header` 仍 60px 未动。
- ⚠️改缩进用 CSS 变量而非覆盖 `padding-left`：Element Plus 用 `calc(20px + var(--el-menu-level)*var(--el-menu-level-padding))` 且优先级高，`--el-menu-level` 由组件 inline style 注入。子菜单 ul 继承根 `--el-menu-bg-color`（默认父子同色）。

### 地图 / 热力图
- **Leaflet + 本地高德离线瓦片**（GCJ-02，`Content/Tiles/{z}/{x}/{y}.png`，z10~17，~330MB），⛔别降级 ECharts 散点；瓦片不进 git，`_tile_root()` 顺序 `.env CELOU_TILE_DIR` → `backend/assets/tiles` → 旧目录；部署 `python -m scripts.prepare_heatmap_tiles --source <目录> --copy`。
- 瓦片走 `POST /api/celou/heatmap/tile-token` 签 `celou_tile`(180min) 挂 query，`GET /api/celou/tiles` 校验，缺图返 1×1 透明 PNG；权重照旧 `GetHeatmapData`（漏量/管径 95 分位归一化 + 0.001° 网格 p50~p95 五档）。前端库 `public/vendor/leaflet/`，覆盖样式用 `.celou-heat-map .xxx` 提权。合规：仅内网离线、界面留 `© 高德地图`、⛔不得对外分发；公网须官方 SDK + 自申请 key + 后端代理鉴权。

## 二、已复刻模块（细节见 `memory/MODULES.md`）
**用户与权限（2026-11-15 全量迁移）**：`scripts/import_users.py` 把旧 `bb_user`(199)+`bb_qxfenpei` 导成 `users` + `legacy_*` 角色（详见当日日志）。密码三版本号：0=bcrypt、1=Argon2id+pepper、2=旧 PBKDF2-SHA1、3=旧 MD5(.NET Unicode, 29~32 位丢前导零)；登录成功统一升级 v1，`scripts/smoke_users.py` 26 项基线。**写 `user_role` 必须同时写 `role_permission`，否则用户权限为空**。
⚠️ **16:17 起 `users.id` = 旧 `bb_user.id` 1:1 恒等**（199 账号，3~382 跳号），`user_map.json` 也是恒等映射；`scripts/rebuild_user_ids.py` 把 1→207(admin)、7→3(林春)、383→7(陈毅清) 重编号并删掉测试超管 21，`import_users.py` 重跑只 UPDATE、不再分配 id。起因：`sms_contact.id` / `gx_user_gxgz.userid` / `jh_ssdb(pz).zhuanguan` / `jh_yyfq.zgy` 等表直接搬旧 id，而 `resolve_user_id()` 写入的是当前 `users.id`，两套口径不一致（重建前 12294 行悬空）。⛔ 以后别让任何脚本重算 user_map；导 dump 前 `make_release.py` 会拦截 `smoke*` / `guitest` 测试账号。

加班 OvertimeApply、通信费/SIM 卡、车辆维修 chelwx、IP/手机、稽查 jcxt 全套、路面修复 roadrepair、材料库 materialLibrary、工单领料 WorkOrder、油量统计 oiltj、工单录入 Gongdan、维抢修加班 Jiaban、领料结算 jiesuandan、材料结算查看 jiesuan、车辆保险 Baoxian、车辆各类费用 CLfeiyong、车辆费用明细统计 chelfytj、**财务管理三模块（固定资产 gdzc、清理报告 baofeizc、物资采购申请 wzcgsq）**。
- 财务管理：`models/finance.py`(7 表) + `services/finance_common.py`(部门范围/行组装/短令牌图片) + `services/finance_excel.py`(导入导出) + 3 个路由；菜单分组「财务管理」(icon Wallet)，权限码 `gdzc:view` / `baofeizc:view` / `wzcgsq:view`(分类「财务管理」)。旧库旧 `cj` 层级码由 `finance_scope_ids` 的新部门子树取代并保留集美(10)→杏林(16)特例；`wzcgsq.cj` 前缀过滤靠 `dept_cj_map()` 从 department_map.json 反查。
- **传导完好率四模块（2026-11-15）**：完好率 CDwanhaolv / 故障 CDguzhang / 大修 CDdaxiu / 变动表 CDbiandong，菜单分组「传导完好率」(icon TrendCharts)，路径 `/cdwhl /cdgz /cddaxiu /cdbd`，权限码 `cdwhl:view/manage`、`cdgz:view`、`cddaxiu:view`、`cdbd:view`。`models/cd.py`(4 表) + `services/cd_common.py` + `services/cd_excel.py` + 5 路由；`scripts/import_cd.py` 导 184/3132/410/1355 行(详见 MODULES.md)。⛔ 用户迁移早于本模块：`import_users.py` 的 68~71 映射已补，另跑 `scripts/grant_cd_perms.py` 给 13 人补授 `legacy_cd*` 角色；重跑用户导入前确认映射仍在。`smoke_cd` 84/84。

## 三、内网部署（2026-11-13，目标机 **172.16.43.126**）
- 目标机 Ubuntu 22.04.2 / Docker 环境（已有 `xinkong` 栈占 8000/8001/7004/5150/18086）/ 系统 Python **3.10.6** / **无外网（pypi 000，apt 可用）**。产物全在 `deploy/`：`install.sh`（幂等 7 步）、`docker-compose.yml`、`sswhl-api.service`、`env.production.example`、`README.md`、`wheels`（37 个 cp310 离线包）。
- 形态：**宿主 venv 跑 API + 容器 `sswhl-mysql`（127.0.0.1:13306）+ FastAPI 直接托管 dist**，systemd `sswhl-api` 对外 **18080**，⛔不装 nginx（少组件）。`requirements-linux.txt` 去 pyodbc，服务器不需要 unixODBC。
- 三个必踩的坑：①容器必须 `--lower-case-table-names=1`，否则 11 个带大写的表名（CLdui/LeakFile/celouTb/cl_cxTP…）在 Linux 找不到，且 create_all 会另建**同名空表**；②导入 dump 必须**沿用开发机 PASSWORD_PEPPER**，换新=全体登录失败（install.sh 检测到已有 .env 会保留）；③`UPLOAD_DIR` 不能留空（`Path("").resolve()`=cwd，附件会散落到 backend/）。
- 代码：`config.py` 增 `SERVE_FRONTEND`(默认 false)/`FRONTEND_DIST`；`main.py` 末尾加 `/assets` 挂载 + `/{full_path:path}` SPA 回退，`api/`、`docs`、`openapi.json` 直接 404，`resolve()+startswith` 防穿越。开发环境不受影响。
- **接入限制（2026-11-14 实测，详见 `docs/服务器环境记录.md`）**：本机 aTrust 连的是另一个办公 VPN 且为**应用级代理**（只代理浏览器），`172.16.43.126`(真机,22/443/80)、`172.56.11.11`(堡垒机网页) **从开发机全不通**，WinSCP/Xftp/Xshell/scp 全部不可用；「运行下载」无 WinSCP，只给 463 字节 `.xfp` 会话文件。**唯一通道 = 堡垒机网页终端 + 自带文件传输**。⛔别再引导用户装客户端工具。
- ⚠️ **IP 更正（2026-11-15 用户实测）**：对外访问地址是 **`http://172.16.43.126:18080`**（早前记录的 `172.56.43.126` 有误，已废弃；开发机到该 IP 不通属正常，因不在同一网络）。
- **容器化（2026-11-14）**：开发机无 Docker、WSL 被安全策略禁用、Hub 直连 000（`docker.1panel.live` 可用），故用 `deploy/tools/build_image_offline.py` **无 daemon 手工造镜像**：下载 base 层→`pip install --target --platform manylinux2014_x86_64 --python-version 3.10 --abi cp310 --only-binary=:all: --no-index`（78 个包目录）→复制 backend/dist→打第 5 层算 diffID→改写 config 的 `rootfs.diff_ids/Env/Cmd/WorkingDir`→拼 manifest+repositories+layer.tar。产物 `sswhl-api-image.tar` 70.6MB，tag `sswhl-api:1.0` + `python:3.10-slim`。compose 的 `api` 挂 `profiles:["docker-api"]`（默认 up 只起 mysql），容器内必须覆盖 `DB_HOST=mysql`/`UPLOAD_DIR=/app/backend/uploads`/`FRONTEND_DIST=/app/frontend/dist`；`.env` 与 `rsa_key.pem` ⛔不打进镜像，只读挂载。⚠️`.dockerignore` 别排除 `deploy/wheels`（Dockerfile 要 COPY）。
- **发版（2026-11-15）**：`python deploy/tools/make_release.py`（库没变加 `--no-db`）一条命令出 3 件产物：最新全量 dump（118 表，含 CREATE DATABASE）、`sswhl-deploy.tar.gz`（首次装）、`sswhl-update.tar.gz`（日常更新 4.3MB）。脚本固定 gzip `mtime=0`+uid/gid=0+排序，**字节可复现**，故 README 第十二节能写死 MD5；含新模块/dist 自动校验。改代码但依赖没变 → **只传精简包 + dump，不重传 71MB 镜像**，`update.sh --pkg ... --schema` → 再 `--db ... --yes`（全量）或 `--tables <10 张表>`（保数据）。⚠️用户/角色/权限/consol 共 6 张表 id 互引，必须与 4 张 cd 表**一组一起覆盖**；`update.sh` 自覆盖已改原子 mv。
