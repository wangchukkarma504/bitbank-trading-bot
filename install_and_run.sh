#!/usr/bin/env bash
set -euo pipefail

# One-command installer & runner for the Bitbank Autonomous Trading Bot
# Usage:
#   ./install_and_run.sh                  # Installs deps & starts in paper mode (or live if --mode live)
#   ./install_and_run.sh --mode live      # Starts in live trading mode (requires .env API_KEY & SECRET_KEY)
#   ./install_and_run.sh --port 8080      # Custom port

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="paper"
PORT="8000"
BASELINE=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --baseline)
      BASELINE="$2"
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "[1/4] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not installed." >&2
  exit 1
fi

echo "[2/4] Setting up virtual environment (.venv)..."
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[3/4] Installing dependencies from requirements.txt..."
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt

echo "[4/4] Checking environment configuration..."
if [[ ! -f ".env" && -f ".env.example" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

if [[ "$MODE" == "live" ]]; then
  if ! grep -Eq '^(API_KEY|BITBANK_API_KEY)=.+' .env 2>/dev/null || grep -Eq '^API_KEY=your_bitbank_api_key_here$' .env 2>/dev/null; then
    echo "Warning: Live mode requires valid API_KEY and SECRET_KEY in .env."
    echo "Edit $SCRIPT_DIR/.env first, or run without --mode live for paper mode."
    exit 1
  fi
fi

CMD=(python3 -u -m tradingbot.server --mode "$MODE" --port "$PORT")
if [[ -n "$BASELINE" ]]; then
  CMD+=(--baseline "$BASELINE")
fi
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi

echo "Starting Bitbank Trading Bot ($MODE mode) on http://localhost:$PORT ..."
exec "${CMD[@]}"
