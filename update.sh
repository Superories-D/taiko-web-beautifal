#!/usr/bin/env bash
set -Eeuo pipefail

case "$0" in
  */*) SCRIPT_PATH="$0" ;;
  *) SCRIPT_PATH="./$0" ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "${SCRIPT_PATH%/*}" && pwd)
exec "${BASH:-bash}" "$SCRIPT_DIR/setup.sh" update "$@"
