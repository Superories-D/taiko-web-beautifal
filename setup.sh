#!/usr/bin/env bash
set -Eeuo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Root privileges are required."
  exit 1
fi

SRC_DIR=$(cd "$(dirname "$0")" && pwd)
INSTALL_DIR=${INSTALL_DIR:-/srv/taiko-web}
DATA_DIR=${DATA_DIR:-/srv/taiko-web-data}
SERVICE_NAME=taiko-web
COMPOSE_PROJECT_NAME=taiko-web
APP_USER=${APP_USER:-www-data}
APP_GROUP=${APP_GROUP:-www-data}

log() {
  echo "[taiko-web] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing command: $1"
    exit 1
  }
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
  cat >"$INSTALL_DIR/.env" <<EOF
COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME
TAIKO_WEB_DATA_DIR=$DATA_DIR
EOF
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
  if ! apt-get install -y docker-compose-plugin; then
    apt-get install -y docker-compose || true
  fi
  systemctl enable --now docker
  require_cmd docker
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
  ensure_data_dirs
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
  log "Direct deployment completed."
  log "Persistent data directory: $DATA_DIR"
}

deploy_container() {
  log "Starting container deployment."
  ensure_base_sync_tools
  ensure_docker
  ensure_data_dirs
  stop_direct_service
  sync_source
  ensure_config
  write_compose_env
  (
    cd "$INSTALL_DIR"
    compose up -d --build
  )
  log "Container deployment completed."
  log "Persistent data directory: $DATA_DIR"
}

upgrade_container() {
  log "Starting container-only upgrade."
  ensure_base_sync_tools
  ensure_docker
  ensure_data_dirs
  sync_source
  ensure_config
  write_compose_env
  (
    cd "$INSTALL_DIR"
    compose up -d mongo redis
    compose up -d --build app
  )
  log "Container upgrade completed."
  log "Persistent data directory kept intact: $DATA_DIR"
}


upgrade_direct() {
  log "Starting direct upgrade."
  ensure_base_sync_tools
  apt_install python3 python3-venv python3-pip git ffmpeg libcap2-bin
  ensure_data_dirs
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
  log "Direct upgrade completed."
  log "Persistent data directory kept intact: $DATA_DIR"
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
  cat <<'EOF'
Choose an action:
  1) Deploy (container)
  2) Deploy (direct)
  3) Upgrade (container only)
  4) Upgrade (direct)
  5) Uninstall
EOF
}

main() {
  local action="${1:-}"

  if [ -z "$action" ]; then
    print_menu
    read -r -p "Enter choice [1-5]: " choice
    case "$choice" in
      1) action="deploy-container" ;;
      2) action="deploy-direct" ;;
      3) action="upgrade-container" ;;
      4) action="upgrade-direct" ;;
      5) action="uninstall" ;;
      *) echo "Invalid choice."; exit 1 ;;
    esac
  fi

  case "$action" in
    deploy-container) deploy_container ;;
    deploy-direct) deploy_direct ;;
    upgrade-container) upgrade_container ;;
    upgrade-direct) upgrade_direct ;;
    uninstall) uninstall_all ;;
    *)
      echo "Unknown command: $action"
      echo "Available commands: deploy-container | deploy-direct | upgrade-container | upgrade-direct | uninstall"
      exit 1
      ;;
  esac
}

main "$@"
