# 模块速查 / 踩坑 / 验证基线（pysswhl）

> 从 `MEMORY.md` 拆出以控制注入体积。**动手改某个模块前，先读本文件对应行**；全局约定见 `MEMORY.md`。

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
| 车辆费用明细统计 chelfytj | `/api/chelfytj`(3) `/vehicle/chelfytj` | **纯只读报表，无新迁表**：`cl_che`(269)+四表金额聚合(PlusOil.ptime/cl_wxdan.jcriqi/cl_baoxian.tbdate/cl_feiyong 分 lx)；部门=dept_scope_ids，下拉再筛子树；zt=0 含已删除、1/2 正常/报废、**3 已删除修正为 delf==0**（旧代码 delf==3 恒空）；footer 合计=筛选后全量车（随筛选变化）；序号全量连续、分页内存切片、total=车辆数；模糊=12 字段 OR；日期缺省本年 1-1~12-31、结束扩 23:59:59；导出 10 列黄底合计（旧标题硬编码 2023→按起始年+部门名生成）；导出列序与页面列序不同（导出油费在前），均照旧 | `chelfytj:view` |

| 固定资产 gdzc | `/api/gdzc`(9) `/gdzc` | `zc_cw`(41383, SUM yz=15818385660.58 / jz=8129039203.67)/`zc_lb`(29)/`zc_nd`(4 死表)/`zc_baofeidan`(176)/`zc_baofeitp`(208)；**nd 是按年度快照且必过滤**(默认 max=2025，7060 行)；22 列 + footer 全量 SUM(yz/jz)；确认/取消盘点 + 备注(修旧 Editxz 判断旧值 bug)；报废单详情弹窗；明细表(17 列)/盘点表(14 列)两导出；导入盘点表按 (nd,zccode) 去重(旧入口在 userman 且无鉴权，已并入本页加权限) | `gdzc:view` |
| 清理报告 baofeizc | `/api/baofeizc`(15) `/baofeizc` | **无独立明细表**：`zc_cw.baofeidanid` 挂报废单；关键字搜的是已挂单资产明细；有明细禁删；候选=本部门 baofeiqk IS NULL ∪ 已挂本单；加报废按 zccode 取最大 nd 行、其它年度只标「已报废」，每单≤10 条；图片 `zc_baofeitp.dizhi` 走 `finance_image` 短令牌代理(旧 /Upload 多缺失→透明 PNG)，新上传落 `backend/uploads/baofeidanImages/`；清理报告 Excel 9 列+合计+签章栏 | `baofeizc:view` |
| 物资采购申请 wzcgsq | `/api/wzcgsq`(13) `/wzcgsq` + `/wzcgsq/print` | `wzcgsq`(1, SUM hj=446)/`wzcgsq_mx`(1)（旧库仅 1 条测试数据）；`bumen` 手填文本、`bmid/cj` 取登录人部门双轨；scope 默认 mine(所以超管打开是空表，点「显示全部」才有数据)；`cj` 前缀过滤靠 `dept_cj_map()`；服务端重算 xiaoji/hj；编辑保留 djriqi(修旧重置 bug)、整单替换明细；打印页两 A4 单 + 申请单/验收单/明细模板 3 个 xlsx；**无状态机无审批流** | `wzcgsq:view` |

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
- gongdan：⛔`gongdan`(76870) 是热线工单镜像，与内网 `getFlowInfoById` 的 flow 工单两套数据，只供 GetGongdanCount 计数；旧服务 `bmid` 在分页后过滤是 bug，新系统分页前过滤；旧编辑弹窗漏水量不回显会清空，新系统已修正；Excel 导入进度遮罩是死代码不复刻；17 列 <1920px 隐 3 列；添加弹窗工单号失焦=先清空除工单号外全部字段再回填(2026-11-11 用户口径)，编辑弹窗不清空。
- ⚠️ **SQL Server `datetime` → MySQL `DATETIME(0)` 会四舍五入进 1 秒**：旧精度 1/300 秒(pyodbc 读出 `.997`)，直接写完差 1 秒（cl_feiyong 34 行 35 处）；导入统一 `value.replace(microsecond=0)` 才能逐列 0 差异（`docs/数据迁移约定.md` 约定 5，后续含日期表照此）。
- 新列宽经验：多列固定宽合计 ≈1588px 时 1600px 窗口内容区仅 ~1360px → **必须 <1920px 隐次要列**（clfeiyong 用 1500 阈值仍出横向滚动条）；CDP 量 `.el-table__body-wrapper .el-scrollbar__wrap` 的 scrollWidth/clientWidth 判定。Vite 首次 HMR 会吐别模块 TDZ 噪声（`JiabanManage before initialization`），CDP 回归需冷刷新后清空计数再统计 JS 异常。

- 财务管理：7 表由 `scripts/import_finance.py` 一次导入(TRUNCATE 重导、bmid_map + user_map 逐行映射、datetime 截微秒)，只碰本模块 7 表；旧 `cj`(000103 集美 / 000109 杏林)特例在 `finance_scope_ids` 里以新 id 10→16 子树保留；`wzcgsq` 历史单 `userid` 按 user_map 映射(3→7 林春)、`bmid` 1→7。⚠️ **Element Plus 展开列插槽是 `#default` 不是 `#expand`**：写错会让 row 为 undefined，`renderExpand` 抛 TypeError 且整张表渲染为空（baofeizc 首轮 CDP 抓到）。⚠️ smoke 里同一 SQLAlchemy Session 的事务快照读不到 TestClient 另一连接刚提交的改动，断言前要 `session.commit()` 再 `get()`；清理临时用户要逐个 ORM delete + commit，bulk delete 会撞 user_role 级联 StaleDataError。

## 四、验证基线
`smoke_material` 62/62、`smoke_roadrepair` 46/46、jcxt 46/46、`smoke_oiltj` 30/30、`smoke_workorder` 44/44、`smoke_gongdan` 71/71、`smoke_jiesuandan` 44/44、`smoke_jiesuan` 10/10、`smoke_jiaban` 56/56、`smoke_baoxian` 28/28、`smoke_clfeiyong` 62/62、`smoke_chelfytj` 41/41、`smoke_finance` 63/63（另 `verify_oiltj_vs_old` 交叉核对通过）；各模块 `npm run build` 通过，Gongdan/Baoxian/Jiaban/CLfeiyong/ChelFyTj/**财务管理三页** 另做 Chrome CDP 实机（`ui_check_finance_cdp.js`，0 JS 异常、无滚动条、截图 `ui_finance_*.png`）。新增模块照此 TestClient 全链路 + build + 浏览器回归。
