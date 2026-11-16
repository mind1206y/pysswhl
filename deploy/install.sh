#!/usr/bin/env bash
# =============================================================================
# 售水业务管理系统(sswhl)一键部署脚本
#   目标环境:Ubuntu 22.04 / 系统自带 Python 3.10 / Docker(本机已有 mysql:8 镜像)/ systemd
#   用法:
#     sudo bash /opt/sswhl/deploy/install.sh                 # 首次部署(空库)
#     sudo bash /opt/sswhl/deploy/install.sh --dump /opt/sswhl/import/sswhl_new.sql
#     sudo bash /opt/sswhl/deploy/install.sh --skip-db       # 只更新代码+依赖并重启
#   脚本可重复执行:已有的 .env、数据卷、venv、账号都会保留,不会清数据。
# =============================================================================

# Windows 上编辑过会变成 CRLF,先自愈再继续(否则 bash 会报 pipefail\r 无效)
if [ -z "${_CRLF_FIXED:-}" ] && grep -q $'\r' "$0" 2>/dev/null; then
  sed -i 's/\r$//' "$0"
  _CRLF_FIXED=1 exec bash "$0" "$@"
fi

set -euo pipefail

APP_DIR="/opt/sswhl"
APP_USER="sswhl"
DB_NAME="sswhl_new"
DB_APP_USER="sswhl_app"
DB_HOST_PORT="13306"
API_PORT="18080"
DUMP_FILE=""
SKIP_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump)    DUMP_FILE="${2:-}"; shift 2 ;;
    --port)    API_PORT="${2:-18080}"; shift 2 ;;
    --skip-db) SKIP_DB=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数:$1(用 --help 查看用法)"; exit 1 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
log()  { echo "  ${c_grn}✔${c_off} $*"; }
warn() { echo "  ${c_ylw}!${c_off} $*"; }
step() { echo; echo "${c_ylw}==> $*${c_off}"; }
die()  { echo; echo "${c_red}✘ $*${c_off}" >&2; exit 1; }

# 修改/追加 KEY=VALUE(sed 用 | 作分隔符,密码统一用 hex 避免特殊字符)
set_env() {
  local k="$1" v="$2" f="$3"
  if grep -qE "^${k}=" "$f" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$f"
  else
    printf '%s=%s\n' "$k" "$v" >> "$f"
  fi
}
get_env() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- || true; }

# ---------------------------------------------------------------- 0 前置检查
step "0/7 环境检查"
[[ $EUID -eq 0 ]] || die "请用 sudo 运行:sudo bash $0"
[[ -d "$APP_DIR/backend/app" ]] || die "找不到 $APP_DIR/backend/app,请确认项目已上传到 $APP_DIR"
command -v docker >/dev/null 2>&1 || die "docker 未安装"
docker compose version >/dev/null 2>&1 || die "docker compose 插件不可用(需要 v2)"
docker image inspect mysql:8 >/dev/null 2>&1 || die "本机没有 mysql:8 镜像,请先 docker pull mysql:8"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || die "Python 需要 3.10+,当前 $(python3 -V 2>&1)"
[[ -d "$APP_DIR/deploy/wheels" ]] || die "缺少离线依赖目录 $APP_DIR/deploy/wheels"
[[ -f "$APP_DIR/frontend/dist/index.html" ]] || die "缺少前端构建产物 $APP_DIR/frontend/dist/index.html"
command -v openssl >/dev/null 2>&1 || die "缺少 openssl(生成随机密钥用)"
HOST_IP="$(hostname -I | awk '{print $1}')"
log "系统 $(. /etc/os-release; echo "$PRETTY_NAME") / Python $(python3 -V 2>&1 | awk '{print $2}') / 本机 IP $HOST_IP"

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  log "已创建系统用户 $APP_USER"
else
  log "系统用户 $APP_USER 已存在"
fi

# ---------------------------------------------------------------- 1 数据库容器
if [[ $SKIP_DB -eq 0 ]]; then
  step "1/7 启动 MySQL 容器(sswhl-mysql,只监听 127.0.0.1:$DB_HOST_PORT)"
  COMPOSE_ENV="$APP_DIR/deploy/.env"
  if [[ ! -f "$COMPOSE_ENV" ]]; then
    umask 077
    printf 'MYSQL_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 16)" > "$COMPOSE_ENV"
    chmod 600 "$COMPOSE_ENV"
    log "已生成 deploy/.env(MySQL root 随机密码)"
  else
    log "已有 deploy/.env,沿用原 root 密码"
  fi
  MYSQL_ROOT_PASSWORD="$(get_env MYSQL_ROOT_PASSWORD "$COMPOSE_ENV")"
  [[ -n "$MYSQL_ROOT_PASSWORD" ]] || die "deploy/.env 里 MYSQL_ROOT_PASSWORD 为空"

  docker compose -f "$APP_DIR/deploy/docker-compose.yml" up -d
  printf '  等待 MySQL 就绪'
  db_ok=0
  for _ in $(seq 1 60); do
    if docker exec sswhl-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "select 1" >/dev/null 2>&1; then
      db_ok=1; break
    fi
    printf '.'; sleep 2
  done
  echo
  [[ $db_ok -eq 1 ]] || die "MySQL 120 秒内未就绪。排查:docker logs sswhl-mysql --tail 50"
  log "MySQL 已就绪(容器 sswhl-mysql,宿主端口 $DB_HOST_PORT)"
