#!/usr/bin/env bash
set -Eeuo pipefail

case "$0" in
  */*) SCRIPT_PATH="$0" ;;
  *) SCRIPT_PATH="./$0" ;;
esac

SRC_DIR=$(CDPATH= cd -- "${SCRIPT_PATH%/*}" && pwd)
INSTALL_DIR=${INSTALL_DIR:-/srv/taiko-web}
DATA_DIR=${DATA_DIR:-/srv/taiko-web-data}
SERVICE_NAME=taiko-web
COMPOSE_PROJECT_NAME=taiko-web
APP_USER=${APP_USER:-www-data}
APP_GROUP=${APP_GROUP:-www-data}
BACKUP_ROOT=${BACKUP_ROOT:-$INSTALL_DIR/backups/mongodb}
DESTRUCTIVE_CONFIRMATION=I_UNDERSTAND_THIS_WILL_DELETE_MONGODB_DATA
LAST_BACKUP_DIR=
UPDATE_BEFORE_SONGS_COUNT=unknown

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [taiko-web] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing command: $1"
    exit 1
  }
}

confirm_destructive_action() {
  echo "This action will DELETE or replace MongoDB data."
  echo "Type ${DESTRUCTIVE_CONFIRMATION} to continue:"
  read -r confirmation

  if [ "$confirmation" != "$DESTRUCTIVE_CONFIRMATION" ]; then
    echo "Cancelled."
    exit 1
  fi
}

load_existing_env() {
  local env_file="$INSTALL_DIR/.env"
  if [ -f "$env_file" ]; then
    # shellcheck disable=SC1090
    set -a
    . "$env_file"
    set +a
    DATA_DIR=${TAIKO_WEB_DATA_DIR:-$DATA_DIR}
    COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-$COMPOSE_PROJECT_NAME}
    BACKUP_ROOT=${BACKUP_ROOT:-$INSTALL_DIR/backups/mongodb}
  fi
}

ensure_env_value() {
  local key="$1"
  local value="$2"
  local env_file="$INSTALL_DIR/.env"

  if grep -q "^${key}=" "$env_file" 2>/dev/null; then
    log ".env already has ${key}; keeping existing value."
  else
    printf '%s=%s\n' "$key" "$value" >>"$env_file"
    log "Added missing ${key} to .env."
  fi
}

mongo_data_exists() {
  if command -v docker >/dev/null 2>&1; then
    if docker volume inspect taiko_mongodb_data >/dev/null 2>&1; then
      return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -Eq '^(taiko-web-mongo|taiko-web-mongo-direct)$'; then
      return 0
    fi
  fi

  if [ -f "$DATA_DIR/mongo/WiredTiger" ]; then
    return 0
  fi
  if [ -d "$DATA_DIR/mongo" ] && [ "$(find "$DATA_DIR/mongo" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    return 0
  fi
  if [ -f "/srv/taiko-web-data/mongo/WiredTiger" ]; then
    return 0
  fi
  if [ -d "/srv/taiko-web-data/mongo" ] && [ "$(find /srv/taiko-web-data/mongo -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    return 0
  fi

  return 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "docker compose is not available."
    exit 1
  fi
}

compose_flavor() {
  if docker compose version >/dev/null 2>&1; then
    echo "v2"
  elif command -v docker-compose >/dev/null 2>&1; then
    echo "v1"
  else
    echo "missing"
  fi
}

mongodb_container() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if docker ps --format '{{.Names}}' | grep -q '^taiko-web-mongo$'; then
    echo "taiko-web-mongo"
    return 0
  fi
  if docker ps --format '{{.Names}}' | grep -q '^taiko-web-mongo-direct$'; then
    echo "taiko-web-mongo-direct"
    return 0
  fi
  return 1
}

mongodb_container_exists() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  docker ps -a --format '{{.Names}}' | grep -Eq '^(taiko-web-mongo|taiko-web-mongo-direct)$'
}

mongo_auth_args() {
  MONGO_AUTH_ARGS=()
  if [ -n "${MONGO_ROOT_USERNAME:-}" ] && [ -n "${MONGO_ROOT_PASSWORD:-}" ]; then
    MONGO_AUTH_ARGS=(
      --username "$MONGO_ROOT_USERNAME"
      --password "$MONGO_ROOT_PASSWORD"
      --authenticationDatabase admin
    )
  fi
}

wait_for_mongodb() {
  local attempts=30
  local container
  mongo_auth_args
  for _ in $(seq 1 "$attempts"); do
    container=$(mongodb_container || true)
    if [ -n "$container" ]; then
      if docker exec "$container" mongosh "${MONGO_AUTH_ARGS[@]}" --quiet --eval "db.adminCommand({ ping: 1 }).ok" >/dev/null 2>&1; then
        return 0
      fi
    elif command -v mongosh >/dev/null 2>&1; then
      if mongosh "${MONGO_AUTH_ARGS[@]}" --quiet --eval "db.adminCommand({ ping: 1 }).ok" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

ensure_mongodb_running() {
  load_existing_env
  if [ -n "$(mongodb_container || true)" ]; then
    wait_for_mongodb
    return $?
  fi

  if mongodb_container_exists; then
    log "Starting existing MongoDB container for backup/health check."
    docker start taiko-web-mongo >/dev/null 2>&1 || docker start taiko-web-mongo-direct >/dev/null 2>&1 || true
    wait_for_mongodb
    return $?
  fi

  if [ -f "$INSTALL_DIR/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
    log "Starting Compose MongoDB service for backup/health check."
    (
      cd "$INSTALL_DIR"
      compose up -d mongo
    )
    wait_for_mongodb
    return $?
  fi

  if systemctl list-unit-files mongod.service >/dev/null 2>&1; then
    log "Starting system MongoDB service for backup/health check."
    systemctl start mongod || true
    wait_for_mongodb
    return $?
  fi

  return 1
}

mongodb_eval() {
  local script="$1"
  local container
  mongo_auth_args
  container=$(mongodb_container || true)
  if [ -n "$container" ]; then
    docker exec "$container" mongosh "${MONGO_AUTH_ARGS[@]}" --quiet --eval "$script"
  else
    mongosh "${MONGO_AUTH_ARGS[@]}" --quiet --eval "$script"
  fi
}

mongodb_collection_count() {
  local collection="$1"
  mongodb_eval "const dbname = db.getSiblingDB('taiko'); const names = dbname.getCollectionNames(); print(names.includes('${collection}') ? dbname.getCollection('${collection}').countDocuments({}) : 0)" 2>/dev/null | tail -n 1
}

backup_mongodb() {
  load_existing_env
  if ! mongo_data_exists; then
    log "No existing MongoDB data detected; skipping backup."
    LAST_BACKUP_DIR=
    return 0
  fi

  ensure_mongodb_running || {
    echo "MongoDB data exists, but MongoDB could not be started for backup. Update aborted."
    exit 1
  }

  local backup_dir="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  log "Creating MongoDB backup at $backup_dir"
  mongo_auth_args

  local container
  container=$(mongodb_container || true)
  if [ -n "$container" ]; then
    docker exec "$container" rm -rf /tmp/mongodump
    docker exec "$container" mongodump "${MONGO_AUTH_ARGS[@]}" --out /tmp/mongodump
    docker cp "$container:/tmp/mongodump" "$backup_dir"
    docker exec "$container" rm -rf /tmp/mongodump
  else
    require_cmd mongodump
    mongodump "${MONGO_AUTH_ARGS[@]}" --out "$backup_dir/mongodump"
  fi

  LAST_BACKUP_DIR="$backup_dir"
  log "MongoDB backup completed: $backup_dir"
  log "Restore command: $0 restore-db $backup_dir/mongodump"
}

restore_mongodb() {
  local backup_path="${1:-}"
  if [ -z "$backup_path" ]; then
    echo "Usage: $0 restore-db $BACKUP_ROOT/YYYYMMDD-HHMMSS/mongodump"
    exit 1
  fi
  if [ ! -d "$backup_path" ]; then
    echo "Backup path not found: $backup_path"
    exit 1
  fi

  confirm_destructive_action
  ensure_mongodb_running || {
    echo "MongoDB could not be started for restore."
    exit 1
  }

  mongo_auth_args
  local container
  container=$(mongodb_container || true)
  if [ -n "$container" ]; then
    docker exec "$container" rm -rf /tmp/restore
    docker cp "$backup_path" "$container:/tmp/restore"
    docker exec "$container" mongorestore "${MONGO_AUTH_ARGS[@]}" --drop /tmp/restore
    docker exec "$container" rm -rf /tmp/restore
  else
    require_cmd mongorestore
    mongorestore "${MONGO_AUTH_ARGS[@]}" --drop "$backup_path"
  fi
  log "MongoDB restored from $backup_path"
}

check_mongodb_health() {
  local before_songs_count="${1:-unknown}"
  local backup_dir="${2:-}"

  ensure_mongodb_running || {
    echo "MongoDB health check failed: cannot connect."
    [ -n "$backup_dir" ] && echo "Latest backup: $backup_dir"
    exit 1
  }

  mongodb_eval "db.adminCommand({ ping: 1 })" >/dev/null
  local after_songs_count
  after_songs_count=$(mongodb_collection_count songs || echo "unknown")
  log "MongoDB songs count before update: $before_songs_count"
  log "MongoDB songs count after update: $after_songs_count"

  if [ "$before_songs_count" != "unknown" ] && [ "$before_songs_count" != "0" ] && [ "$after_songs_count" = "0" ]; then
    echo "MongoDB data health check failed: songs count dropped to 0."
    [ -n "$backup_dir" ] && echo "Restore command: $0 restore-db $backup_dir/mongodump"
    exit 1
  fi
}

prepare_mongodb_update() {
  local skip_backup="${1:-false}"
  load_existing_env
  ensure_data_dirs
  UPDATE_BEFORE_SONGS_COUNT=unknown
  LAST_BACKUP_DIR=

  if ! mongo_data_exists; then
    log "No existing MongoDB data detected; update will continue without a database backup."
    return 0
  fi

  ensure_mongodb_running || {
    echo "MongoDB data exists, but MongoDB could not be started for pre-update checks."
    exit 1
  }
  UPDATE_BEFORE_SONGS_COUNT=$(mongodb_collection_count songs || echo "unknown")

  if [ "$skip_backup" = "true" ]; then
    echo "WARNING: --skip-backup was requested. MongoDB update backup is being skipped."
    echo "This is high risk and should only be used after a verified manual backup."
    return 0
  fi

  backup_mongodb
}

apt_install() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y "$@"
}

ensure_base_sync_tools() {
  apt_install rsync curl ca-certificates gnupg
}

sync_source() {
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '.env' \
    --exclude 'backups' \
    --exclude 'config.py' \
    --exclude 'public/songs' \
    --exclude 'taiko-editor/.venv' \
    --exclude 'taiko-editor/build' \
    --exclude 'taiko-editor/dist' \
    "$SRC_DIR/" "$INSTALL_DIR/"
}

ensure_config() {
  if [ ! -f "$INSTALL_DIR/config.py" ] && [ -f "$INSTALL_DIR/config.example.py" ]; then
    cp "$INSTALL_DIR/config.example.py" "$INSTALL_DIR/config.py"
  fi
}

ensure_data_dirs() {
  mkdir -p "$DATA_DIR/songs" "$DATA_DIR/mongo" "$DATA_DIR/redis"
}

write_compose_env() {
  mkdir -p "$INSTALL_DIR"
  if [ ! -f "$INSTALL_DIR/.env" ]; then
    : >"$INSTALL_DIR/.env"
    log ".env created. Existing values will be preserved on future runs."
  else
    log ".env already exists; keeping existing values."
  fi
  ensure_env_value COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT_NAME"
  ensure_env_value TAIKO_WEB_DATA_DIR "$DATA_DIR"
  load_existing_env
}

write_systemd_service() {
  cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Taiko Web
After=network.target mongod.service redis-server.service docker.service
Wants=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
Environment=TAIKO_WEB_SONGS_DIR=$DATA_DIR/songs
Environment=TAIKO_WEB_MONGO_HOST=127.0.0.1:27017
Environment=TAIKO_WEB_REDIS_HOST=127.0.0.1
Environment=REDIS_URI=redis://127.0.0.1:6379/0
ExecStart=$INSTALL_DIR/.venv/bin/gunicorn -b 0.0.0.0:80 app:app
Restart=always
User=$APP_USER
Group=$APP_GROUP
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF
}

stop_direct_service() {
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
}

remove_direct_service() {
  stop_direct_service
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload || true
}

ensure_docker() {
  apt_install docker.io
  if ! docker compose version >/dev/null 2>&1; then
    if ! apt-get install -y docker-compose-plugin; then
      install_docker_apt_repo || true
      apt-get update -y || true
      apt-get install -y docker-compose-plugin || install_compose_plugin_manual || true
    fi
  fi
  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    apt-get install -y docker-compose || true
  fi
  systemctl enable --now docker
  require_cmd docker
  if [ "$(compose_flavor)" = "missing" ]; then
    echo "docker compose is not available."
    exit 1
  fi
  log "Using Docker Compose $(compose_flavor)."
  if [ "$(compose_flavor)" = "v1" ]; then
    log "Compose v2 could not be installed; falling back to docker-compose v1."
  fi
}

install_docker_apt_repo() {
  . /etc/os-release || true
  local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  [ -n "$codename" ] || return 1

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
}

install_compose_plugin_manual() {
  local arch
  case "$(uname -m)" in
    x86_64|amd64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    armv7l|armv7*) arch="armv7" ;;
    *) return 1 ;;
  esac
  install -m 0755 -d /usr/local/lib/docker/cli-plugins
  curl -fL "https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-${arch}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
}

install_mongodb_direct() {
  if command -v mongod >/dev/null 2>&1; then
    return 0
  fi

  . /etc/os-release || true
  local codename="${VERSION_CODENAME:-}"

  if [ -n "$codename" ] && echo "$codename" | grep -Eq '^(focal|jammy)$'; then
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${codename}/mongodb-org/7.0 multiverse" \
      > /etc/apt/sources.list.d/mongodb-org-7.0.list
    apt-get update -y
    apt-get install -y mongodb-org
    return 0
  fi

  return 1
}

remove_container_stack() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi

  if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    (
      cd "$INSTALL_DIR"
      compose down --remove-orphans >/dev/null 2>&1 || true
    )
  fi

  docker rm -f taiko-web-app taiko-web-mongo taiko-web-redis >/dev/null 2>&1 || true
}

remove_named_stack_containers() {
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  docker rm -f taiko-web-app taiko-web-mongo taiko-web-redis >/dev/null 2>&1 || true
}

compose_up_or_recreate_named() {
  local log_file
  log_file=$(mktemp)
  if compose "$@" 2>"$log_file"; then
    rm -f "$log_file"
    return 0
  fi

  cat "$log_file" >&2
  if grep -q "container name .* is already in use\\|Conflict. The container name" "$log_file"; then
    log "Detected stale named containers from an older Compose run; removing containers only, preserving volumes."
    remove_named_stack_containers
    rm -f "$log_file"
    compose "$@"
    return $?
  fi

  rm -f "$log_file"
  return 1
}

ensure_direct_datastores() {
  apt_install redis-server
  systemctl enable redis-server || true
  systemctl restart redis-server || systemctl start redis-server || true

  if install_mongodb_direct; then
    systemctl enable mongod || true
    systemctl restart mongod || systemctl start mongod || true
    return 0
  fi

  log "MongoDB direct install is unavailable on this system; using a MongoDB container instead."
  ensure_docker
  if ! docker ps -a --format '{{.Names}}' | grep -q '^taiko-web-mongo-direct$'; then
    docker run -d \
      --name taiko-web-mongo-direct \
      --restart unless-stopped \
      -p 27017:27017 \
      -v "$DATA_DIR/mongo:/data/db" \
      mongo:7.0
  else
    docker start taiko-web-mongo-direct >/dev/null 2>&1 || true
  fi
}

deploy_direct() {
  log "Starting direct deployment."
  ensure_base_sync_tools
  apt_install python3 python3-venv python3-pip git ffmpeg libcap2-bin
  load_existing_env
  ensure_data_dirs
  if mongo_data_exists; then
    log "Existing MongoDB data detected during install; switching to safe update behavior."
    prepare_mongodb_update false
  fi
  ensure_direct_datastores
  remove_container_stack
  sync_source
  ensure_config
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/pip" install -U pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
  chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR" "$DATA_DIR"
  write_systemd_service
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  check_mongodb_health "$UPDATE_BEFORE_SONGS_COUNT" "$LAST_BACKUP_DIR"
  log "Direct deployment completed."
  log "Persistent data directory: $DATA_DIR"
  [ -n "$LAST_BACKUP_DIR" ] && log "MongoDB backup: $LAST_BACKUP_DIR"
}

deploy_container() {
  log "Starting container deployment."
  ensure_base_sync_tools
  ensure_docker
  load_existing_env
  ensure_data_dirs
  if mongo_data_exists; then
    log "Existing MongoDB data detected during install; switching to safe update behavior."
    prepare_mongodb_update false
  fi
  stop_direct_service
  sync_source
  ensure_config
  write_compose_env
  (
    cd "$INSTALL_DIR"
    compose_up_or_recreate_named up -d --build --force-recreate --remove-orphans
  )
  check_mongodb_health "$UPDATE_BEFORE_SONGS_COUNT" "$LAST_BACKUP_DIR"
  log "Container deployment completed."
  log "Persistent data directory: $DATA_DIR"
  [ -n "$LAST_BACKUP_DIR" ] && log "MongoDB backup: $LAST_BACKUP_DIR"
}

upgrade_container() {
  local skip_backup="${1:-false}"
  log "Starting container-only upgrade."
  ensure_base_sync_tools
  ensure_docker
  prepare_mongodb_update "$skip_backup"
  sync_source
  ensure_config
  write_compose_env
  (
    cd "$INSTALL_DIR"
    compose_up_or_recreate_named up -d --build --force-recreate --remove-orphans
  )
  check_mongodb_health "$UPDATE_BEFORE_SONGS_COUNT" "$LAST_BACKUP_DIR"
  log "Container upgrade completed."
  log "Persistent data directory kept intact: $DATA_DIR"
  [ -n "$LAST_BACKUP_DIR" ] && log "MongoDB backup: $LAST_BACKUP_DIR"
}


upgrade_direct() {
  local skip_backup="${1:-false}"
  log "Starting direct upgrade."
  ensure_base_sync_tools
  apt_install python3 python3-venv python3-pip git ffmpeg libcap2-bin
  prepare_mongodb_update "$skip_backup"
  ensure_direct_datastores
  remove_container_stack
  sync_source
  ensure_config

  if [ ! -x "$INSTALL_DIR/.venv/bin/python3" ]; then
    python3 -m venv "$INSTALL_DIR/.venv"
  fi
  "$INSTALL_DIR/.venv/bin/pip" install -U pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

  chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR" "$DATA_DIR"
  write_systemd_service
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  check_mongodb_health "$UPDATE_BEFORE_SONGS_COUNT" "$LAST_BACKUP_DIR"
  log "Direct upgrade completed."
  log "Persistent data directory kept intact: $DATA_DIR"
  [ -n "$LAST_BACKUP_DIR" ] && log "MongoDB backup: $LAST_BACKUP_DIR"
}

repair_installation() {
  log "Repairing containers, permissions, and generated environment without deleting MongoDB data."
  ensure_base_sync_tools
  ensure_data_dirs
  mkdir -p "$INSTALL_DIR"
  write_compose_env
  if [ -d "$INSTALL_DIR" ]; then
    chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR" "$DATA_DIR" || true
  fi
  if [ -f "$INSTALL_DIR/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
    (
      cd "$INSTALL_DIR"
      compose_up_or_recreate_named up -d --remove-orphans
    )
  fi
  check_mongodb_health unknown "$LAST_BACKUP_DIR"
  log "Repair completed. MongoDB data directory preserved: $DATA_DIR/mongo"
}

reset_db() {
  load_existing_env
  confirm_destructive_action
  if mongo_data_exists; then
    backup_mongodb
  fi
  ensure_data_dirs

  log "Resetting MongoDB data directory after explicit confirmation."
  if command -v docker >/dev/null 2>&1; then
    docker rm -f taiko-web-mongo taiko-web-mongo-direct >/dev/null 2>&1 || true
  fi

  local mongo_dir
  mongo_dir=$(readlink -f "$DATA_DIR/mongo")
  local data_root
  data_root=$(readlink -f "$DATA_DIR")
  if [ -z "$mongo_dir" ] || [ -z "$data_root" ] || [ "${mongo_dir#"$data_root"/}" = "$mongo_dir" ]; then
    echo "Refusing to reset MongoDB: resolved path is outside DATA_DIR."
    exit 1
  fi
  rm -rf "$mongo_dir"
  mkdir -p "$mongo_dir"
  log "MongoDB data reset completed."
  [ -n "$LAST_BACKUP_DIR" ] && log "Pre-reset backup: $LAST_BACKUP_DIR"
}

uninstall_all() {
  log "Starting uninstall."
  remove_direct_service
  if command -v docker >/dev/null 2>&1; then
    remove_container_stack
    docker rm -f taiko-web-mongo-direct >/dev/null 2>&1 || true
  fi
  rm -rf "$INSTALL_DIR"
  log "Application files removed."
  log "Persistent data directory preserved: $DATA_DIR"
}

print_menu() {
  printf '%s\n' \
    "Available actions:" \
    "  install              First install with persistent MongoDB data directory" \
    "  update [--skip-backup]" \
    "                       Safe update; backs up MongoDB before changing services" \
    "  backup-db           Create a MongoDB backup only" \
    "  restore-db PATH     Restore MongoDB from a backup; requires full confirmation" \
    "  repair              Repair containers/env/permissions without deleting data" \
    "  reset-db            Delete MongoDB data; requires full confirmation" \
    "  deploy-container    Legacy alias for install" \
    "  deploy-direct       Direct-system install" \
    "  upgrade-container   Legacy alias for update" \
    "  upgrade-direct      Direct-system update" \
    "  uninstall           Remove app files; preserves persistent data directory"
}

main() {
  local action="${1:-}"
  if [ "$#" -gt 0 ]; then
    shift
  fi
  local skip_backup=false
  local positional=()

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --skip-backup)
        skip_backup=true
        ;;
      --help|-h)
        print_menu
        exit 0
        ;;
      *)
        positional+=("$1")
        ;;
    esac
    shift
  done

  if [ -z "$action" ]; then
    load_existing_env
    if mongo_data_exists || [ -d "$INSTALL_DIR" ]; then
      action="update"
      log "Existing installation or MongoDB data detected; defaulting to safe update."
    else
      action="install"
      log "No existing installation detected; defaulting to install."
    fi
  fi

  case "$action" in
    menu|help|--help|-h)
      print_menu
      exit 0
      ;;
  esac

  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Root privileges are required."
    exit 1
  fi

  case "$action" in
    install) deploy_container ;;
    update) upgrade_container "$skip_backup" ;;
    backup-db) backup_mongodb ;;
    restore-db) restore_mongodb "${positional[0]:-}" ;;
    repair) repair_installation ;;
    reset-db) reset_db ;;
    deploy-container) deploy_container ;;
    deploy-direct) deploy_direct ;;
    upgrade-container) upgrade_container "$skip_backup" ;;
    upgrade-direct) upgrade_direct "$skip_backup" ;;
    uninstall) uninstall_all ;;
    *)
      echo "Unknown command: $action"
      print_menu
      exit 1
      ;;
  esac
}

main "$@"
