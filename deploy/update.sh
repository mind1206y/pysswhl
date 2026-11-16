#!/usr/bin/env bash
# =============================================================================
# 售水业务管理系统(sswhl) 日常更新脚本 —— 纯容器形态
#
# 五种场景,各一条命令:
#   sudo bash update.sh --status                                   # 看当前版本/备份/容器
#   sudo bash update.sh --pkg ~/sswhl-deploy.tar.gz                # ① 更新程序(改代码/前端)
#   sudo bash update.sh --pkg ~/sswhl-deploy.tar.gz --schema        # ② 更新程序 + 补表结构
#   sudo bash update.sh --db  ~/sswhl_new.sql.gz --tables a,b       # ③ 只覆盖指定表(补数据)
#   sudo bash update.sh --db  ~/sswhl_new.sql.gz --yes              # ④ 全量覆盖(危险,删表重建)
#   sudo bash update.sh --image ~/sswhl-api-image.tar               # ⑤ 更新依赖(requirements 变了)
#   sudo bash update.sh --rollback                                  # 回滚到上一版代码
#
# 设计要点:
#   * 代码是宿主目录只读挂载进容器的,所以①只覆盖文件 + 重启,不重建 71MB 镜像
#   * 每次更新前自动备份:数据库(仅①时可选)、代码目录。默认保留最近 10 份
#   * 备份目录 /opt/sswhl-backup,回滚与救急都从这里取
#   * 不动 backend/.env(.env 里的 PASSWORD_PEPPER 一旦变了,所有人都登不上)
#   * 不动 uploads、rsa_key.pem
# =============================================================================

if [ -z "${_CRLF_FIXED:-}" ] && grep -q $'\r' "$0" 2>/dev/null; then
  sed -i 's/\r$//' "$0"
  _CRLF_FIXED=1 exec bash "$0" "$@"
fi

set -euo pipefail

APP_DIR="/opt/sswhl"
BACKUP_DIR="/opt/sswhl-backup"
COMPOSE_FILE="$APP_DIR/deploy/docker-compose.yml"
COMPOSE_ENV="$APP_DIR/deploy/.env"
BE_ENV="$APP_DIR/backend/.env"
API_IMAGE="sswhl-api:1.0"
API_PORT="18080"
DB_CONTAINER="sswhl-mysql"
DB_NAME="sswhl_new"
KEEP_BACKUPS=10

MODE=""
PKG_FILE=""
DB_FILE=""
IMG_FILE=""
TABLES=""
YES=0
DO_SCHEMA=0
DO_DB_BACKUP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --status)   MODE="status"; shift ;;
    --pkg)      MODE="code"; PKG_FILE="${2:-}"; shift 2 ;;
    --db)       MODE="data"; DB_FILE="${2:-}"; shift 2 ;;
    --image)    MODE="image"; IMG_FILE="${2:-}"; shift 2 ;;
    --rollback) MODE="rollback"; shift ;;
    --tables)   TABLES="${2:-}"; shift 2 ;;
    --schema)   DO_SCHEMA=1; shift ;;
    --backup-db) DO_DB_BACKUP=1; shift ;;
    --yes)      YES=1; shift ;;
    -h|--help)  sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数:$1(用 --help 查看用法)"; exit 1 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_off=$'\033[0m'
log()  { echo "  ${c_grn}✔${c_off} $*"; }
warn() { echo "  ${c_ylw}!${c_off} $*"; }
step() { echo; echo "${c_ylw}==> $*${c_off}"; }
die()  { echo; echo "${c_red}✘ $*${c_off}" >&2; exit 1; }

get_env() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- || true; }
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }
stamp() { date +%Y%m%d-%H%M; }

[[ $EUID -eq 0 ]] || die "请用 sudo 运行:sudo bash $0"
[[ -d "$APP_DIR/backend/app" ]] || die "找不到 $APP_DIR/backend/app,请先解压部署包到 $APP_DIR"
docker image inspect "$API_IMAGE" >/dev/null 2>&1 || die "缺少镜像 $API_IMAGE,先执行:sudo docker load -i sswhl-api-image.tar"
mkdir -p "$BACKUP_DIR"

ROOT_PASS() { get_env MYSQL_ROOT_PASSWORD "$COMPOSE_ENV"; }
db_alive()  { docker exec "$DB_CONTAINER" mysql -uroot -p"$(ROOT_PASS)" -e "select 1" >/dev/null 2>&1; }

