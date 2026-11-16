# 内网部署手册（Ubuntu 22.04 · 172.16.43.126）

面向"不熟 Linux"的场景写的,每一步都写清**在哪敲、敲什么、看到什么算成功**。
整套方案只对外开 **1 个端口(18080)**,不装 nginx、不影响机器上已有的 xinkong 容器。

> 环境现状(主机/Docker/端口/网络/接入方式)见 `docs/服务器环境记录.md`,换人接手或重装前先读它。

## 一、这套东西长什么样

| 组件 | 形态 | 端口 | 说明 |
|---|---|---|---|
| 前端 | 已构建的 `frontend/dist` | — | 由后端进程直接托管,无需单独部署 |
| 后端 | Docker 容器 `sswhl-api`(镜像 `sswhl-api:1.0`) | 宿主 `0.0.0.0:18080` | 自带 Python 3.10 + 37 个依赖 |
| 数据库 | Docker 容器 `sswhl-mysql`(镜像 `mysql:8`) | 宿主 `127.0.0.1:13306` | 只监听本机,不对外 |
| 代码 | 从 `/opt/sswhl` 只读挂载进容器 | — | 更新程序 = 覆盖文件 + 重启容器 |
| 依赖 | 37 个离线包已打进镜像 | — | 服务器无需联网 |

宿主侧只提供 **Docker**(引擎 + compose)。不装 Python、不建 venv、不配 systemd、不装 nginx。

为什么不装 nginx:少一个组件就少一处能坏的地方,单端口足够内网几百人使用。
为什么不复用现有 MySQL:`xinkong` 那套是别人的生产库,混用会互相牵连;独立容器 + 独立数据卷,出问题能整体删掉重来。

## 二、把安装包传上去

要传的是**三个**文件,都上传到服务器 `/home/sysmgr/`(你自己的家目录,有写权限):

| 本地文件 | 大小 | 内容 |
|---|---|---|
| `E:\pysswhl\sswhl-deploy.tar.gz` | 50.2 MB | 代码 + 前端 dist + deploy 脚本 + 离线依赖包 |
| `E:\pysswhl\sswhl-api-image.tar` | 71 MB | API 镜像(已装好 Python 3.10 与 37 个依赖) |
| `E:\pysswhl\deploy\import\sswhl_new.sql.gz` | 22.3 MB | 数据库导出(**118 张表**,2026-11-15 版) |

第三个文件在 `deploy\import\` 子目录里,不在根目录。合计 144 MB。

`sswhl-update.tar.gz`(1.7 MB)是**以后日常更新**用的精简包,首次部署不用传;
代码/前端有改动但依赖没变时,只传它 + 数据库 dump 即可(见**第十二节**)。

> 三个产物都在开发机用一条命令重新生成:
> `backend\.venv\Scripts\python.exe deploy\tools\make_release.py`(库没变时加 `--no-db`)。
> 它会导出全量库、打两个包、校验新模块与新 dist 是否进包,并打印 MD5。

传完先校验,别急着解压:

```bash
cd ~ && md5sum sswhl-deploy.tar.gz sswhl-api-image.tar sswhl_new.sql.gz
```

三个值与开发机给出的 MD5 逐字一致才算传完。网页上传最容易"看着传完了、实际断在半路",
其中 71 MB 那个最常出问题,断了以后 `docker load` 只会报 `unexpected EOF`,不好定位。

> ⚠️ 包内含 `backend/.env`,里面有 `PASSWORD_PEPPER`(用户密码哈希的胡椒)。
> 必须和开发机保持一致,导入老数据后大家才能用原密码登录。此包**不要外传**。

## 三、解压 + 一键安装

在网页终端里逐条执行(每条回车后等它跑完):

```bash
# 1) 解压到 /opt/sswhl(已存在会覆盖同名文件,不会动数据和配置)
sudo mkdir -p /opt/sswhl
sudo tar -xzf ~/sswhl-deploy.tar.gz -C /opt/sswhl

# 2) 看一眼文件齐不齐(应看到 backend / deploy / frontend 三项)
ls /opt/sswhl

# 3) 导入 API 镜像(约 20 秒,全程不联网)
sudo docker load -i ~/sswhl-api-image.tar

# 4) 一键安装 + 导数据(首次部署,约 2~4 分钟)
sudo bash /opt/sswhl/deploy/install-container.sh --dump ~/sswhl_new.sql.gz
```

第 4 步会依次做:起 MySQL 容器(`127.0.0.1:13306`)→ 建库建账号 → 导入 118 张表 →
**在容器内**跑 `scripts.init_db` 补权限码 → 起 API 容器(对外 18080)→ 健康检查。
**任何一步失败都会停下并打印原因**,不会留半截状态;脚本可重复执行。

宿主侧只需要 Docker:不装 Python、不建 venv、不配 systemd、不装 nginx。

成功时最后会打印:

```
  访问地址 : http://172.16.43.126:18080
  健康检查 : curl http://127.0.0.1:18080/api/health
```

## 四、单独导入或重导数据

第 3 节的第 4 步已经带了 `--dump`,首次部署**不需要**再单独导入。
后续要重导(例如把服务器重置成开发机快照)时用:

```bash
# 全量覆盖:会先自动备份,再 DROP 重建 118 张表。服务器上已录入的数据会丢失
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --yes

