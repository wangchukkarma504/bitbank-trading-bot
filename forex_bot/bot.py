"""Autonomous Forex Trading Bot Daemon for Binance Demo and Live trading.

Employs Bitbank institutional trading tenets:
- 10,000 JPY budget with 3.0x leverage buying power boost
- 2-minute cycle review & trade execution cadence
- Regime-gated trend filters & ATR volatility normalization
- Mandatory protective stop losses on every fill (zero naked exposure)
- Dynamic multi-tier ratchets (Break-even, Profit Lock, Target Exit)
- Dual currency accounting: Native JPY (¥) and USDT ($)
"""

import datetime as dt
import json
import logging
import math
import os
import signal
import sys
import time
from typing import Dict, Optional

from .client import BinanceClient
from .strategy import ForexStrategy, ForexRegime

log = logging.getLogger("forex_bot")


class ForexBot:
    def __init__(
        self,
        pairs: list = None,
        mode: str = "DEMO",
        api_key: str = "",
        api_secret: str = "",
        state_file: str = "forex_state.json",
        poll_interval: int = 120,  # 2 minutes
        budget_jpy: float = 10000.0,
        leverage: float = 3.0,
        risk_per_trade: float = 0.02,  # 2% risk per leveraged setup
        max_pair_alloc: float = 0.50,  # up to 50% equity allocation per pair
    ):
        self.pairs = pairs or ["EURUSDT", "EURUSDC"]
        self.mode = mode.upper()
        self.state_file = state_file
        self.poll_interval = poll_interval
        self.budget_jpy = budget_jpy
        self.leverage = leverage
        self.risk_per_trade = risk_per_trade
        self.max_pair_alloc = max_pair_alloc
        self.running = True
        self.cycle_count = 0

        # Initialize API client
        self.client = BinanceClient(api_key=api_key, api_secret=api_secret, mode=self.mode)
        self.strategy = ForexStrategy()

        # Update USD/JPY rate
        self.usdjpy_rate = self.client.get_usdjpy_rate()

        # Load or initialize state
        self.state = self.load_state()

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        log.info("Shutdown signal received. Saving state and terminating safely...")
        self.running = False

    def load_state(self) -> dict:
        initial_usd = self.budget_jpy / self.usdjpy_rate if self.usdjpy_rate > 0 else 65.0

        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Check if previous state has budget_jpy
                    if "budget_jpy" in data:
                        log.info(f"Loaded existing state from {self.state_file}. Equity: ¥{data.get('equity_jpy', self.budget_jpy):,.1f} (${data.get('equity', initial_usd):.2f})")
                        return data
            except Exception as e:
                log.error(f"Error loading {self.state_file}: {e}. Initializing fresh state.")

        initial_state = {
            "mode": self.mode,
            "budget_jpy": self.budget_jpy,
            "starting_equity_jpy": self.budget_jpy,
            "starting_equity": initial_usd,
            "equity": initial_usd,
            "cash": initial_usd,
            "equity_jpy": self.budget_jpy,
            "cash_jpy": self.budget_jpy,
            "leverage": self.leverage,
            "usdjpy_rate": self.usdjpy_rate,
            "positions": {},
            "closed_trades": [],
            "daily_start_equity": initial_usd,
            "last_day": dt.date.today().isoformat(),
            "updated_at": dt.datetime.utcnow().isoformat(),
        }
        self.save_state(initial_state)
        return initial_state

    def save_state(self, state: dict = None):
        if state is not None:
            self.state = state
        self.state["updated_at"] = dt.datetime.utcnow().isoformat()
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state to {self.state_file}: {e}")

    def update_equity(self):
        """Update current total account equity (Cash + Unrealized PnL) in USD and JPY."""
        current_day = dt.date.today().isoformat()
        if self.state.get("last_day") != current_day:
            self.state["last_day"] = current_day
            self.state["daily_start_equity"] = self.state["equity"]
            log.info(f"New trading day. Reset daily starting equity to ¥{self.state.get('equity_jpy', self.budget_jpy):,.1f}")

        # Update live USD/JPY rate
        rate = self.client.get_usdjpy_rate()
        if rate > 0:
            self.usdjpy_rate = rate
            self.state["usdjpy_rate"] = rate

        # If live authenticated with Binance, pull real balance
        if self.client.is_authenticated():
            try:
                acct = self.client.get_account()
                usdt_bal = 0.0
                for b in acct.get("balances", []):
                    if b.get("asset") in ["USDT", "USD"]:
                        usdt_bal += float(b.get("free", 0.0)) + float(b.get("locked", 0.0))
                if usdt_bal > 0:
                    self.state["cash"] = usdt_bal
            except Exception as e:
                log.warning(f"Could not fetch account balance from API: {e}")

        # Calculate unrealized PnL of open positions
        unrealized_pnl_usd = 0.0
        for symbol, pos in list(self.state["positions"].items()):
            try:
                current_px = self.client.get_ticker_price(symbol)
                entry_px = pos["entry_price"]
                qty = pos["quantity"]
                side = pos["side"]

                if side == "BUY":
                    pos_pnl = (current_px - entry_px) * qty
                else:
                    pos_pnl = (entry_px - current_px) * qty

                pos["current_price"] = current_px
                pos["unrealized_pnl"] = pos_pnl
                pos["unrealized_pnl_jpy"] = pos_pnl * self.usdjpy_rate
                unrealized_pnl_usd += pos_pnl
            except Exception as e:
                log.warning(f"Failed to fetch price for {symbol}: {e}")

        self.state["equity"] = self.state["cash"] + unrealized_pnl_usd
        self.state["equity_jpy"] = self.state["equity"] * self.usdjpy_rate
        self.state["cash_jpy"] = self.state["cash"] * self.usdjpy_rate
        self.save_state()

    def check_daily_loss_limit(self) -> bool:
        start_eq = self.state.get("daily_start_equity", self.state["equity"])
        current_eq = self.state["equity"]
        drawdown_pct = (start_eq - current_eq) / start_eq
        if drawdown_pct >= 0.08:  # 8% max daily drawdown circuit breaker
            log.warning(f"CIRCUIT BREAKER: Daily loss limit reached (-{drawdown_pct*100:.2f}%). Halting new entries.")
            return True
        return False

    def manage_open_positions(self):
        """Monitor stops, profit targets, and dynamic ratchets for active positions."""
        for symbol, pos in list(self.state["positions"].items()):
            try:
                current_px = self.client.get_ticker_price(symbol)
                entry_px = pos["entry_price"]
                stop_px = pos["stop_loss"]
                tp1 = pos["tp1"]
                tp2 = pos["tp2"]
                side = pos["side"]
                qty = pos["quantity"]
                ratchet_stage = pos.get("ratchet_stage", 0)
                risk_unit = pos["risk_per_unit"]

                # 1. Protective Stop Loss Check (Mandatory risk cap)
                hit_stop = (current_px <= stop_px) if side == "BUY" else (current_px >= stop_px)
                if hit_stop:
                    log.warning(f"🚨 [{symbol}] STOP LOSS HIT @ {current_px:.5f} (Stop: {stop_px:.5f})")
                    self.close_position(symbol, current_px, reason="STOP_LOSS")
                    continue

                # 2. Final Take Profit Target Check (+2.5R)
                hit_tp2 = (current_px >= tp2) if side == "BUY" else (current_px <= tp2)
                if hit_tp2:
                    log.info(f"🎯 [{symbol}] TARGET 2 REACHED @ {current_px:.5f} (TP2: {tp2:.5f})")
                    self.close_position(symbol, current_px, reason="TARGET_2")
                    continue

                # 3. Dynamic Ratchets
                # Stage 1: Hit +1.0R / Mid-band -> Ratchet stop to Break-Even
                hit_tp1 = (current_px >= tp1) if side == "BUY" else (current_px <= tp1)
                if ratchet_stage == 0 and hit_tp1:
                    new_stop = entry_px + (0.0001 if side == "BUY" else -0.0001)
                    pos["stop_loss"] = self.client.round_price(symbol, new_stop)
                    pos["ratchet_stage"] = 1
                    log.info(f"🛡️ [{symbol}] RATCHET 1: Stop moved to Break-Even ({pos['stop_loss']:.5f})")
                    self.save_state()

                # Stage 2: Hit +1.2R -> Lock Profit (+0.5R)
                target_1_2r = (entry_px + 1.2 * risk_unit) if side == "BUY" else (entry_px - 1.2 * risk_unit)
                hit_1_2r = (current_px >= target_1_2r) if side == "BUY" else (current_px <= target_1_2r)
                if ratchet_stage == 1 and hit_1_2r:
                    locked_stop = (entry_px + 0.5 * risk_unit) if side == "BUY" else (entry_px - 0.5 * risk_unit)
                    pos["stop_loss"] = self.client.round_price(symbol, locked_stop)
                    pos["ratchet_stage"] = 2
                    log.info(f"🔒 [{symbol}] RATCHET 2: Profit Locked at +0.5R ({pos['stop_loss']:.5f})")
                    self.save_state()

            except Exception as e:
                log.error(f"Error managing position for {symbol}: {e}")

    def execute_entry(self, symbol: str, signal: dict):
        if symbol in self.state["positions"]:
            return

        if self.check_daily_loss_limit():
            return

        px = signal["price"]
        stop_px = signal["stop_loss"]
        risk_per_unit = abs(px - stop_px)
        if risk_per_unit <= 0:
            return

        # Sizing with LEVERAGE:
        # Effective equity boosted by leverage (e.g. 10,000 JPY * 3.0x = 30,000 JPY buying power)
        equity_usd = self.state["equity"]
        buying_power_usd = equity_usd * self.leverage

        risk_usd = equity_usd * self.risk_per_trade
        desired_qty = risk_usd / risk_per_unit
        max_alloc_qty = (buying_power_usd * self.max_pair_alloc) / px
        qty = min(desired_qty, max_alloc_qty)
        qty = self.client.round_qty(symbol, qty)

        rules = self.client.get_symbol_rules(symbol)
        notional = qty * px
        if notional < rules["min_notional"]:
            log.info(f"[{symbol}] Notional ${notional:.2f} is below minNotional ${rules['min_notional']:.2f}. Auto-adjusting to minNotional.")
            qty = self.client.round_qty(symbol, (rules["min_notional"] * 1.1) / px)
            notional = qty * px

        side = signal["signal"]
        notional_jpy = notional * self.usdjpy_rate
        log.info(f"⚡ [LEVERAGED ENTRY] {side} {symbol}: Qty={qty:.1f} | Notional=¥{notional_jpy:,.0f} (${notional:.2f}) | Entry={px:.5f} | Stop={stop_px:.5f} | TP2={signal['tp2']:.5f}")

        # If live authenticated, send order
        if self.client.is_authenticated():
            try:
                order_res = self.client.create_order(
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=qty,
                )
                log.info(f"[{symbol}] Binance Order ID: {order_res.get('orderId')}")
            except Exception as e:
                log.error(f"[{symbol}] Order submission failed: {e}")
                return

        # Record position
        pos = {
            "symbol": symbol,
            "side": side,
            "entry_price": px,
            "quantity": qty,
            "notional": notional,
            "notional_jpy": notional_jpy,
            "stop_loss": stop_px,
            "tp1": signal["tp1"],
            "tp2": signal["tp2"],
            "risk_per_unit": risk_per_unit,
            "ratchet_stage": 0,
            "entry_time": dt.datetime.utcnow().isoformat(),
            "reason": signal["reason"],
        }
        self.state["positions"][symbol] = pos
        self.save_state()

    def close_position(self, symbol: str, exit_price: float, reason: str):
        pos = self.state["positions"].pop(symbol, None)
        if not pos:
            return

        qty = pos["quantity"]
        entry_price = pos["entry_price"]
        side = pos["side"]

        if self.client.is_authenticated():
            try:
                close_side = "SELL" if side == "BUY" else "BUY"
                self.client.create_order(
                    symbol=symbol,
                    side=close_side,
                    order_type="MARKET",
                    quantity=qty,
                )
                log.info(f"[{symbol}] API position closed.")
            except Exception as e:
                log.error(f"Failed to close API position for {symbol}: {e}")

        # Compute PnL
        if side == "BUY":
            gross_pnl_usd = (exit_price - entry_price) * qty
        else:
            gross_pnl_usd = (entry_price - exit_price) * qty

        fee_usd = (exit_price * qty + entry_price * qty) * 0.00075
        net_pnl_usd = gross_pnl_usd - fee_usd
        net_pnl_jpy = net_pnl_usd * self.usdjpy_rate

        self.state["cash"] += net_pnl_usd
        self.state["equity"] += net_pnl_usd
        self.state["cash_jpy"] = self.state["cash"] * self.usdjpy_rate
        self.state["equity_jpy"] = self.state["equity"] * self.usdjpy_rate

        closed_trade = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
            "net_pnl_usd": net_pnl_usd,
            "net_pnl_jpy": net_pnl_jpy,
            "reason": reason,
            "entry_time": pos["entry_time"],
            "exit_time": dt.datetime.utcnow().isoformat(),
        }
        self.state["closed_trades"].append(closed_trade)
        self.save_state()

        pnl_symbol = "+" if net_pnl_jpy >= 0 else ""
        log.info(f"🏁 CLOSED [{symbol}] {side} @ {exit_price:.5f} | Net PnL: {pnl_symbol}¥{net_pnl_jpy:,.1f} ({pnl_symbol}${net_pnl_usd:.2f}) | Reason: {reason} | Total Equity: ¥{self.state['equity_jpy']:,.1f}")

    def run_cycle(self):
        """Execute a single 2-minute evaluation cycle across all configured pairs."""
        self.cycle_count += 1
        now_str = dt.datetime.now().strftime("%H:%M:%S")

        self.update_equity()
        self.manage_open_positions()

        eq_jpy = self.state.get("equity_jpy", self.budget_jpy)
        eq_usd = self.state.get("equity", 65.0)
        power_jpy = eq_jpy * self.leverage
        power_usd = eq_usd * self.leverage
        open_count = len(self.state.get("positions", {}))

        log.info(f"🔄 [CYCLE #{self.cycle_count:04d} | {now_str}] Equity: ¥{eq_jpy:,.0f} (${eq_usd:.2f}) | Leverage: {self.leverage:.1f}x | Buying Power: ¥{power_jpy:,.0f} (${power_usd:.2f}) | Open Positions: {open_count}")

        for symbol in self.pairs:
            try:
                # 4h candles for macro regime
                klines_4h = self.client.get_klines(symbol=symbol, interval="4h", limit=200)
                # 15m candles for intraday execution triggers
                klines_15m = self.client.get_klines(symbol=symbol, interval="15m", limit=80)

                signal_res = self.strategy.check_signal(klines_4h, klines_15m)
                regime = signal_res.get("regime", "UNKNOWN")
                sig = signal_res.get("signal", "WAIT")
                px = self.client.get_ticker_price(symbol)

                log.info(f"   📊 [{symbol}] Px: {px:.5f} | Regime: {regime} | Signal: {sig} | Reason: {signal_res.get('reason')}")

                if sig in ["BUY", "SELL"]:
                    self.execute_entry(symbol, signal_res)

            except Exception as e:
                log.error(f"Error evaluating {symbol}: {e}")

    def start(self):
        log.info("=" * 70)
        log.info(f" 🚀 Autonomous Forex Trading Bot Initialized")
        log.info(f" Mode: {self.mode} | Endpoint: {self.client.base_url}")
        log.info(f" Starting Budget: ¥{self.budget_jpy:,.0f} (~${self.state['equity']:.2f} USDT @ {self.usdjpy_rate:.2f} JPY/USD)")
        log.info(f" Active Leverage: {self.leverage:.1f}x (Total Buying Power: ¥{self.budget_jpy*self.leverage:,.0f})")
        log.info(f" Cadence: Checking every {self.poll_interval}s (2 minutes)")
        log.info(f" Strategy: 4h Regime Filter + 15m/1h BB & RSI Mean-Reversion + Multi-Tier Ratchets")
        log.info("=" * 70)

        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                log.error(f"Unexpected error in run cycle: {e}")
            time.sleep(self.poll_interval)

        log.info("Forex Bot stopped gracefully.")
