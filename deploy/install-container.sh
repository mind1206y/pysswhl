#!/usr/bin/env bash
# =============================================================================
# 售水业务管理系统(sswhl) 纯容器部署 —— 只依赖宿主机 Docker
#
# 与 install.sh 的区别:不需要宿主机 Python / venv / systemd,
# 依赖与代码全在镜像 sswhl-api:1.0 里(自带 Python 3.10 + 37 个离线包 + 前端 dist)。
#
# 用法:
#   sudo bash install-container.sh                                                  # 空库
#   sudo bash install-container.sh --dump /home/sysmgr/sswhl_new.sql.gz             # 带数据
#   sudo bash install-container.sh --skip-db                                        # 只重建并重启 API 容器
#   sudo bash install-container.sh --only-account                                   # 只重建库账号+跑 init_db+重启(修 1045)
#
# 前置:
#   1) 项目已解压到 /opt/sswhl
#   2) 已导入镜像: sudo docker load -i sswhl-api-image.tar
#   3) 本机有 mysql:8 镜像(系统盘已有)
# =============================================================================

if [ -z "${_CRLF_FIXED:-}" ] && grep -q $'\r' "$0" 2>/dev/null; then
  sed -i 's/\r$//' "$0"
  _CRLF_FIXED=1 exec bash "$0" "$@"
fi

set -euo pipefail

APP_DIR="/opt/sswhl"
COMPOSE_FILE="$APP_DIR/deploy/docker-compose.yml"
COMPOSE_ENV="$APP_DIR/deploy/.env"
BE_ENV="$APP_DIR/backend/.env"
API_IMAGE="sswhl-api:1.0"
API_PORT="18080"
DB_CONTAINER="sswhl-mysql"
DB_NAME="sswhl_new"
DB_APP_USER="sswhl_app"
DUMP_FILE=""
SKIP_DB=0
ONLY_ACCOUNT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump)         DUMP_FILE="${2:-}"; shift 2 ;;
    --port)         API_PORT="${2:-18080}"; shift 2 ;;
    --skip-db)      SKIP_DB=1; shift ;;
    --only-account) ONLY_ACCOUNT=1; shift ;;
    -h|--help)      sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数:$1(用 --help 查看用法)"; exit 1 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
log()  { echo "  ${c_grn}✔${c_off} $*"; }
warn() { echo "  ${c_ylw}!${c_off} $*"; }
step() { echo; echo "${c_ylw}==> $*${c_off}"; }
die()  { echo; echo "${c_red}✘ $*${c_off}" >&2; exit 1; }

set_env() {
  local k="$1" v="$2" f="$3"
  if grep -qE "^${k}=" "$f" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$f"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}
# 读 .env 的值。必须去掉行尾的 \r:Windows 生成的 .env 是 CRLF,Linux 的 grep/cut
# 会把 \r 一起带出来 -> 建号时密码比实际多一个回车 -> 容器内连库报 1045 Access denied。
get_env() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true; }

# 把 CRLF 的 .env 统一转成 LF(幂等,只处理带 \r 的文件)
normalize_env() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  if grep -q $'\r' "$f" 2>/dev/null; then
    sed -i 's/\r$//' "$f"
    warn "$(basename "$f") 原为 CRLF 换行,已转为 LF"
  fi
}

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }

# ---------------------------------------------------------------- 0 前置检查
step "0/6 环境检查(只要求 Docker)"
[[ $EUID -eq 0 ]] || die "请用 sudo 运行:sudo bash $0"
[[ -d "$APP_DIR/backend/app" ]] || die "找不到 $APP_DIR/backend/app,请先解压部署包到 $APP_DIR"
[[ -f "$COMPOSE_FILE" ]] || die "找不到 compose 文件:$COMPOSE_FILE"
command -v docker >/dev/null 2>&1 || die "docker 未安装"
docker compose version >/dev/null 2>&1 || die "docker compose 插件不可用(需要 v2)"
docker image inspect "$API_IMAGE" >/dev/null 2>&1 \
  || die "缺少镜像 $API_IMAGE,请先执行:sudo docker load -i sswhl-api-image.tar"
docker image inspect mysql:8 >/dev/null 2>&1 \
  || die "缺少 mysql:8 镜像。可执行:sudo docker pull mysql:8(或从别的机器 docker save 后导入)"
[[ -f "$BE_ENV" ]] || die "缺少 $BE_ENV(部署包内自带,含 PASSWORD_PEPPER,不要重建它)"
log "系统 $(. /etc/os-release; echo "$PRETTY_NAME") / Docker $(docker version --format '{{.Server.Version}}')"
log "镜像 $API_IMAGE 已就绪"
warn "不需要宿主机 Python:依赖与代码都在镜像内"