# 只覆盖几张基础表(保留其它数据)
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --tables departments,gongdancailiao
```

细节见**第十一节**。

## 五、验收清单

| 检查项 | 怎么做 | 通过标准 |
|---|---|---|
| 页面能开 | 浏览器访问 `http://172.16.43.126:18080` | 出现登录页,不是 404/白屏 |
| 接口正常 | `curl http://127.0.0.1:18080/api/health` | `{"status":"ok"}` |
| 老账号能登 | 用原有管理员账号登录 | 能进首页(说明 pepper 一致) |
| 数据在 | 抽查加班/工单/财务管理各一条 | 列表有数据、能翻页 |
| 附件能下 | 打开一个带附件的记录 | 图片/文件能预览下载 |
| 热力图 | 测漏成果汇总页面 | 有底图;没有则见下方"瓦片" |
| 重启自恢复 | `sudo reboot` 后等待 2 分钟 | 页面自己回来(两个服务都是开机自启) |

## 六、日常运维(就这几条)

```bash
sudo docker ps | grep sswhl                                   # 两个容器活着没
sudo docker logs -f sswhl-api                                 # 实时日志(Ctrl+C 退出)
sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api restart api
sudo docker exec -it sswhl-mysql mysql -uroot -p'<root密码>'   # 进数据库
sudo bash /opt/sswhl/deploy/update.sh --status                # 版本/数据量/备份/磁盘

# 手工备份数据库(update.sh 每次更新前会自动备份,这里是不更新时的额外备份)
sudo docker exec sswhl-mysql mysqldump -uroot -p'<root密码>' --single-transaction \
  --default-character-set=utf8mb4 sswhl_new | gzip > /opt/sswhl-backup/manual-$(date +%F).sql.gz
```

`<root密码>` 在 `/opt/sswhl/deploy/.env` 里(`sudo cat` 查看)。

**更新程序 / 更新数据 / 回滚**:不要手工解压覆盖,统一用 `deploy/update.sh`,见**第十一节**。
它可以自动备份、只替换代码目录、按需补表结构、失败能回滚。

## 七、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面打不开 | 容器没起 / 端口不通 | `docker ps \| grep sswhl`;`ss -lntp \| grep 18080` |
| 页面能开、登录报 500 | 数据库连不上 | `docker ps \| grep sswhl-mysql`;`docker logs sswhl-api --tail 50` |
| 登录提示密码错误(所有人都错) | `PASSWORD_PEPPER` 与老数据不一致 | 恢复开发机的 pepper 值再重启,不要重置密码 |
| 某张表提示不存在 | `lower_case_table_names` 没设成 1 | 检查 compose 参数;若已用错参数初始化过,需删数据卷重建再导入 |
| 中文乱码 | 字符集不一致 | 确认容器 `utf8mb4`;导入时带 `--default-character-set=utf8mb4` |
| 附件上传失败 | `uploads` 权限 | `sudo chown -R sswhl:sswhl /opt/sswhl/backend/uploads` |
| `1045 Access denied for user 'sswhl_app'@'172.x.x.x'` | `.env` 是 Windows CRLF,shell 取密码时尾部带不可见 `\r`,与容器内 Python 读到的值不一致 | `sudo sed -i 's/\r$//' /opt/sswhl/backend/.env`,再 `sudo bash /opt/sswhl/deploy/install-container.sh --only-account`(新版脚本会自动转 LF) |
| `ModuleNotFoundError: No module named 'exceptiongroup'` | 镜像按 Python 3.10 构建,而依赖是在 3.12 环境解析的;anyio 在 3.10 上需要该包,3.11+ 才并入标准库 | 换新镜像(已补该依赖);详见第十一节「离线重建镜像」 |
| 热力图没底图 | 瓦片没部署 | 见下节 |

## 八、热力图瓦片(269 MB / 65204 个 png,单独传)

瓦片是 GCJ-02 高德离线底图,目录结构 `{z}/{x}/{y}.png`,层级 z10~z17。
**必须打包成 tar 传**,直接传目录的话 6.5 万个小文件通过堡垒机网页传输会慢到无法接受。
PNG 本身已是压缩格式,所以 tar **不再 gzip**(压不动还费时间)。

### 8.1 开发机打包(已做好,在 `build/tiles/`)

分三个包,便于先传小的让地图尽快可用、大包断了自己重传不影响前面的:

| 包 | 内容 | 大小 | png 数 |
|---|---|---|---|
| `tiles-z10-14.tar` | z10~z14(全市/片区级) | 8.1 MB | 1127 |
| `tiles-z15-16.tar` | z15~z16(街道级) | 76 MB | 15457 |
| `tiles-z17.tar` | z17(最细,压到单栋楼) | 185 MB | 48620 |
| `sswhl-compose-patch.tar.gz` | 含瓦片挂载的 compose | 2.3 KB | — |

```bash
cd /e/sswhl/sswhl/Content/Tiles      # 旧系统的瓦片源目录
tar -cf tiles-z10-14.tar 10 11 12 13 14
tar -cf tiles-z15-16.tar 15 16
tar -cf tiles-z17.tar 17
```

### 8.2 服务器解压

```bash
sudo mkdir -p /opt/sswhl/tiles
sudo tar -xf ~/tiles-z10-14.tar -C /opt/sswhl/tiles
sudo tar -xf ~/tiles-z15-16.tar -C /opt/sswhl/tiles
sudo tar -xf ~/tiles-z17.tar     -C /opt/sswhl/tiles      # 可以先不传这个
```

解压后应是 `/opt/sswhl/tiles/10/3351/1710.png` 这样的结构。**属主 root、权限 644 即可**,
容器以只读方式挂载,非 root 用户能读就行:

```bash
sudo chmod -R a+rX /opt/sswhl/tiles      # 保险:6.5 万文件约几秒
ls /opt/sswhl/tiles                      # 应看到 10 11 12 13 14 15 16 17
```

### 8.3 让容器看到瓦片(关键)

compose 里 api 服务必须有这一行只读挂载:

```yaml
      - ../tiles:/app/backend/assets/tiles:ro
```

挂到 `assets/tiles` 是为了命中 `config.py` 的默认探测顺序
(`CELOU_TILE_DIR` → `backend/assets/tiles` → 旧系统目录),这样**不用改 `.env`**。
若是老版本 compose,用补丁包覆盖(会先备份):

```bash
sudo cp /opt/sswhl/deploy/docker-compose.yml /opt/sswhl/deploy/docker-compose.yml.bak
sudo tar -xzf ~/sswhl-compose-patch.tar.gz -C /opt/sswhl
```

### 8.4 重启并验证

```bash
sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api up -d --force-recreate api

# 后端实际解析到的路径 + 读到的 png 数量(应打印 /app/backend/assets/tiles True 65204)
# 注意:镜像没有 /opt/venv(那是 docker build 路径才有的),解释器一律用 /usr/local/bin/python3.10
sudo docker exec -w /app/backend sswhl-api /usr/local/bin/python3.10 -c \
  "from app.api.routes.celou import _tile_root as r; p=r(); print(p, p.is_dir(), len(list(p.rglob('*.png'))))"
```

然后浏览器打开测漏页面切到热力图,底图应出现厦门地图;放大到 17 级看最细一层。

### 8.5 说明

- **不需要**再跑 `scripts/prepare_heatmap_tiles.py`:那个脚本是把瓦片复制进项目目录,
  容器化方案下目录是挂载进来的,直接指到挂载点就行。
- 不传瓦片不影响任何其他功能,只是热力图页提示"底图为空"(缺失瓦片返回 1×1 透明 PNG,不报 404)。
- 瓦片只在内网使用,界面保留 `© 高德地图` 版权,**不得对外分发**或做公网服务。

## 九、上线前待办

- [ ] 防火墙只放行 `18080`(内网段),`13306` 不要放行(`ufw allow from 172.16.0.0/12 to any port 18080`)
- [ ] `backend/.env` 与 `rsa_key.pem` 权限 600(脚本已设),**单独备份 pepper**
- [ ] 改掉默认初始密码 `abc123456`(改 `.env` 后重启)
- [ ] 确认服务器时区 `Asia/Shanghai`(`timedatectl`),否则 JWT 过期判断会偏
- [ ] 确认到短信网关 `172.16.110.170`、工单上游 `172.16.73.91` 的网络可达性(不通只影响对应功能)

## 十、关于镜像的几个细节

`sswhl-api-image.tar`(70.6 MB)是**在开发机离线组装好的完整镜像**,已装好 37 个依赖、后端代码
与 `frontend/dist`,打了两个 tag:`sswhl-api:1.0` 与 `python:3.10-slim`(后者留着,以后用
`Dockerfile.api` 重建时 base image 现成)。服务器上**只需 `docker load`,全程不联网**。
安装步骤见**第三节**,这里只讲几个容易踩的点。

**`--profile docker-api` 这个参数不能漏**:`api` 服务带 `profiles: ["docker-api"]`,不带该参数时
`up -d` 只起数据库。这样做的好处是,万一容器方式出问题,可以随时用 `install.sh` 退回宿主方案
(venv + systemd),两条路互不干扰。

**如果你之前用 `install.sh` 装过**(宿主 venv + systemd),`install-container.sh` 会自动
`systemctl disable --now sswhl-api` 把 18080 让出来。手工回退:

```bash
sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api down
sudo systemctl enable --now sswhl-api
```

**两种方案互迁时搬附件**(容器内路径 `/app/backend/uploads` ↔ 宿主 `/opt/sswhl/backend/uploads`):

```bash
# 宿主 → 容器
sudo docker run --rm -v sswhl_uploads:/data -v /opt/sswhl/backend/uploads:/src \
  sswhl-api:1.0 cp -a /src/. /data/
# 容器 → 宿主
sudo docker run --rm -v sswhl_uploads:/src -v /opt/sswhl/backend/uploads:/data \
  sswhl-api:1.0 cp -a /src/. /data/
```

镜像不含 `.env` 与 `rsa_key.pem`(避免口令与私钥进镜像层),由 compose 只读挂载进容器;
容器内 `DB_HOST`、`UPLOAD_DIR`、`FRONTEND_DIST` 由 compose 的 `environment` 覆盖为容器内路径。

⚠️ **这两个文件的属主必须与容器运行用户一致**。手工组装的 `sswhl-api:1.0` 没有 `User` 字段,
以 **root** 运行;而 `Dockerfile.api` 里有 `USER sswhl`(uid 10001),用它重建的镜像属主就是 10001。
属主不对的症状是容器一起就退出,日志里是 `Permission denied: '/app/backend/.env'`。
`install-container.sh` 会让镜像自己跑一次 `id -u`,拿到真实 uid 再 `chown`,两种镜像都适用。

需要重建镜像时,`deploy/tools/build_image_offline.py` 可复现同一过程(无 Docker 环境下手工组装)。


## 十一、日常更新(改程序 / 改数据 / 回滚)