# --------------------------------------------------------------- 备份
backup_code() {
  local dst="$BACKUP_DIR/code-$(stamp).tar.gz"
  tar -czf "$dst" -C "$APP_DIR" backend/app backend/scripts frontend/dist 2>/dev/null \
    || die "代码备份失败(磁盘满?)"
  log "代码已备份 -> $dst"
  ls -1t "$BACKUP_DIR"/code-*.tar.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS+1)) | xargs -r rm -f
}

backup_db() {
  db_alive || die "数据库容器未运行,无法备份。先执行:docker start $DB_CONTAINER"
  local dst="$BACKUP_DIR/db-$(stamp).sql.gz"
  printf '  正在备份数据库'
  docker exec "$DB_CONTAINER" mysqldump -uroot -p"$(ROOT_PASS)" \
    --single-transaction --default-character-set=utf8mb4 --no-tablespaces \
    --set-gtid-purged=OFF --databases "$DB_NAME" 2>/dev/null | gzip -6 > "$dst" \
    || die "数据库备份失败"
  gunzip -t "$dst" 2>/dev/null || die "备份文件校验失败:$dst"
  log "数据库已备份 -> $dst ($(du -h "$dst" | cut -f1))"
  ls -1t "$BACKUP_DIR"/db-*.sql.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS+1)) | xargs -r rm -f
}

apply_schema() {
  step "补表结构与权限码(容器内 init_db,幂等)"
  dc --profile docker-api run --rm --no-deps api python -m scripts.init_db \
    || die "init_db 失败,见上方报错。代码已更新但未重启,可先 --rollback 回退"
  log "表结构与权限码就绪"
}

restart_api() {
  step "重启 API 容器"
  dc --profile docker-api up -d --force-recreate api >/dev/null 2>&1 \
    || die "重启失败。排查:docker logs sswhl-api --tail 50"
  printf '  等待服务就绪'
  local ok=0
  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
    printf '.'; sleep 2
  done
  echo
  if [[ $ok -ne 1 ]]; then
    echo "---- API 日志(最近 40 行)----"
    docker logs sswhl-api --tail 40 2>&1 || true
    die "健康检查未通过。代码已备份,可执行:sudo bash $0 --rollback"
  fi
  log "服务已重启并通过健康检查"
}

write_version() {
  local note="$1"
  {
    echo "updated_at=$(date '+%F %T')"
    echo "note=$note"
    echo "pkg_md5=${2:-}"
  } > "$APP_DIR/.deploy-version"
}

# --------------------------------------------------------------- 状态
if [[ "$MODE" == "status" ]]; then
  step "当前部署状态"
  if [[ -f "$APP_DIR/.deploy-version" ]]; then
    sed 's/^/  /' "$APP_DIR/.deploy-version"
  else
    warn "还没有更新记录(.deploy-version 不存在)"
  fi
  echo
  echo "  镜像:"
  docker images "$API_IMAGE" --format '    {{.Repository}}:{{.Tag}}  {{.ID}}  {{.CreatedSince}}  {{.Size}}'
  echo "  容器:"
  docker ps -a --filter "name=sswhl" --format '    {{.Names}}  {{.Status}}  {{.Ports}}'
  echo "  数据量:"
  if db_alive; then
    docker exec "$DB_CONTAINER" mysql -uroot -p"$(ROOT_PASS)" -N -e \
      "select concat('    表数=',count(*)) from information_schema.tables where table_schema='$DB_NAME';
       select concat('    用户数=',count(*)) from $DB_NAME.users;
       select concat('    工单数=',count(*)) from $DB_NAME.gongdan;" 2>/dev/null || true
  else
    warn "数据库容器未运行"
  fi
  echo "  备份(最近 5 份):"
  ls -1t "$BACKUP_DIR"/code-*.tar.gz "$BACKUP_DIR"/db-*.sql.gz 2>/dev/null | head -5 | sed 's/^/    /' \
    || echo "    (无)"
  echo "  可用空间:"
  df -h "$APP_DIR" | tail -1 | sed 's/^/    /'
  exit 0
fi

