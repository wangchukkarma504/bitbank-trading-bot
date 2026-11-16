#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Stopping Bitbank FastAPI Trading Server..."
if [[ -f ".server.pid" ]]; then
  PID="$(cat .server.pid)"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" || true
  fi
  rm -f .server.pid
fi

pkill -f "tradingbot.server" 2>/dev/null || true
echo "Stopped. (Note: any open Bitbank positions keep their native exchange-side stop orders.)"