全部用一条脚本 `deploy/update.sh`,不用手工解压覆盖。**每个动作都会先备份**,
备份放 `/opt/sswhl-backup`,默认保留最近 10 份,回滚就从这里取。

```bash
sudo bash /opt/sswhl/deploy/update.sh --help      # 看全部用法
sudo bash /opt/sswhl/deploy/update.sh --status    # 当前版本/镜像/容器/数据量/备份/磁盘
```

### 11.1 更新程序(最常见,约 20 秒)

代码与前端产物是**从宿主目录只读挂载进容器**的,所以更新程序**不需要重建镜像**
(那个 71 MB 的 tar 只在依赖变化时才要重新传)。

```bash
# 开发机:一条命令重新生成两个包(见第十二节)
#   backend\.venv\Scripts\python.exe deploy\tools\make_release.py --no-db
# 上传 sswhl-update.tar.gz(1.7 MB,精简包)到 ~ 后:
sudo bash /opt/sswhl/deploy/update.sh --pkg ~/sswhl-update.tar.gz
```

脚本依次做:校验包完整 → 备份代码目录 → 原子替换 `backend/app`、`backend/scripts`、
`frontend/dist` → 重启 API 容器 → 健康检查。**不动** `backend/.env`、`rsa_key.pem`、`uploads`。

| 加的参数 | 作用 |
|---|---|
| `--schema` | 顺手在容器内跑 `scripts.init_db`,补齐新增的字段/表/权限码 |
| `--backup-db` | 连数据库一起备份(改结构前建议加) |

**依赖变了怎么办**:如果 `requirements-linux.txt` 有改动,脚本会明确警告——依赖装在镜像里,
挂载覆盖不到,需要在开发机重新生成 `sswhl-api-image.tar` 后执行:

```bash
sudo bash /opt/sswhl/deploy/update.sh --image ~/sswhl-api-image.tar
```

### 11.2 表结构变了

模型新增字段时 `create_all` 不会改已有表。两条路:

- 脚本会自动补的:`scripts/init_db.py` 里的 `ensure_columns()` 覆盖了 `users`、`departments` 等表的
  历史变更,`--pkg ... --schema` 自动执行;
- 其余新字段:开发机 `init_db.py` 里加一段 `ALTER TABLE`,一起打进包,再用 `--schema`。

**现状提醒**:项目没有 Alembic 迁移体系,结构变更靠 `create_all` + 手工 ALTER。加字段是安全的,
删列/改类型要人工确认——`create_all` 不会删列,所以旧列会一直留着(无害)。

### 11.3 更新数据库数据(两种,差别很大)

⚠️ 导出的 SQL 里带 **118 条 `DROP TABLE IF EXISTS`**,全量导入 = 删表重建。**服务器上录入的数据会没**。

**A. 只补几张基础表(推荐,保留其它数据)**
适合:开发机补了材料库、部门、车辆等基础数据,要同步到服务器。

```bash
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --tables gongdancailiao,departments
```

从完整 dump 里精确抽出这几张表的 DROP+CREATE+INSERT,只重建它们,其它表一个字节不动。
表名写错会跳过并提示。**注意**:这几张表被重建后自增 id 会重置,若别的表用 id 引用了它们,引用可能错位——
纯基础数据表没这个问题,业务表(工单、结算)不要这么干。

**B. 全量覆盖(危险)**
只在"服务器上没有需要保留的新数据"时用,例如首次上线、或把测试环境重置成开发机快照。

```bash
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --yes
```

会先自动 `mysqldump` 备份到 `/opt/sswhl-backup/db-*.sql.gz`,然后整库覆盖。
不带 `--yes` 时只打印后果、不执行。

**C. 线上运行起来之后的正解**
一旦有人在服务器上录数据,**开发机的库就不再是权威**了。此后:

- 基础表往服务器同步 → 走 A;
- 业务数据 → 只从服务器往开发机导(反向),永远不要在服务器上跑全量覆盖;
- 结构变更 → 用 `--schema` 或单独写 `ALTER`,不要靠重导。

### 11.4 回滚

```bash
sudo bash /opt/sswhl/deploy/update.sh --rollback
```

取**最近一份代码备份**覆盖回去并重启,健康检查通过才算成功。回滚只退代码,不退数据库
(数据要退就 `gunzip -c /opt/sswhl-backup/db-xxxx.sql.gz | sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>'`)。
因为 `update.sh` 在替换前一定先备份,所以任何一次更新都能退回上一版。

### 11.5 一条命令都没生效时的自查

```bash
sudo bash /opt/sswhl/deploy/update.sh --status     # 版本时间戳有没有变
sudo docker logs sswhl-api --tail 50               # 起不来就看这里
sudo docker exec sswhl-api ls -l app/main.py       # 挂载是否生效
```

如果 `--pkg` 后页面还是旧的,多半是浏览器缓存(强制刷新 `Ctrl+F5`)。

### 11.6 离线重建 API 镜像(依赖变了才需要)

依赖装在镜像里,宿主目录挂载覆盖不到。`requirements-linux.txt` 一改,就得重做镜像。
开发机没有 Docker,所以用脚本**手工组装**(复用 base 层,只重做最上面一层):

```bash
# 开发机,在仓库根目录
.venv/Scripts/python.exe deploy/tools/rebuild_image_local.py
# 输出 sswhl-api-image.tar(约 71MB),旧镜像自动备份为 build/image-old.tar
```

它**完全不联网**:base 的 4 个层从现有镜像里原样复用(43MB),只重新 pip 装依赖 +
复制代码,然后重写 config 的 `diff_ids`/`history` 并自检每层 sha256。