else
  step "1/7 跳过数据库(--skip-db)"
  COMPOSE_ENV="$APP_DIR/deploy/.env"
  MYSQL_ROOT_PASSWORD="$(get_env MYSQL_ROOT_PASSWORD "$COMPOSE_ENV")"
fi

# ---------------------------------------------------------------- 2 后端配置
step "2/7 准备 backend/.env"
BE_ENV="$APP_DIR/backend/.env"
if [[ ! -f "$BE_ENV" ]]; then
  cp "$APP_DIR/deploy/env.production.example" "$BE_ENV"
  set_env SECRET_KEY "$(openssl rand -hex 32)" "$BE_ENV"
  set_env PASSWORD_PEPPER "$(openssl rand -hex 32)" "$BE_ENV"
  set_env DB_PASSWORD "$(openssl rand -hex 16)" "$BE_ENV"
  log "已按模板新建 .env(SECRET_KEY / PASSWORD_PEPPER / DB_PASSWORD 均为本机新随机串)"
else
  log "检测到已有 .env:保留 SECRET_KEY 与 PASSWORD_PEPPER(导入现网数据时必须与开发机一致)"
  if [[ "$(get_env DB_USER "$BE_ENV")" != "$DB_APP_USER" ]]; then
    set_env DB_PASSWORD "$(openssl rand -hex 16)" "$BE_ENV"
    log "原 DB_USER 不是 $DB_APP_USER,已为应用账号生成新密码"
  fi
  [[ -n "$(get_env DB_PASSWORD "$BE_ENV")" ]] || set_env DB_PASSWORD "$(openssl rand -hex 16)" "$BE_ENV"
fi

# 每次部署都校准的固定项
set_env DB_HOST 127.0.0.1 "$BE_ENV"
set_env DB_PORT "$DB_HOST_PORT" "$BE_ENV"
set_env DB_USER "$DB_APP_USER" "$BE_ENV"
set_env DB_NAME "$DB_NAME" "$BE_ENV"
set_env SERVE_FRONTEND true "$BE_ENV"
set_env ENABLE_DOCS false "$BE_ENV"
set_env CORS_ORIGINS "http://$HOST_IP:$API_PORT" "$BE_ENV"
set_env UPLOAD_DIR "$APP_DIR/backend/uploads" "$BE_ENV"
DB_PASS="$(get_env DB_PASSWORD "$BE_ENV")"
[[ -n "$DB_PASS" ]] || die "backend/.env 里 DB_PASSWORD 为空"
mkdir -p "$APP_DIR/backend/uploads"
log "数据库指向 127.0.0.1:$DB_HOST_PORT / 库 $DB_NAME / 账号 $DB_APP_USER"
warn "对外端口 $API_PORT,前端由后端直接托管(SERVE_FRONTEND=true),接口文档已关闭"

# ---------------------------------------------------------------- 3 建库建号
if [[ $SKIP_DB -eq 0 ]]; then
  step "3/7 创建数据库与应用账号"
  docker exec -i sswhl-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL || die "建库/授权失败"
CREATE DATABASE IF NOT EXISTS $DB_NAME DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '$DB_APP_USER'@'%' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_APP_USER'@'%' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_APP_USER'@'%';
GRANT CREATE ON *.* TO '$DB_APP_USER'@'%';
FLUSH PRIVILEGES;
SQL
  log "库 $DB_NAME 与账号 $DB_APP_USER 就绪(仅本机 3306 内网段可见)"
fi

# ---------------------------------------------------------------- 4 依赖
step "4/7 安装 Python 依赖(离线 wheels,不联网)"
VENV="$APP_DIR/backend/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$VENV" \
    || die "创建 venv 失败。请先执行:sudo apt-get install -y python3.10-venv"
  log "已创建 venv"
fi
if [[ ! -x "$VENV/bin/pip" ]]; then
  sudo -u "$APP_USER" "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 \
    || die "venv 内没有 pip。请执行:sudo apt-get install -y python3.10-venv 后重跑"
fi
sudo -u "$APP_USER" "$VENV/bin/pip" install --no-index \
  --find-links="$APP_DIR/deploy/wheels" \
  -r "$APP_DIR/backend/requirements-linux.txt" -q \
  || die "离线安装依赖失败,检查 deploy/wheels 是否完整"
