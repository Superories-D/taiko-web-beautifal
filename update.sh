#!/usr/bin/env bash
set -Eeuo pipefail

case "$0" in
  */*) SCRIPT_PATH="$0" ;;
  *) SCRIPT_PATH="./$0" ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "${SCRIPT_PATH%/*}" && pwd)
INSTALL_DIR=${INSTALL_DIR:-/srv/taiko-web}
UPDATE_MODE=${TAIKO_WEB_UPDATE_MODE:-auto}

detect_update_mode() {
  if command -v docker >/dev/null 2>&1 &&
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^taiko-web-app$'; then
    echo container
    return
  fi

  if command -v systemctl >/dev/null 2>&1 &&
    systemctl is-active --quiet taiko-web 2>/dev/null; then
    echo direct
    return
  fi

  if command -v docker >/dev/null 2>&1 &&
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^taiko-web-app$'; then
    echo container
    return
  fi

  if command -v systemctl >/dev/null 2>&1 &&
    { systemctl is-enabled --quiet taiko-web 2>/dev/null ||
      [ -f /etc/systemd/system/taiko-web.service ]; }; then
    echo direct
    return
  fi

  if command -v docker >/dev/null 2>&1 && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo container
    return
  fi

  # Preserve the historical behavior for installations that cannot be detected.
  echo container
}

case "$UPDATE_MODE" in
  auto) UPDATE_MODE=$(detect_update_mode) ;;
  container|direct) ;;
  *)
    echo "Invalid TAIKO_WEB_UPDATE_MODE: $UPDATE_MODE (expected auto, container, or direct)"
    exit 2
    ;;
esac

echo "[taiko-web] Detected update mode: $UPDATE_MODE"
UPDATE_ACTION="upgrade-$UPDATE_MODE"
if [ "${TAIKO_WEB_UPDATE_DRY_RUN:-0}" = "1" ]; then
  printf '[taiko-web] Dry run: %s %s %s' "${BASH:-bash}" "$SCRIPT_DIR/setup.sh" "$UPDATE_ACTION"
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$@"
  fi
  printf '\n'
  exit 0
fi

exec "${BASH:-bash}" "$SCRIPT_DIR/setup.sh" "$UPDATE_ACTION" "$@"