> ⚠️ 跨版本装依赖有个坑:开发机是 Python 3.12,镜像里是 3.10,而
> `pip install --python-version 3.10` **不会评估** `python_version < "3.11"` 这类依赖标记。
> 所以只能在 3.10 上生效的条件依赖必须**无条件写进** `requirements-linux.txt`
> (目前只有 `exceptiongroup`,anyio 需要)。漏了的表现是容器启动即崩:
> `ModuleNotFoundError: No module named 'xxx'`,日志里能看到。
> 修改依赖后建议先自查闭包完整性,再重建镜像。

服务器上换镜像:

```bash
sudo docker load -i ~/sswhl-api-image.tar
sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api \
  up -d --force-recreate api
curl http://127.0.0.1:18080/api/health
```

`--force-recreate` 是必须的:镜像 tag 没变(`sswhl-api:1.0`),不加这个参数 compose
会认为容器配置没变、继续用旧镜像。数据库容器不受影响,不会重启。

---

## 十二、本次上线:传导完好率 4 模块 + 用户权限(2026-11-15)

服务器 11-14 装的是**旧版**:代码包 11-15 00:19、数据库 dump 11-13 08:12(114 表)。
这一节是把它升到今天这版的**最短路径**;全新机器首次安装仍走**第三节**,不用看这里。

### 12.1 为什么数据库必须一起更新

| 变化 | 旧 dump(11-13) | 新 dump(11-15) |
|---|---|---|
| 表数 | 114 | **118**(+`cd_whl` `cd_gz` `cd_daxiu` `cd_xz`) |
| 传导历史数据 | 无 | 184 / 3132 / 410 / 1355 行 |
| 权限码 | 无 `cd*` | 5 个:`cdwhl:view` `cdwhl:manage` `cdgz:view` `cddaxiu:view` `cdbd:view` |
| 用户与角色 | 未全量迁移 | 199 账号 + `legacy_*` 角色,13 个老账号补了传导权限 |
| `consol_tb` | 无开关 | 「锁定传导报表」(默认 0=未锁) |

只更新代码不导数据 → 点菜单报 `Table 'sswhl_new.cd_whl' doesn't exist` 或菜单根本不显示。
**代码与库必须同时升**。

### 12.2 只传 2 个文件(堡垒机网页终端 → `~`)

> ⚠️ **本节与第十三节的 MD5 已过期**（16:30 又做了用户 id 1:1 重建，数据库重新导出）。
> 本次上线**请直接看第十四节**，别再用下面这两个校验值。

| 文件 | 大小 | MD5(本次) |
|---|---|---|
| `sswhl-update.tar.gz`(仓库根目录) | 4.3 MB | `927ee18bb6bf2e1e04860a46706ae416` |
| `sswhl_new.sql.gz`(`deploy/import/`) | 22.5 MB | `f96661b2900363a7942048ceb03e90c6` |

> 上表为**含加班数据的最新版**(14:4x)。早期 22.3 MB / `94a82f07...` 那份不含加班数据,见**第十三节**。

> 仓库根目录 `E:\pysswhl\` 已备好一份**改名副本** `sswhl_new_118.sql.gz`(同一个文件,MD5 相同)。
> 用堡垒机文件传输时直接选它,传到服务器天然就是新名字,不用再手工改名。

```bash
cd ~ && md5sum sswhl-update.tar.gz sswhl_new_118.sql.gz   # 两个值必须与上表逐字一致
```

> ⚠️ **最容易踩的坑(2026-11-15 实际发生过一次)**:服务器上 11-14 已传过同名
> `sswhl_new.sql.gz`,再次上传时网页传输**不一定覆盖**,结果导入的还是 11-13 的 114 表旧 dump。
> 症状很有迷惑性:脚本一切正常、健康检查 `{"status":"ok"}`,但输出里写的是
> 「全量覆盖数据库(含 **114** 条 DROP TABLE)」,传导 4 张表全空、用户数还是 3。
> **做法**:上传时换个新文件名(如 `sswhl_new_118.sql.gz`),或先 `rm ~/sswhl_new.sql.gz` 再传;
> 导入**之前**务必跑这三条,第一条必须等于下表的 MD5、第二条必须等于 **118**:
>
> ```bash
> cd ~ && md5sum sswhl_new_118.sql.gz
> gzip -dc sswhl_new_118.sql.gz | grep -c '^DROP TABLE IF EXISTS'     # 118
> gzip -dc sswhl_new_118.sql.gz | grep -m1 'CREATE TABLE `cd_whl`'    # 要有输出
> ```
> 后面命令里的 `~/sswhl_new.sql.gz` 相应换成你实际用的文件名。
> 导入后看 `--status`:**表数 118、用户数 199** 才算真的成功。

**不用重传 71 MB 镜像**:本次新代码只用到 `openpyxl` / `xlrd` / `fastapi` / `sqlalchemy`,
镜像里全有了,`requirements-linux.txt` 一个字没改。
**不用动 `backend/.env`**:`update.sh` 不碰它,`PASSWORD_PEPPER` 保持原值,老账号原密码照登。
> 若以后重新生成产物,MD5 以 `make_release.py` 输出为准(整包 MD5 不在此列,它含本手册、会随文档变化)。

### 12.3 路径 A(推荐:服务器上还没有要保留的新数据)

全量重导,一步把 118 张表和全部权限/用户换成开发机最新状态。**两条命令**,每条都会先自动备份。

> 前提:服务器用的是**纯容器方案**(`install-container.sh`)。先跑 `sudo docker ps | grep sswhl`,
> 应看到 `sswhl-api` 与 `sswhl-mysql` 两个容器。如果只看到 mysql、后端是 systemd 的
> `sswhl-api.service`,说明用的是老 `install.sh` 方案:先在网页终端执行
> `sudo bash /opt/sswhl/deploy/install-container.sh`(不带 `--dump`,不动数据)切到容器方案,再往下走。

```bash
# 0) 先确认两个容器都在、当前版本
sudo bash /opt/sswhl/deploy/update.sh --status

