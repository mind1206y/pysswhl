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
- 入口 `E:\pysswhl\push.bat`（纯 ASCII + CRLF），桌面 `push-pysswhl.bat` 只 `call` 它。流程：缺则建裸库 `E:/pysswhl-backup.git` 并把 HEAD 指 `refs/heads/main`（原 HEAD=master→clone 出空分支）→ `git add -A` + 时间戳提交 → push `origin main` → push `github main:github-clean`（`mind1206y/pysswhl.git`）→ 备份 `backend/.env`、`.env.example`、`rsa_key.pem` 到 `E:\pysswhl-backup\`。
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
加班 OvertimeApply、通信费/SIM 卡、车辆维修 chelwx、IP/手机、稽查 jcxt 全套、路面修复 roadrepair、材料库 materialLibrary、工单领料 WorkOrder、油量统计 oiltj、工单录入 Gongdan、维抢修加班 Jiaban、领料结算 jiesuandan、材料结算查看 jiesuan、车辆保险 Baoxian、车辆各类费用 CLfeiyong、车辆费用明细统计 chelfytj、**财务管理三模块（固定资产 gdzc、清理报告 baofeizc、物资采购申请 wzcgsq）**。
- 财务管理：`models/finance.py`(7 表) + `services/finance_common.py`(部门范围/行组装/短令牌图片) + `services/finance_excel.py`(导入导出) + 3 个路由；菜单分组「财务管理」(icon Wallet)，权限码 `gdzc:view` / `baofeizc:view` / `wzcgsq:view`(分类「财务管理」)。旧库旧 `cj` 层级码由 `finance_scope_ids` 的新部门子树取代并保留集美(10)→杏林(16)特例；`wzcgsq.cj` 前缀过滤靠 `dept_cj_map()` 从 department_map.json 反查。
