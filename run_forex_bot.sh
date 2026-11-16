#!/usr/bin/env bash
# Fast-Execution Forex Bot Daemon (10,000 JPY budget, 3.0x leverage, 30s poll)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Starting High-Speed Forex Bot daemon (30s poll)..."
setsid -f python3 -u run_forex_bot.py --budget 10000 --leverage 3.0 --poll 30 >> forex_bot.log 2>&1
echo "Forex Bot daemon running in background with PID $(pgrep -f run_forex_bot)."
