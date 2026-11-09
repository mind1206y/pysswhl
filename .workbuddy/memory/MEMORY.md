# 项目长期记忆（pysswhl 旧系统迁移）

> 旧库 SQL Server `db_plan` / 新库 MySQL `sswhl_new` / 新系统 FastAPI+Vue3 / 旧源码 `sswhl/`。复刻 = 1:1 还原旧功能 + 旧数据全量迁移。

## 一、全局约定

### 部门 id / bmid
- 旧 `bb_bumen`(38) 与 `departments` id **不对应且撞车**：一律读 `backend/scripts/migration_reports/department_map.json`，⛔勿按名称现算；旧 bmid=10 无映射→NULL+告警。常用：2→8 厦门、5→10 集美、6→16 杏林、7→9 海沧、8→12 同安、9→13 翔安、4→15 售水本部、18→22 特水、30→32 制水。
- 一次原子 `CASE WHEN ... END WHERE bmid IN (...)`；⛔逐条 UPDATE 循环会链式污染。工具：`import_departments.py`（幂等补齐）、`repair_bmid_from_old.py`（只更 IS NULL）、`build_bmid_map`；`fix_waterfee_bmid.py` 已退役。已核 0 不一致：cl_che、plusoil、shuifeixitong、shuifeixitongquxiao、gongchenggl、celouTb；旧库仍有 ~40 张带 bmid 表未迁。
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
- `<el-menu>` 已开 `unique-opened`（点一个分组收其它，sub-menu index 用中文分组标题），当前路由父分组仍自动展开。`MainLayout.vue` 用 `:deep()`：`.menu` 上 `--el-menu-level-padding:40px`（子项 padding-left=60px）、`.el-menu--inline` 背景 `#0b2238`（父 `#001529`）+ 4px 上下 padding + inset 细线；子项文字 `#b6bfcb` + 46px 处 5px 圆点，hover 白字+7% 白底，active `rgba(83,58,253,.28)` + inset 3px `#8b7bff` 左竖条。
- ⚠️改缩进用 CSS 变量而非覆盖 `padding-left`：Element Plus 用 `calc(20px + var(--el-menu-level)*var(--el-menu-level-padding))` 且优先级高，`--el-menu-level` 由组件 inline style 注入。子菜单 ul 继承根 `--el-menu-bg-color`（默认父子同色）。

### 地图 / 热力图
- **Leaflet + 本地高德离线瓦片**（GCJ-02，`Content/Tiles/{z}/{x}/{y}.png`，z10~17，~330MB），⛔别降级 ECharts 散点；瓦片不进 git，`_tile_root()` 顺序 `.env CELOU_TILE_DIR` → `backend/assets/tiles` → 旧目录；部署 `python -m scripts.prepare_heatmap_tiles --source <目录> --copy`。
- 瓦片走 `POST /api/celou/heatmap/tile-token` 签 `celou_tile`(180min) 挂 query，`GET /api/celou/tiles` 校验，缺图返 1×1 透明 PNG；权重照旧 `GetHeatmapData`（漏量/管径 95 分位归一化 + 0.001° 网格 p50~p95 五档）。前端库 `public/vendor/leaflet/`，覆盖样式用 `.celou-heat-map .xxx` 提权。合规：仅内网离线、界面留 `© 高德地图`、⛔不得对外分发；公网须官方 SDK + 自申请 key + 后端代理鉴权。

## 二、已复刻模块速查