# 1) 更新程序:后端 app/scripts + 前端 dist,顺手补表结构与权限码
sudo bash /opt/sswhl/deploy/update.sh --pkg ~/sswhl-update.tar.gz --schema --backup-db

# 2) 全量重导数据库:自动备份到 /opt/sswhl-backup/db-*.sql.gz 后 DROP 重建 118 表
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --yes

# 3) 健康检查
curl http://127.0.0.1:18080/api/health
```

第 2 步会**删掉服务器上 11-14 之后新录入的数据**(试装阶段通常没有),备份一定在
`/opt/sswhl-backup/`,后悔了可以整库导回。低峰期执行更稳;想避免导入期间有请求打到半截的表,
可先 `sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api stop api`,
第 2 步末尾的 `restart_api` 会把它拉起来。

### 12.4 路径 B(服务器已有人录数据,不能全量覆盖)

只重建**本次涉及的 10 张表**,其余 108 张一个字节不动:

```bash
sudo bash /opt/sswhl/deploy/update.sh --pkg ~/sswhl-update.tar.gz --schema --backup-db
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_new.sql.gz --tables cd_whl,cd_gz,cd_daxiu,cd_xz,users,roles,permissions,user_role,role_permission,consol_tb
```

- 前 4 张 = 传导数据;后 6 张 = 用户/角色/权限/开关,**必须一组一起换**:它们用自增 id 互相引用,
  分开覆盖会错位。开发机上这 10 张表的段落已实测可正确抽取(各 1 条 CREATE + 1 条 INSERT + UNLOCK)。
- ⚠️ 代价:服务器上**新建的账号、改过的密码、手工加的角色**会被开发机版本覆盖掉。
  有这类改动就先 `sudo docker exec sswhl-mysql mysqldump ... > ~/before.sql` 留一份,再逐条补回。
- `--tables` 同样会自动备份数据库,且末尾自动重启 API。

### 12.5 验收(网页终端里跑)

```bash
# ① 4 表行数:应为 184 / 3132 / 410 / 1355
sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>' --table -e "
SELECT 'cd_whl' t,COUNT(*) n FROM sswhl_new.cd_whl UNION ALL
SELECT 'cd_gz',COUNT(*) FROM sswhl_new.cd_gz UNION ALL
SELECT 'cd_daxiu',COUNT(*) FROM sswhl_new.cd_daxiu UNION ALL
SELECT 'cd_xz',COUNT(*) FROM sswhl_new.cd_xz;"

# ② 权限码:应为 5 行
sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>' -e \
  "SELECT code FROM sswhl_new.permissions WHERE code LIKE 'cd%' ORDER BY code;"
```

`<root密码>` 在 `/opt/sswhl/deploy/.env`(`sudo cat` 查看)。

| 检查项 | 通过标准 |
|---|---|
| 老账号登录 | 原密码可登(说明 pepper 没变) |
| 左侧菜单 | 有「传导完好率」分组,下面 4 项;**只有被授权账号可见**,超管全可见 |
| 4 个页面 | 打开无 404/白屏,控制台 0 报错 |
| 数据 | 默认查当月(空表属正常),**报表月份切到 2026年10月**能看到历史数据 |
| 完好率合计行 | 切 10 月后表格底部有「合计」,4 行部门数据 |
| 导出/上传 | 完好率与大修 Excel 能下载,变动表模板能下载并上传 |
| 其它模块 | 加班/工单/财务管理抽查一条,确认没被重导影响 |

### 12.6 出问题的退路

```bash
sudo bash /opt/sswhl/deploy/update.sh --rollback     # 只退代码(退到上一次 --pkg 之前)
# 数据库回退(整库):先看清备份文件名再执行
ls -lh /opt/sswhl-backup/db-*.sql.gz
gunzip -c /opt/sswhl-backup/db-YYYYMMDD-HHMM.sql.gz | \
  sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>' --default-character-set=utf8mb4
sudo docker compose -f /opt/sswhl/deploy/docker-compose.yml --profile docker-api restart api
```

| 现象 | 原因 / 处理 |
|---|---|
| 全量导入显示「含 **114** 条 DROP」、传导页空白、用户数=3 | 传成 11-13 的旧 dump 了(同名文件没覆盖)。按 12.2 换新文件名重传、校验 118 条 DROP,再跑一次 `--db ... --yes` |
| `1046 / No database selected` | 传成单表 SQL 了;全量导入必须用带 `CREATE DATABASE` 的完整 dump |
| `Table 'cd_whl' doesn't exist` | 只跑了 `--pkg`,没跑 `--db`;按 12.3/12.4 补一次 |
| 菜单里没有「传导完好率」 | 权限表没同步(路径 B 漏了后 6 张表),或该账号本来没权限;用超管确认 |
| 全员密码错误 | `.env` 的 `PASSWORD_PEPPER` 被换过;恢复成开发机值再重启,**不要重置密码** |
| `--pkg` 提示包里缺目录 | 传错成别的 tar 了;本次要传 `sswhl-update.tar.gz`(1.7 MB) |
| `! 检测到 requirements-linux.txt 有变化!` | **虚警**:服务器上原是 11-13 旧文本(没有 `exceptiongroup` 那行),包里是新版,`cmp` 不同就报警;但镜像 11-15 00:33 已按新清单重建,且容器能启动就说明所有新路由都 import 成功(缺依赖会直接崩)。`--pkg` 已同步新文本,下次不再报。自查:`sudo docker exec sswhl-api /usr/local/bin/python3.10 -c "import openpyxl,xlrd,exceptiongroup;print('deps ok')"` |
| 页面还是旧版 | 浏览器缓存,`Ctrl+F5` 强刷 |

