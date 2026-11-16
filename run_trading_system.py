#!/usr/bin/env python3
"""Run Trading System - Main CLI Entry Point for Bitbank Autonomous System.

Coordinates the 6 specialized roles in a 10-second tick cycle:
- Role 1: Position Reviewer
- Role 2: Directional Strategist
- Role 3: Market Trend Analyst
- Role 4: Wick Anatomy Analyst
- Role 5: Technical & Order Book Analyst
- Role 6: Risk & Profit Execution Manager
Renders the institutional ASCII Easy Dashboard.

Usage:
  python3 run_trading_system.py --mode dry-run --once
  python3 run_trading_system.py --mode live --interval 10
"""

import argparse
import logging
import os
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("RunTradingSystem")


def load_env(path: str) -> None:
    """Load environment variables from .env file if present."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except FileNotFoundError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bitbank Autonomous Multi-Role Trading System CLI Entry Point"
    )
    parser.add_argument(
        "--mode",
        choices=["live", "dry-run"],
        default="dry-run",
        help="Execution mode: 'dry-run' (simulation / safe monitoring) or 'live' (live orders). Default: dry-run",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Execute a single tick and terminate immediately",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Tick execution interval in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--baseline",
        type=float,
        default=10001.0,
        help="Starting baseline budget in JPY (default: 10001.0)",
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=None,
        help="Target trading pairs (default: btc_jpy eth_jpy sol_jpy xrp_jpy doge_jpy)",
    )

    args = parser.parse_args()

    # Load environment variables
    script_dir = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(script_dir, ".env"))
    load_env("/home/karma/Trading-bot/.env")

    from tradingbot.bitbank import Bitbank
    from tradingbot.orchestrator import TradingOrchestrator

    client = Bitbank()

    orchestrator = TradingOrchestrator(
        client=client,
        baseline_budget_jpy=args.baseline,
        mode=args.mode,
        pairs=args.pairs,
    )

    orchestrator.run_loop(interval=args.interval, once=args.once)


if __name__ == "__main__":
    main()