| 模块 | 后端 / 前端 | 迁移要点 | 权限 |
|---|---|---|---|
| 加班 OvertimeApply | `/api/overtime`(75) `/overtime` | 12 张 `overtime_*`，**不导旧数据**（旧 199 用户仅 2 个匹配，须先补账号映射）；三套 id 见踩坑；6 Tab 靠 `/dicts` perms 显隐 | `overtime:view/apply/verify/hr/manage` |
| 通信费 / SIM 卡 | `/api/simfees` `/simfee`；`/api/simcard` `/simcard` | `feiyong`(84879) 只读、写入口在 SIM 卡上传话费；`sim`(2627) 等 8 表；`delf=1` 正常、0 软删(卡号加 `_X`)；SUM(jine)=5631979.44 | `simfee:view`、`simcard:view/manage` |
| 车辆维修 chelwx | `/api/repairs` `/repair` | `cl_wxdan`(1433)/`cl_wxmx`(6486)/`cl_wxdw`(14)/`cl_wxdTP`(0)；维修单无 bmid，部门取 `cl_che.bmid` | `repair:view/manage/audit`（audit=旧 `clsp=1`） |
| IP / 手机 | `/api/ipadress` `/ipadress`；`/api/phones` `/phone`+`/phone/print` | `ipadress`(2530)=10 网段×253，加网络自动生成 253 IP；「可领用」=未使用；`shouji`(388) 等 4 表 | `ipadress:view/manage`、`phone:view/manage/huishou` |
| 稽查 jcxt 全套 | `/api/jcxt` `/api/spjicha` `/api/jcdan` `/api/jcjl`，4 页 | 数据在 db_plan 的 `jc_*`（本地无 ssjcxt 库）：`jc_jcxx`(17495)/`jc_tupian`(12652) 等；10 项金额对齐；printcolum 51 条属已删用户跳过 | 4 个 `*:view` |
| 路面修复 roadrepair | `/api/roadrepair` `/roadrepair` | `road_repair`(508)/progress(7)/price(37)/attachment(60)/`qiangxiurenyuan`(14)；**road_* 无 bmid**；`qiangxiurenyuan` 是班组下拉源、工单共用；SUM(total)=787161.49 | `roadrepair:view` |
| 材料库 materialLibrary | `/api/materials`(18) `/material` | 5 表见 `models/material.py`：library(695)/in_stock_record(1020)/material_record(31194 只读)/image(236)/**work_order(10976 勿重导)**；bmid 44121；SUM(num)=38305.2 | `material:view/manage` |
| 工单领料 WorkOrder | `/api/workorder` `/workorder` | `import_workorder.py` **只导 gongdancailiao(19689)+work_order_attachment(0)**；「已领用」=EXISTS(gongdancailiao.gongdanhao=work_order_no)，`IsUsed` 死列；已领 9104/未领 1872 | `workorder:view/manage` |
| 油量统计 oiltj | `/api/oiltj`(12) `/vehicle/oiltj` | `tboil`(14552)，SUM(oilnum)=355253.31 / oiljine=1729186.90；**数据源不混用**：列表油量/财务导出→PlusOil、里程→yongcherc、子表/图表/月年度导出→tboil、余额→OilCard | `oiltj:view` |
| 工单录入 Gongdan | `/api/gongdan`(21) `/gongdan` | 主表 **gongdancailiao(19689) 复用勿重导**；只新导 gongdan(76870 热线镜像)/两字典(72/21)；`cf`=重复工单号、`fcf`=每号取 djriqi 最新，可叠加；20 列导出 | `gongdan:view/manage` |
| 维抢修加班 Jiaban | `/api/jiaban`(22) `/jiaban` | 新表 jiaban(3095)/jiabanrenyuan(51)/jiaban_attachment(508)；lei bit→tinyint；本月=上月21~本月20；附件短令牌、缺文件下载兜底；工资汇总=round(工日×单价)+人民币大写；工日=小时/8 保 1 位 | `jiaban:view`（删除限本人） |
| 领料结算 jiesuandan | `/api/jiesuandan` `/jiesuandan` | `jiesuancailiao`(47)/`jiesuandetail`(392)/`cailiao_fujian`(46)，SUM 均 2005607.01；明细引用 lingliaodetail，增删改联动 jiesuannum/jiesuanzt、lingliao.shzt、material.lastdanjia；销售结算表+采购申请/验收单+打印页 | `jiesuandan:view/manage` |
| 材料结算查看 jiesuan | `/api/jiesuan` `/jiesuan` | 只读，复用 lingliao/jiesuandan/material；`shzt in (2,5,6)` + 部门子树，剩余可结算≤0 灰显；旧 SaveJiesuan/Edit 无入口不复刻 | `jiesuan:view` |
| 车辆保险 Baoxian | `/api/baoxian` `/vehicle/baoxian` | `cl_baoxian`(432, SUM=406072.84)，cheid 直对旧 cl_che；`lx` 仅商业车险/交强险（历史「商业险」按关键字归并）；编辑限登记人本人或 djname 空；导入=第4行起 B~I 列+文件名含「保险」+保单号库内/批内去重；合计挂全量 tj；导出 12 列 | `baoxian:view` |
| 车辆各类费用 CLfeiyong | `/api/clfeiyong`(6) `/vehicle/clfeiyong` | `cl_feiyong`(34, SUM=1285.0000)，**逐列 0 差异**；无 bmid→`cheid→cl_che.bmid` 子树；类别固定洗车/高速/停车（实际只有洗车）；关键字=收费单位 OR 车号；合计=筛选后全量；补旧 `Editgz` 漏存 jine、补增删改 403；导出 9 列 `.xlsx`，列表与导出共用 `fee_query`；15 列 <1920px 隐 2 日期列 | `vehicle:view` |

## 三、关键踩坑
- 加班三套 id：`overtime_dept` 镜像树连 id 原样导入（不套 bmid_map）；旧 `bb_bumen.id`→只作用于 `sys_bumen_id`/`mapped_bumen_id`/`scope_bumen_id`；旧 `bb_user.id`→`user_map.json`。`is_field`=旧 `_parentId==1`。审批关闭时核销直通 `draft→printed→verified`；个人记录「head + 独立明细(apply_id IS NULL)」两种载体都要查；核销下拉初值/首查/重置统一当前月；新 `users` 只有 3 个、不导旧账号。
- ⚠️ `SessionLocal(autoflush=False)`：改完 ORM 对象后用 `with_entities(列)` 聚合读到旧值，必须 `db.flush()` 再算（jiesuandan 改明细重算 zonge 踩过）。
- chelwx：`import_vehicles.py` 也会 TRUNCATE `cl_wxdan`；前端漏 import `getRepair` build 不报错、只在编辑弹窗抛 ReferenceError → 必须真机回归。`sim` 表模型统一在 `models/simcard.py`（`phone.py` 别名导入，⛔别重复声明）。
- jcxt：新 Department 无 `cj` 排序用 id；无日期参数默认本月；列表项键小写 `id`；审批通过不可编辑/撤回；奖励硬编码同安 旧8→新12。roadrepair：编辑不改 `current_progress`；公路局价格只取专属价、其它单位含通用价(NULL=通用)；进度排序 `progress_date desc,id desc`；MainLayout 中 project 与 roadrepair 都在才合并子菜单组。
- material：路由挂 `/api/materials` 后子路径别再写 `/materials`（405）；动态 `GET/DELETE /{mid}` 放文件末尾防吞静态路径；Numeric 先 `float()`；进出库=入库流水+工单领料负数（按 `WorkOrder.CreateTime`，两源各取 page*size 内存合并分页）；预警不限部门；大口径 `dakoujing=='on'`。
- oiltj：部门筛选是子树语义（旧 StartsWith(cj)），复用 `oiltj.py` 的 `_subtree_ids`；SQLAlchemy `filter(True)` 不行要条件拼接；1 月「上月」跨年两处口径不同；财务导出只按用户作用域。
- workorder：⛔重跑 `import_materials.py`/`import_roadrepair.py` 会清工单新数据；列表大口径=`dakoujing` 非空、导出=`=='on'`（照旧两处不同）；提交/删除即时增减 `material_library.num`、不写 in_stock_record、允许负库存；编辑=回滚旧明细再扣新；工单号失焦调内网工作流（3 秒超时降级「暂无数据」），已有领料记录时载入编辑态；「取消」保留班组/类别、「重置」清空；附件短令牌 `workorder_attach`(180min)、只可删本人上传。
- 外部工单详情与 jcxt/gongdan **同源**：`app/services/workorder_external.py` 的 `fetch_workorder(no, timeout)` + `workorder_detail(d)`；workorder `/external/info`、`/external/images`（3 图槽、`workorder_wo_image` 短令牌、白名单代理、缺图透明 PNG，权限 `workorder:view`）；gongdan `/by-no`、`/images` 同上游同结构（`success/message/data`、`flow_id`、3 图槽），仅换权限码。前端抽屉照抄 `WorkOrderManage.vue` 的 `woInfo`+`el-descriptions`+`.wo-*`，⛔别自绘，图片失败不清详情。
- workorder 页面自适应：`calc(100vh - 94px)` 整页 flex overflow hidden、上 55%/下 45%、左:右=1.15:0.85；`ResizeObserver` 实测后给 `el-table` 传 **max-height**（不要 height/固定 px）；行高 28px、每页 10 条、`wide`(>=1500px) 隐次要列；量滚动看 `.el-scrollbar__wrap`。
- gongdan：⛔`gongdan`(76870) 是热线工单镜像，与内网 `getFlowInfoById` 的 flow 工单两套数据，只供 GetGongdanCount 计数；旧服务 `bmid` 在分页后过滤是 bug，新系统分页前过滤；旧编辑弹窗漏水量不回显会清空，新系统已修正；Excel 导入进度遮罩是死代码不复刻；17 列 <1920px 隐 3 列。
- ⚠️ **SQL Server `datetime` → MySQL `DATETIME(0)` 会四舍五入进 1 秒**：旧精度 1/300 秒(pyodbc 读出 `.997`)，直接写完差 1 秒（cl_feiyong 34 行 35 处）；导入统一 `value.replace(microsecond=0)` 才能逐列 0 差异（`docs/数据迁移约定.md` 约定 5，后续含日期表照此）。
- 新列宽经验：多列固定宽合计 ≈1588px 时 1600px 窗口内容区仅 ~1360px → **必须 <1920px 隐次要列**（clfeiyong 用 1500 阈值仍出横向滚动条）；CDP 量 `.el-table__body-wrapper .el-scrollbar__wrap` 的 scrollWidth/clientWidth 判定。Vite 首次 HMR 会吐别模块 TDZ 噪声（`JiabanManage before initialization`），CDP 回归需冷刷新后清空计数再统计 JS 异常。

## 四、验证基线
`smoke_material` 62/62、`smoke_roadrepair` 46/46、jcxt 46/46、`smoke_oiltj` 30/30、`smoke_workorder` 44/44、`smoke_gongdan` 71/71、`smoke_jiesuandan` 42/42、`smoke_jiesuan` 10/10、`smoke_jiaban` 56/56、`smoke_baoxian` 28/28、`smoke_clfeiyong` 62/62（另 `verify_oiltj_vs_old` 交叉核对通过）；各模块 `npm run build` 通过，Gongdan/Baoxian/Jiaban/CLfeiyong 另做 Chrome CDP 实机（0 JS 异常、无滚动条）。新增模块照此 TestClient 全链路 + build + 浏览器回归。