---

## 十三、加班人员表 / 部门树数据补齐(2026-11-15 第二次发版)

### 13.1 为什么要再传一次数据库

加班申请审批模块的**功能**早就复刻好了(配置管理 → 人员管理 / 部门管理抽屉),
但 12 张 `overtime_*` 表的数据一直没迁:新库里人员 0 行、部门只有 3 个初始化节点,
其余申请单/明细/时段全空。14:4x 在开发机补跑了 `scripts/import_overtime.py`,
把旧库全量导进来:

| 表 | 旧库 → 新库 | 说明 |
|---|---|---|
| `overtime_personnel` | 559 | **人员表**(在职 556,绑定系统账号 137) |
| `overtime_dept` | 47 | **加班部门树**(根=售水事业部,4 级,`sys_bumen_id` 已映射到新 `departments.id`) |
| `overtime_apply` / `detail` / `time_entry` | 186 / 1465 / 7570 | 历史申请单与时段明细 |
| `overtime_month_config` / `user` / `record` / `comp_leave` | 3 / 19 / 51 / 2 | 月份规则、旧账号白名单、遗留记录、补休 |
| `overtime_approval_level` / `approver` / `apply_approval` | 0 / 0 / 0 | 旧库本身为空 |

校验:12 表行数 + 7 列金额/时长 SUM 逐列对齐,9 组 id 引用 0 悬空,
`smoke_overtime` **50/50 通过**(含 dicts / 人员 / 部门树 / 申请单 / 汇总等只读接口)。

服务器 14:29 导入的是补齐**之前**的快照,所以加班表仍是空的。
**代码与前端一个字没改**(`app/` 未动),所以**不用重传代码包、不用重传镜像**,只补数据库。

### 13.2 只传 1 个文件

仓库根目录已备好改名副本 `sswhl_ot_118.sql.gz`(与 `deploy/import/sswhl_new.sql.gz`
同一文件),用堡垒机文件传输选它,传到 `~` 后:

```bash
cd ~ && md5sum sswhl_ot_118.sql.gz                                # f96661b2900363a7942048ceb03e90c6
gzip -dc sswhl_ot_118.sql.gz | grep -c '^DROP TABLE IF EXISTS'     # 118
```

> ⚠️ 别再把旧名 `sswhl_new.sql.gz` 传上去覆盖(见 12.2 的同名坑)。
> 也不能用 22.3 MB / `94a82f07...` 那份旧 dump——它不含加班数据。

### 13.3 推荐:只覆盖 12 张加班表(服务器上其它数据一字不动)

```bash
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_ot_118.sql.gz --tables overtime_dept,overtime_personnel,overtime_approval_level,overtime_approver,overtime_month_config,overtime_apply,overtime_apply_detail,overtime_time_entry,overtime_apply_approval,overtime_comp_leave,overtime_record,overtime_user
```

脚本会自动备份数据库、逐表 DROP + 重建 + 导入、末尾重启 API。
12 张表的 SQL 段落已在新 dump 上逐张实测可正确抽取(每张 1 条 CREATE,空表也有 UNLOCK)。
传导 4 表、用户/角色/权限、工单等**完全不受影响**。

若服务器上还没人录数据、想省事,也可以走全量重导(会覆盖全部 118 表):

```bash
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_ot_118.sql.gz --yes
```

### 13.4 验收

```bash
sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>' --table -e "
SELECT '人员' t,COUNT(*) n FROM sswhl_new.overtime_personnel UNION ALL
SELECT '部门',COUNT(*) FROM sswhl_new.overtime_dept UNION ALL
SELECT '申请单',COUNT(*) FROM sswhl_new.overtime_apply UNION ALL
SELECT '明细',COUNT(*) FROM sswhl_new.overtime_apply_detail UNION ALL
SELECT '时段',COUNT(*) FROM sswhl_new.overtime_time_entry;"
# 期望 559 / 47 / 186 / 1465 / 7570
```

浏览器 `Ctrl+F5` → 加班申请 → **配置管理 → 人员管理**应能搜到 559 人(默认只显示 556 在职),
**部门管理**抽屉应展开 47 个节点的部门树;切到历史月份能看到旧申请单。
注意:人员里只有 137 人绑定了系统账号(旧库如此),没绑定的人不会出现在「我的加班」自动匹配里,
这不是迁移丢失。

---

## 十四、用户账号 id 1:1 重建（16:30，含全量重导）⚠️ 本次上线以本节为准

> **12.2 / 13.2 两张 MD5 表已过期**，别再按它们的文件名和校验值传。
> 本节产物是 16:30 之后重新导出的，数据库里的用户 id 全部变了。