# ---------------------------------------------------------------- 1 数据库容器
if [[ $SKIP_DB -eq 0 ]]; then
  step "1/6 启动数据库容器(只监听 127.0.0.1:13306)"
  if [[ ! -f "$COMPOSE_ENV" ]]; then
    umask 077
    printf 'MYSQL_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" > "$COMPOSE_ENV"
    chmod 600 "$COMPOSE_ENV"
    log "已生成 deploy/.env(MySQL root 随机密码)"
  else
    log "已有 deploy/.env,沿用原 root 密码"
  fi
  MYSQL_ROOT_PASSWORD="$(get_env MYSQL_ROOT_PASSWORD "$COMPOSE_ENV")"
  [[ -n "$MYSQL_ROOT_PASSWORD" ]] || die "deploy/.env 里 MYSQL_ROOT_PASSWORD 为空"

  dc up -d mysql
  printf '  等待 MySQL 就绪'
  db_ok=0
  for _ in $(seq 1 60); do
    if docker exec "$DB_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "select 1" >/dev/null 2>&1; then
      db_ok=1; break
    fi
    printf '.'; sleep 2
  done
  echo
  [[ $db_ok -eq 1 ]] || die "MySQL 120 秒内未就绪。排查:docker logs $DB_CONTAINER --tail 50"
  log "MySQL 已就绪"
else
  step "1/6 跳过数据库(--skip-db)"
  MYSQL_ROOT_PASSWORD="$(get_env MYSQL_ROOT_PASSWORD "$COMPOSE_ENV")"
  [[ -n "$MYSQL_ROOT_PASSWORD" ]] || die "$COMPOSE_ENV 里没有 MYSQL_ROOT_PASSWORD,无法校正应用账号"
fi

# ---------------------------------------------------------------- 2 应用配置
step "2/6 校准 backend/.env(不改 PEPPER 与密钥)"
# Windows 上编辑过的 .env 是 CRLF,必须先归一化,否则 shell 取到的密码尾部带不可见 \r
normalize_env "$BE_ENV"
normalize_env "$COMPOSE_ENV"
# 容器内连库走服务名,宿主路径一律指向容器内路径;这些值同时由 compose environment 再覆盖一次
set_env DB_HOST mysql "$BE_ENV"
set_env DB_PORT 3306 "$BE_ENV"
set_env DB_USER "$DB_APP_USER" "$BE_ENV"
set_env DB_NAME "$DB_NAME" "$BE_ENV"
set_env SERVE_FRONTEND true "$BE_ENV"
set_env ENABLE_DOCS false "$BE_ENV"
set_env UPLOAD_DIR /app/backend/uploads "$BE_ENV"
set_env FRONTEND_DIST /app/frontend/dist "$BE_ENV"
if [[ -z "$(get_env DB_PASSWORD "$BE_ENV")" ]]; then
  set_env DB_PASSWORD "$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')" "$BE_ENV"
  log "原 .env 无 DB_PASSWORD,已生成"
fi
DB_PASS="$(get_env DB_PASSWORD "$BE_ENV")"

# 容器按镜像 config 里的 User 运行(手工组装的镜像是 root;用 Dockerfile.api 重建时是 sswhl/10001)。
# .env 与私钥是只读挂载进容器的,属主必须让该用户可读,否则容器启动即报 Permission denied。
# 这里用镜像自己跑一次 id 拿到真实 uid:gid 再 chown,两种镜像都适用。
RUN_UIDGID="$(docker run --rm --entrypoint sh "$API_IMAGE" -c 'echo "$(id -u):$(id -g)"' 2>/dev/null | tr -d '\r\n' || true)"
[[ -n "$RUN_UIDGID" ]] || RUN_UIDGID="0:0"
chown "$RUN_UIDGID" "$BE_ENV" 2>/dev/null || true
if [[ -f "$APP_DIR/backend/rsa_key.pem" ]]; then
  chown "$RUN_UIDGID" "$APP_DIR/backend/rsa_key.pem" 2>/dev/null || true
fi
chmod 600 "$BE_ENV"
[[ -f "$APP_DIR/backend/rsa_key.pem" ]] && chmod 600 "$APP_DIR/backend/rsa_key.pem" || true
log "配置已对齐容器内路径(库 $DB_NAME / 账号 $DB_APP_USER)"
log "文件属主已对齐容器运行用户 $RUN_UIDGID"

# ---------------------------------------------------------------- 3 建库建号
# 幂等,每次都执行:--skip-db / --only-account 时也要把账号密码校正过来
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$DB_CONTAINER"; then
  step "3/6 创建数据库与应用账号(幂等)"
  docker exec -i "$DB_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL || die "建库/授权失败"