# --------------------------------------------------------------- 回滚
if [[ "$MODE" == "rollback" ]]; then
  LATEST="$(ls -1t "$BACKUP_DIR"/code-*.tar.gz 2>/dev/null | head -1 || true)"
  [[ -n "$LATEST" ]] || die "$BACKUP_DIR 里没有代码备份,无法回滚"
  step "回滚代码到 $LATEST"
  warn "只回滚代码,不回滚数据库(如需回滚数据,见 README 第十二节)"
  backup_code >/dev/null
  rm -rf "$APP_DIR/backend/app.old" "$APP_DIR/backend/scripts.old" "$APP_DIR/frontend/dist.old"
  mv "$APP_DIR/backend/app" "$APP_DIR/backend/app.old"
  mv "$APP_DIR/backend/scripts" "$APP_DIR/backend/scripts.old"
  mv "$APP_DIR/frontend/dist" "$APP_DIR/frontend/dist.old"
  tar -xzf "$LATEST" -C "$APP_DIR" || die "解压备份失败"
  rm -rf "$APP_DIR/backend/app.old" "$APP_DIR/backend/scripts.old" "$APP_DIR/frontend/dist.old"
  log "代码已恢复"
  write_version "rollback from $LATEST"
  restart_api
  log "回滚完成"
  exit 0
fi

# --------------------------------------------------------------- ⑤ 更新镜像
if [[ "$MODE" == "image" ]]; then
  [[ -f "$IMG_FILE" ]] || die "找不到镜像文件:$IMG_FILE"
  step "导入新镜像(更新的是依赖与 Python 环境,不是业务代码)"
  backup_code
  docker load -i "$IMG_FILE" | sed 's/^/  /' || die "docker load 失败"
  log "镜像已导入"
  restart_api
  write_version "image $(basename "$IMG_FILE")"
  log "完成。业务代码来自 $APP_DIR 的挂载目录,如需一并更新请再跑 --pkg"
  exit 0
fi

# --------------------------------------------------------------- ① 更新程序
if [[ "$MODE" == "code" ]]; then
  [[ -f "$PKG_FILE" ]] || die "找不到部署包:$PKG_FILE"
  step "更新程序:$(basename "$PKG_FILE") ($(du -h "$PKG_FILE" | cut -f1))"

  TMP="$(mktemp -d /tmp/sswhl-upd-XXXXXX)"
  trap 'rm -rf "$TMP"' EXIT
  tar -xzf "$PKG_FILE" -C "$TMP" || die "解压失败,文件可能传断了(重新上传)"
  for d in backend/app backend/scripts frontend/dist; do
    [[ -d "$TMP/$d" ]] || die "包里缺少 $d,这不是完整的部署包"
  done
  log "包内容校验通过"

  # 依赖是否变化:依赖在镜像里,挂载覆盖不到
  REQ_CHANGED=0
  if [[ -f "$TMP/backend/requirements-linux.txt" && -f "$APP_DIR/backend/requirements-linux.txt" ]]; then
    if ! cmp -s "$TMP/backend/requirements-linux.txt" "$APP_DIR/backend/requirements-linux.txt"; then
      REQ_CHANGED=1
    fi
  fi

  if [[ $DO_DB_BACKUP -eq 1 ]]; then backup_db; else warn "跳过数据库备份(如需: --backup-db)"; fi
  backup_code

  step "替换代码目录"
  for d in backend/app backend/scripts frontend/dist; do
    dst="$APP_DIR/$d"
    src="$TMP/$d"
    rm -rf "$dst.new"
    cp -a "$src" "$dst.new"
    rm -rf "$dst.old"
    mv "$dst" "$dst.old"
    mv "$dst.new" "$dst"
    rm -rf "$dst.old"
    log "$d 已更新"
  done
  find "$APP_DIR/backend/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

  # 把新的 requirements 记录同步过去,供下次比对
  [[ -f "$TMP/backend/requirements-linux.txt" ]] && cp -f "$TMP/backend/requirements-linux.txt" "$APP_DIR/backend/requirements-linux.txt"
  # deploy 目录只取脚本,不覆盖 .env
  # ⚠️ 必须「写临时文件 + mv 原子替换」:脚本自身正在被 bash 逐行读取,
  #   直接 cp -f 覆盖同一 inode 会让后续行错乱(尤其 update.sh 覆盖自己)。
  for f in update.sh install-container.sh docker-compose.yml; do
    if [[ -f "$TMP/deploy/$f" ]]; then
      cp -f "$TMP/deploy/$f" "$APP_DIR/deploy/$f.new" \
        && mv -f "$APP_DIR/deploy/$f.new" "$APP_DIR/deploy/$f"
    fi
  done

  [[ $DO_SCHEMA -eq 1 ]] && apply_schema || warn "未补表结构。若模型新增了字段,请加 --schema"

  restart_api
  write_version "code $(basename "$PKG_FILE")" "$(md5sum "$PKG_FILE" | cut -d' ' -f1)"

  if [[ $REQ_CHANGED -eq 1 ]]; then
    echo
    warn "检测到 requirements-linux.txt 有变化!"
    warn "依赖装在镜像里,挂载覆盖不到。请在开发机重新生成镜像,再执行:"
    warn "  sudo bash $0 --image ~/sswhl-api-image.tar"
  fi
  log "完成 -> http://$(hostname -I | awk '{print $1}'):$API_PORT"
  exit 0