### 14.1 为什么必须重导数据库

旧库 `bb_user` 199 个账号的 id 是 3~382 的跳号 IDENTITY。初次迁移时新库已有
`id=1 admin`、`id=7 林春`，产生 `3→7 / 7→383 / 207→1` 三个特例。但下面这些表
**直接搬旧 id、没走 `user_map` 映射**，而 `plan_common.resolve_user_id()` 在新增/编辑时
写入的是当时的新 `users.id`，两套口径不一致：

| 表.列 | 重建前悬空行数 |
|---|---|
| `sms_contact.id` | 2 |
| `gx_user_gxgz.userid` | 548 |
| `jh_ssdb.zhuanguan` | 457 |
| `jh_ssdbpz.zhuanguan` | 10952 |
| `jh_yyfq.zgy` | 334 |
| `jh_yyfq.opid` | 1 |

合计 **12294 行**关联不上；另有 `ht_add.djuser`(74 行)、`wzcgsq.userid`(1 行)
姓名快照写着「林春」、id 却指向陈毅清这类**语义错位 75 行**（只查悬空发现不了）。

`scripts/rebuild_user_ids.py` 已把 `users.id` 重编号为旧 id 的 **1:1 恒等**：
`1→207`、`7→3`、`383→7`，删掉免改密的测试超管 `id=21 guitest`，
并把 12 个「存新 id」的引用列**两段式**重映射（`user_role` / `user_department` /
加班 8 列 / `ht_add.djuser` / `wzcgsq.userid` / `jc_printcolum.userid`）。
`user_map.json` 随之改为恒等映射，`import_users.py` 以后重跑只做 UPDATE、不会再分配 id。

**验收**：账号 199/199、id 集合与用户名逐条和旧库一致；所有引用列 0 悬空、
姓名快照 0 错位；仅 `jh_yyfq.opid` 残留 1 行（旧库本身已删账号的历史脏值）。
全套 17 个冒烟脚本通过（另修了 `smoke_chelfytj` 跑完不自清临时账号的 bug）。

### 14.2 本次产物

| 文件 | 大小 | MD5 |
|---|---|---|
| `E:\pysswhl\sswhl_uid_118.sql.gz`（上传副本，改名避免同名不覆盖） | 22.5 MB | `1a8de46448c16437518f6a9e8946c097` |
| `E:\pysswhl\sswhl-update.tar.gz`（精简代码包） | 4.4 MB | `bc44b81acfd40cd1092c4570648aa8f3` |

`deploy/import/sswhl_new.sql.gz` 与上传副本是同一个文件（MD5 相同）。
**不用重传 71 MB 镜像、不用动 `.env`、不用重新 build 前端**（`app/` 与 `dist` 一字未改）。

### 14.3 服务器步骤（必须全量重导）

⚠️ **不能再用 `--tables` 单表覆盖**：id 变化涉及 `users` + `user_role` +
`user_department` + 多个历史表的 `userid` 列，只覆盖部分表会留下半新半旧的引用。

```bash
cd ~
md5sum sswhl_uid_118.sql.gz                                    # 1a8de46448c16437518f6a9e8946c097
gzip -dc sswhl_uid_118.sql.gz | grep -c '^DROP TABLE IF EXISTS'   # 118
gzip -dc sswhl_uid_118.sql.gz | grep -m1 'CREATE TABLE `cd_whl`'  # 要有输出

# 推荐：先同步脚本与恒等映射文件（否则服务器上 user_map.json 仍是旧口径）
sudo bash /opt/sswhl/deploy/update.sh --pkg ~/sswhl-update.tar.gz --backup-db

# 全量重导（自动先备份到 /opt/sswhl-backup/，末尾补表结构 + 重启）
sudo bash /opt/sswhl/deploy/update.sh --db ~/sswhl_uid_118.sql.gz --yes
```

全量重导会 DROP 重建 118 张表，**服务器上 11-14 之后新录入的数据会全部丢失**
（试装阶段通常没有）。第 2 条若省略，功能不受影响，只是服务器上脚本口径落后。

### 14.4 验收

```bash
sudo bash /opt/sswhl/deploy/update.sh --status       # 表数=118、用户数=199
sudo docker exec -i sswhl-mysql mysql -uroot -p'<root密码>' --table -e "
SELECT id,username,real_name,is_superuser FROM sswhl_new.users WHERE id IN (3,7,207) ORDER BY id;
SELECT COUNT(*) AS smoke FROM sswhl_new.users WHERE username LIKE 'smoke%' OR username='guitest';"
# 期望:3 林春 / 7 陈毅清 / 207 admin(唯一超管);smoke=0
```

浏览器 `Ctrl+F5` 强刷后重新登录，左侧「传导完好率」分组、加班配置页人员/部门树
都应与开发机一致。

### 14.5 两个必须知道的影响

1. **所有已登录用户会被踢下线**：JWT 的 `sub` 存的是用户 id，`admin` 从 1 变 207、
   另两人也变了，旧 token 查不到用户直接 401。**重新登录即可**，密码没变
   （`PASSWORD_PEPPER` 保持不变）。
2. **别在服务器上跑旧的 `import_users.py` / `import_overtime.py`**：精简包已把口径改成恒等，
   若跳过 `--pkg` 且以后有人重跑旧脚本，会把 id 又改回去。`make_release.py` 现在
   导出 dump 前会检查 `smoke*` / `guitest` 测试账号，有残留直接中止发版。