CREATE DATABASE IF NOT EXISTS $DB_NAME DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '$DB_APP_USER'@'%' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_APP_USER'@'%' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_APP_USER'@'%';
FLUSH PRIVILEGES;
SQL
  # 用刚设好的账号回连一次:密码若对不上,这里立刻暴露,不必等 init_db 才报 1045
  if ! docker exec -i "$DB_CONTAINER" mysql -u"$DB_APP_USER" -p"$DB_PASS" -e "select 1" "$DB_NAME" >/dev/null 2>&1; then
    die "应用账号 $DB_APP_USER 建好后仍无法登录。请确认 $BE_ENV 的 DB_PASSWORD 只含字母数字(无空格/引号/\$)"
  fi
  log "库与账号就绪(应用账号自检通过)"
else
  warn "数据库容器 $DB_CONTAINER 未运行,跳过建号"
fi

# ---------------------------------------------------------------- 4 导入数据
step "4/6 导入数据 / 初始化表结构"
if [[ $ONLY_ACCOUNT -eq 1 ]]; then
  warn "跳过数据导入(--only-account)"
elif [[ -n "$DUMP_FILE" ]]; then
  [[ -f "$DUMP_FILE" ]] || die "找不到 SQL 文件:$DUMP_FILE"
  case "$DUMP_FILE" in
    *.gz)
      log "导入 $DUMP_FILE(gzip,含 DROP TABLE)"
      gunzip -c "$DUMP_FILE" | docker exec -i "$DB_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --default-character-set=utf8mb4 \
        || die "导入失败。常见原因:dump 库名不是 $DB_NAME,或导出端 MySQL 版本语法在 8.0 上不兼容"
      ;;
    *)
      log "导入 $DUMP_FILE"
      docker exec -i "$DB_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --default-character-set=utf8mb4 < "$DUMP_FILE" \
        || die "导入失败,见上方报错"
      ;;
  esac
  log "数据导入完成"
else
  warn "未指定 --dump,按空库初始化"
fi

# init_db 在镜像内执行,不需要宿主机 Python
log "在容器内执行 scripts.init_db(幂等)"
dc --profile docker-api run --rm --no-deps api python -m scripts.init_db \
  || die "init_db 执行失败,见上方报错"
log "表结构与权限码就绪"

# ---------------------------------------------------------------- 5 启动服务
step "5/6 启动 API 容器(对外 $API_PORT)"
if systemctl is-active --quiet sswhl-api 2>/dev/null; then
  systemctl disable --now sswhl-api >/dev/null 2>&1 || true
  warn "检测到宿主机 systemd 服务 sswhl-api,已停止(避免端口冲突)"
fi
if ss -lntp 2>/dev/null | grep -qE ":${API_PORT}[[:space:]]"; then
  die "端口 $API_PORT 已被占用:
$(ss -lntp | grep -E ":${API_PORT}[[:space:]]")"
fi
dc --profile docker-api up -d
printf '  等待服务就绪'
svc_ok=0
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then
    svc_ok=1; break
  fi
  printf '.'; sleep 2
done
echo
if [[ $svc_ok -ne 1 ]]; then
  echo "---- 容器状态 ----"
  docker ps -a --filter "name=sswhl" --format "table {{.Names}}\t{{.Status}}"
  echo "---- API 日志(最近 40 行)----"
  docker logs sswhl-api --tail 40 2>&1 || true
  die "服务未通过健康检查,日志见上"
fi
log "服务已启动并通过健康检查"

# ---------------------------------------------------------------- 6 收尾
step "6/6 完成"
HOST_IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

  访问地址 : ${c_grn}http://$HOST_IP:$API_PORT${c_off}
  健康检查 : curl http://127.0.0.1:$API_PORT/api/health

  运行形态(全部在容器里,宿主只提供 Docker)
    数据库 : 容器 $DB_CONTAINER(127.0.0.1:13306 / 库 $DB_NAME / 账号 $DB_APP_USER)
    API    : 容器 sswhl-api(镜像 $API_IMAGE,自带 Python 3.10 与依赖)
    前端   : 由 API 进程直接托管,无独立容器
    附件   : 卷 sswhl_uploads ↔ /app/backend/uploads

  常用命令
    看状态 : sudo docker compose -f $COMPOSE_FILE --profile docker-api ps
    看日志 : sudo docker logs -f sswhl-api
    重启   : sudo docker compose -f $COMPOSE_FILE --profile docker-api restart api
    全停   : sudo docker compose -f $COMPOSE_FILE --profile docker-api down
    进容器 : sudo docker exec -it sswhl-api bash
    配置文件 : $BE_ENV(权限 600,含 PASSWORD_PEPPER,勿外传)

EOF
