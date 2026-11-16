#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-live}"
PORT="${2:-8000}"
BASELINE_ARG=""
if [[ -n "${3:-}" ]]; then
  BASELINE_ARG="--baseline $3"
fi

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

pkill -f "tradingbot.server" 2>/dev/null || true
sleep 1

echo "Starting tradingbot.server (--mode $MODE --port $PORT $BASELINE_ARG) in background..."
nohup python3 -u -m tradingbot.server --mode "$MODE" --port "$PORT" $BASELINE_ARG > trading_server.log 2>&1 &
echo $! > .server.pid
echo "Started PID $(cat .server.pid). Logs: $SCRIPT_DIR/trading_server.log"
echo "Dashboard: http://localhost:$PORT"