fi

# --------------------------------------------------------------- ③④ 更新数据
if [[ "$MODE" == "data" ]]; then
  [[ -f "$DB_FILE" ]] || die "找不到 SQL 文件:$DB_FILE"
  db_alive || die "数据库容器未运行。先执行:docker start $DB_CONTAINER"

  if [[ -z "$TABLES" ]]; then
    NDROP="$(gunzip -c "$DB_FILE" | grep -c '^DROP TABLE IF EXISTS' || true)"
    step "全量覆盖数据库(含 ${NDROP:-0} 条 DROP TABLE)"
    warn "这会删除并重建 $DB_NAME 里的表,服务器上新录入的数据会全部丢失"
    if [[ $YES -ne 1 ]]; then
      echo
      echo "  确认无误会先自动备份,然后继续请执行(加 --yes):"
      echo "    sudo bash $0 --db $DB_FILE --yes"
      exit 1
    fi
    backup_db
    printf '  正在导入'
    gunzip -c "$DB_FILE" | docker exec -i "$DB_CONTAINER" mysql -uroot -p"$(ROOT_PASS)" \
      --default-character-set=utf8mb4 || die "导入失败,数据已备份于 $BACKUP_DIR"
    echo; log "全量导入完成"
    apply_schema
    restart_api
    write_version "full data $(basename "$DB_FILE")"
    exit 0
  fi

  # 只覆盖指定表
  step "只覆盖指定表:$TABLES"
  warn "这些表会被 DROP + 重建,表内自增 id 会重置;若别的表用 id 引用了它们,引用会错位"
  backup_db

  IFS=',' read -r -a TBL_ARR <<< "$TABLES"
  TMP="$(mktemp -d /tmp/sswhl-tbl-XXXXXX)"
  trap 'rm -rf "$TMP"' EXIT
  gunzip -c "$DB_FILE" > "$TMP/full.sql" || die "解压失败"

  for tbl in "${TBL_ARR[@]}"; do
    tbl="$(echo "$tbl" | tr -d ' ')"
    [[ -n "$tbl" ]] || continue
    if ! grep -q "DROP TABLE IF EXISTS \`$tbl\`" "$TMP/full.sql"; then
      warn "跳过 $tbl:dump 里没有这张表(拼写错误?表名大小写?)"
      continue
    fi
    awk -v t="$tbl" '
      /^DROP TABLE IF EXISTS/ {
        if (inb==1) inb=0
        if (index($0, "`" t "`") > 0) inb=1
      }
      inb==1 { print }
      /^UNLOCK TABLES;/ { if (inb==1) inb=0 }
    ' "$TMP/full.sql" > "$TMP/$tbl.sql"
    n=$(grep -c "^INSERT INTO" "$TMP/$tbl.sql" || true)
    if [[ ! -s "$TMP/$tbl.sql" ]]; then
      warn "跳过 $tbl:提取结果为空"
      continue
    fi
    docker exec -i "$DB_CONTAINER" mysql -uroot -p"$(ROOT_PASS)" \
      --default-character-set=utf8mb4 "$DB_NAME" < "$TMP/$tbl.sql" \
      || die "导入 $tbl 失败,数据已备份于 $BACKUP_DIR"
    log "$tbl 已覆盖($n 条 INSERT 语句)"
  done

  restart_api
  write_version "tables [$TABLES] from $(basename "$DB_FILE")"
  log "数据更新完成"
  exit 0
fi

sed -n '2,22p' "$0"