log "依赖安装完成($(ls "$APP_DIR/deploy/wheels" | wc -l) 个 wheel)"

# ---------------------------------------------------------------- 5 数据
step "5/7 初始化数据库结构 / 导入数据"
if [[ -n "$DUMP_FILE" ]]; then
  [[ -f "$DUMP_FILE" ]] || die "找不到 SQL 文件:$DUMP_FILE"
  [[ -n "$MYSQL_ROOT_PASSWORD" ]] || die "缺少 deploy/.env 里的 MYSQL_ROOT_PASSWORD,无法导入"
  case "$DUMP_FILE" in
    *.gz)
      log "导入 $DUMP_FILE(gzip,边解压边导入,含 DROP TABLE)"
      gunzip -c "$DUMP_FILE" | docker exec -i sswhl-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --default-character-set=utf8mb4 \
        || die "导入失败。常见原因:dump 里写的库名不是 $DB_NAME,或导出端 MySQL 版本语法在 8.0 上不兼容"
      ;;
    *)
      log "导入 $DUMP_FILE(含 DROP TABLE,会覆盖同名表)"
      docker exec -i sswhl-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
        --default-character-set=utf8mb4 < "$DUMP_FILE" \
        || die "导入失败。常见原因:dump 里写的库名不是 $DB_NAME,或导出端 MySQL 版本语法在 8.0 上不兼容"
      ;;
  esac
  log "数据导入完成"
else
  warn "未指定 --dump,按空库初始化(上线后需要录入或另行导入数据)"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend" "$APP_DIR/frontend/dist"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR/backend' && '$VENV/bin/python' -m scripts.init_db" \
  || die "init_db 执行失败,见上方报错"
log "表结构与基础数据已就绪(脚本幂等,可重复执行)"

# ---------------------------------------------------------------- 6 服务
step "6/7 安装并启动 systemd 服务(sswhl-api)"
install -m 0644 "$APP_DIR/deploy/sswhl-api.service" /etc/systemd/system/sswhl-api.service
sed -i "s|--port 18080|--port $API_PORT|" /etc/systemd/system/sswhl-api.service
chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend"
chmod 600 "$BE_ENV" 2>/dev/null || true
[[ -f "$APP_DIR/backend/rsa_key.pem" ]] && chmod 600 "$APP_DIR/backend/rsa_key.pem" || true
systemctl daemon-reload
systemctl enable sswhl-api >/dev/null 2>&1
systemctl restart sswhl-api
printf '  等待服务就绪'
svc_ok=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
    svc_ok=1; break
  fi
  printf '.'; sleep 2
done
echo
if [[ $svc_ok -ne 1 ]]; then
  echo "---- systemctl status ----"
  systemctl status sswhl-api --no-pager -l | tail -15 || true
  echo "---- journalctl(最近 40 行)----"
  journalctl -u sswhl-api -n 40 --no-pager || true
  die "服务未通过健康检查,日志见上"
fi
log "服务已启动并通过健康检查"

# ---------------------------------------------------------------- 7 收尾
step "7/7 完成"
TILE_DIR="$APP_DIR/backend/assets/tiles"
if [[ ! -d "$TILE_DIR" ]] || [[ -z "$(ls -A "$TILE_DIR" 2>/dev/null)" ]]; then
  warn "热力图底图瓦片未部署($TILE_DIR 为空),测漏热力图会提示'底图为空';"
  warn "需要时把 tiles 目录上传到 $APP_DIR/tiles 后执行:"
  warn "  cd $APP_DIR/backend && $VENV/bin/python -m scripts.prepare_heatmap_tiles --source $APP_DIR/tiles --copy"
fi
cat <<EOF

  访问地址 : ${c_grn}http://$HOST_IP:$API_PORT${c_off}
  健康检查 : curl http://127.0.0.1:$API_PORT/api/health
  数据库   : 127.0.0.1:$DB_HOST_PORT(容器 sswhl-mysql / 库 $DB_NAME / 账号 $DB_APP_USER)

  常用命令
    查看状态 : sudo systemctl status sswhl-api
    实时日志 : sudo journalctl -u sswhl-api -f
    重启服务 : sudo systemctl restart sswhl-api
    停止服务 : sudo systemctl stop sswhl-api
    数据库   : sudo docker compose -f $APP_DIR/deploy/docker-compose.yml ps
    备份库   : sudo docker exec sswhl-mysql mysqldump -uroot -p'<root密码>' --single-transaction --default-character-set=utf8mb4 $DB_NAME > /opt/sswhl-backup/\$(date +%F).sql
    配置文件 : $BE_ENV(权限 600,含 PASSWORD_PEPPER,勿外传)

EOF
