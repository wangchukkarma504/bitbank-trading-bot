#!/usr/bin/env python3
"""Main Entry Point for Binance Forex Autonomous Trading Bot.
"""

import argparse
import logging
import os
import sys

# Ensure module path is accessible
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forex_bot.bot import ForexBot


def load_env_file(path: str = ".env"):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def setup_logging():
    log_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # File Handler
    file_handler = logging.FileHandler("forex_bot.log", encoding="utf-8")
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)


def main():
    parser = argparse.ArgumentParser(description="Institutional Forex Trading Bot (Binance Demo/Live)")
    parser.add_argument("--mode", type=str, default=None, help="Execution mode: DEMO, TESTNET, or LIVE")
    parser.add_argument("--pairs", type=str, default=None, help="Comma-separated symbols, e.g., EURUSDT,EURUSDC")
    parser.add_argument("--poll", type=int, default=120, help="Polling interval in seconds (default: 120 / 2 minutes)")
    parser.add_argument("--budget", type=float, default=10000.0, help="Starting budget in JPY (default: 10000)")
    parser.add_argument("--leverage", type=float, default=3.0, help="Leverage multiplier to boost capital (default: 3.0)")
    args = parser.parse_args()

    load_env_file(".env")
    setup_logging()

    # Determine mode: CLI arg > ENV > default to DEMO
    mode = (args.mode or os.environ.get("FOREX_MODE") or os.environ.get("BINANCE_MODE") or "DEMO").upper()

    # Determine credentials based on mode
    if mode == "LIVE":
        api_key = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")
    else:
        api_key = os.environ.get("BINANCE_DEMO_API_KEY", os.environ.get("BINANCE_API_KEY", ""))
        api_secret = os.environ.get("BINANCE_DEMO_API_SECRET", os.environ.get("BINANCE_API_SECRET", ""))

    pairs_str = args.pairs or os.environ.get("FOREX_PAIRS", "EURUSDT,EURUSDC")
    pairs = [p.strip().upper() for p in pairs_str.split(",") if p.strip()]

    bot = ForexBot(
        pairs=pairs,
        mode=mode,
        api_key=api_key,
        api_secret=api_secret,
        poll_interval=args.poll,
        budget_jpy=args.budget,
        leverage=args.leverage,
    )
    bot.start()


if __name__ == "__main__":
    main()
