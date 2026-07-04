#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=${NETPLAY_INSTALL_DIR:-/opt/taiko-netplay-ws}
CONFIG_DIR=${NETPLAY_CONFIG_DIR:-/etc/taiko-netplay-ws}
SERVICE_NAME=${NETPLAY_SERVICE_NAME:-taiko-netplay-ws}
RUN_USER=${NETPLAY_RUN_USER:-taiko-netplay}
RUN_GROUP=${NETPLAY_RUN_GROUP:-taiko-netplay}

prompt() {
  local var_name="$1"
  local label="$2"
  local default_value="${3:-}"
  local secret="${4:-false}"
  local value
  if [ -n "${!var_name:-}" ]; then
    return
  fi
  if [ "$secret" = "true" ]; then
    read -r -s -p "$label: " value
    echo
  elif [ -n "$default_value" ]; then
    read -r -p "$label [$default_value]: " value
    value=${value:-$default_value}
  else
    read -r -p "$label: " value
  fi
  printf -v "$var_name" '%s' "$value"
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Root privileges are required."
    exit 1
  fi
}

write_config() {
  mkdir -p "$CONFIG_DIR"
  local config_file="$CONFIG_DIR/config.json"
  if [ -f "$config_file" ]; then
    local backup="$config_file.$(date +%Y%m%d-%H%M%S).bak"
    cp "$config_file" "$backup"
    echo "Existing config backed up to $backup"
  fi

  cat >"$config_file" <<EOF
{
  "main_server": "$TAIKO_MAIN_SERVER",
  "server_id": "$TAIKO_SERVER_ID",
  "server_token": "$TAIKO_SERVER_TOKEN",
  "public_endpoint": "$TAIKO_PUBLIC_ENDPOINT",
  "region": "$TAIKO_REGION",
  "listen_host": "$TAIKO_LISTEN_HOST",
  "listen_port": $TAIKO_LISTEN_PORT,
  "max_players": $TAIKO_MAX_PLAYERS,
  "max_rooms": $TAIKO_MAX_ROOMS,
  "max_players_per_ip": $TAIKO_MAX_PLAYERS_PER_IP,
  "heartbeat_interval": $TAIKO_HEARTBEAT_INTERVAL,
  "invite_ttl_seconds": 300,
  "room_idle_seconds": 900,
  "allowed_origins": [$(printf '%s' "$TAIKO_ALLOWED_ORIGINS" | awk -v RS=, '{gsub(/^[ \t]+|[ \t]+$/, ""); if ($0 != "") printf "%s\"%s\"", sep, $0; sep=", "}')]
}
EOF
  chmod 600 "$config_file"
}

install_files() {
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip rsync

  if ! getent group "$RUN_GROUP" >/dev/null 2>&1; then
    groupadd --system "$RUN_GROUP"
  fi
  if ! id "$RUN_USER" >/dev/null 2>&1; then
    useradd --system --gid "$RUN_GROUP" --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$RUN_USER"
  fi
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude '.venv' \
    --exclude 'config.json' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/pip" install -U pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
  chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR"
  chown -R root:"$RUN_GROUP" "$CONFIG_DIR"
  chmod 750 "$CONFIG_DIR"
}

install_service() {
  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
  cp "$INSTALL_DIR/systemd/taiko-netplay-ws.service" "$service_file"
  sed -i \
    -e "s#/opt/taiko-netplay-ws#$INSTALL_DIR#g" \
    -e "s#/etc/taiko-netplay-ws#$CONFIG_DIR#g" \
    -e "s#User=taiko-netplay#User=$RUN_USER#g" \
    -e "s#Group=taiko-netplay#Group=$RUN_GROUP#g" \
    "$service_file"
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
}

main() {
  require_root
  prompt TAIKO_MAIN_SERVER "Main server URL" "https://taiko.asia"
  prompt TAIKO_SERVER_ID "Official server ID" "official-jp-1"
  prompt TAIKO_SERVER_TOKEN "Server token shown once in admin" "" true
  prompt TAIKO_PUBLIC_ENDPOINT "Public WebSocket endpoint" "wss://ws-jp.taiko.asia"
  prompt TAIKO_REGION "Region label" "JP"
  prompt TAIKO_LISTEN_HOST "Listen host" "0.0.0.0"
  prompt TAIKO_LISTEN_PORT "Listen port" "8765"
  prompt TAIKO_MAX_PLAYERS "Max connected players" "100"
  prompt TAIKO_MAX_ROOMS "Max rooms" "50"
  prompt TAIKO_MAX_PLAYERS_PER_IP "Max connections per IP" "3"
  prompt TAIKO_HEARTBEAT_INTERVAL "Heartbeat interval seconds" "20"
  prompt TAIKO_ALLOWED_ORIGINS "Allowed origins, comma-separated" "$TAIKO_MAIN_SERVER,http://localhost:3000,http://127.0.0.1:3000"

  install_files
  write_config
  install_service
  echo "Installed $SERVICE_NAME."
  echo "Status: systemctl status $SERVICE_NAME"
  echo "Logs:   journalctl -u $SERVICE_NAME -f"
}

main "$@"
