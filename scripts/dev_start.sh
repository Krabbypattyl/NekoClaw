#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtualenv Python: $VENV_PYTHON"
  echo "Create it first, for example:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e \".[dev]\""
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

WORKING_DIR="${COPAW_WORKING_DIR:-$HOME/.copaw-dev}"
HOST="${COPAW_DEV_HOST:-127.0.0.1}"
PORT="${COPAW_DEV_PORT:-8098}"
LOG_LEVEL="${COPAW_LOG_LEVEL:-debug}"
RELOAD="${COPAW_DEV_RELOAD:-1}"

mkdir -p "$WORKING_DIR"

if [[ ! -f "$WORKING_DIR/config.json" ]]; then
  echo "Initializing isolated dev workspace at $WORKING_DIR"
  "$VENV_PYTHON" -m copaw init --defaults
fi

echo "Starting CoPaw dev server"
echo "  repo:        $ROOT_DIR"
echo "  working dir: $WORKING_DIR"
echo "  url:         http://$HOST:$PORT"
echo "  reload:      $RELOAD"

CMD=(
  "$VENV_PYTHON"
  -m copaw
  app
  --host "$HOST"
  --port "$PORT"
  --log-level "$LOG_LEVEL"
)

if [[ "$RELOAD" == "1" || "$RELOAD" == "true" || "$RELOAD" == "yes" ]]; then
  CMD+=(--reload)
fi

exec "${CMD[@]}"
