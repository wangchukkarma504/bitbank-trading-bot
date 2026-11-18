"""Control server and web dashboard for the Bitbank trading bot.

- runs the trading engine (engine.py) in a background thread, with pause / resume / emergency stop;
- JSON API: /api/status, /api/candles, /api/pause, /api/resume, /api/emergency-stop, /api/close-position,
  /api/config, /api/tax, /health;
- the web dashboard at / (dashboard_html.py), behind an optional login.
"""

import argparse
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import uvicorn

from tradingbot.bitbank import Bitbank, BitbankError
from tradingbot.dashboard_html import DASHBOARD_HTML, render_login_html
from tradingbot.engine import Engine, PAIRS, Settings, floor_amount, fmt_amount
from tradingbot.tax_japan import (
    build_tax_report,
    load_tax_profile,
    render_tax_csv,
    save_tax_profile,
)


logger = logging.getLogger("FastAPIServer")


def _load_env_file(env_path: str = ".env") -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _save_env_keys(env_path: str, api_key: str, api_secret: str) -> None:
    """Persist API_KEY and SECRET_KEY to .env without exposing them in logs."""
    lines: List[str] = []
    if env_path and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    updated = {"API_KEY": False, "SECRET_KEY": False}
    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("API_KEY="):
            new_lines.append(f"API_KEY={api_key}")
            updated["API_KEY"] = True
        elif stripped.startswith("SECRET_KEY="):
            new_lines.append(f"SECRET_KEY={api_secret}")
            updated["SECRET_KEY"] = True
        else:
            new_lines.append(line)
    if not updated["API_KEY"]:
        new_lines.append(f"API_KEY={api_key}")
    if not updated["SECRET_KEY"]:
        new_lines.append(f"SECRET_KEY={api_secret}")
    if env_path:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")


def _remove_env_keys(env_path: str) -> None:
    """Remove Bitbank API credentials from .env."""
    if not env_path or not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    filtered = [
        line for line in lines
        if not line.strip().startswith(("API_KEY=", "SECRET_KEY=", "BITBANK_API_KEY=", "BITBANK_API_SECRET="))
    ]
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(("\n".join(filtered) + "\n") if filtered else "")


class ConfigRequest(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    capital_limit_jpy: Optional[float] = None
    baseline_jpy: Optional[float] = None
    goal_target_jpy: Optional[float] = None
    allow_shorts: Optional[bool] = None
    force_profit_close_jpy: Optional[float] = None
    allow_counter_trend_longs: Optional[bool] = None


class ClosePositionRequest(BaseModel):
    pair: str
    position_side: Optional[str] = None


class TaxProfileRequest(BaseModel):
    tax_year: Optional[int] = None
    employment_type: Optional[str] = None
    annual_salary_jpy: Optional[float] = None
    other_misc_income_jpy: Optional[float] = None
    filing_threshold_jpy: Optional[float] = None
    taxpayer_name: Optional[str] = None
    tax_office: Optional[str] = None


class BotController:
    """Thread-safe wrapper around the trading engine: settings, equity history, pause and emergency stop."""

    MAX_HISTORY_POINTS = 500
    HISTORY_EVERY_SEC = 300.0

    def __init__(
        self,
        engine: Engine,
        history_path: str = "equity_history.json",
        config_path: str = "bot_config.json",
        env_path: str = ".env",
        tax_profile_path: str = "tax_profile.json",
        trade_log_path: str = "trade_audit_log.json",
        auto_start: bool = True,
    ):
        self.engine = engine
        self.history_path = history_path
        self.config_path = config_path
        self.env_path = env_path
        self.tax_profile_path = tax_profile_path
        self.trade_log_path = trade_log_path
        self.lock = threading.Lock()
        self.running: bool = auto_start
        self.emergency_stopped: bool = False
        self.last_error: Optional[str] = None
        self.last_tick_ts: float = 0.0
        self.last_emergency_report: Optional[Dict[str, Any]] = None
        self.goal_target_jpy: Optional[float] = None
        self.equity_history: List[Dict[str, Any]] = []
        self.trade_audit: List[Dict[str, Any]] = []
        self._last_sync_ts: float = 0.0
        self._last_history_ts: float = 0.0
        self._candle_cache: Dict[Any, Any] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_history()
        self._load_config()
        self._load_trade_audit()
        self.engine.entries_enabled = self.running and not self.emergency_stopped

    def _load_config(self) -> None:
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            s = self.engine.settings

            def positive(key: str) -> Optional[float]:
                v = cfg.get(key)
                return float(v) if v is not None and float(v) > 0 else None

            s.capital_limit_jpy = positive("capital_limit_jpy")
            s.equity_floor_jpy = positive("equity_floor_jpy")
            manual_stop = positive("manual_stop_pct")
            if manual_stop and manual_stop <= 25.0:
                s.manual_stop_pct = manual_stop / 100.0
            if positive("baseline_jpy"):
                s.baseline_jpy = positive("baseline_jpy")
            self.goal_target_jpy = positive("goal_target_jpy")
            risk, slots = positive("risk_per_trade_pct"), positive("max_positions")
            if risk and risk <= 5.0:
                self.engine.params = replace(self.engine.params, risk_per_trade=risk / 100.0)
            if slots and slots <= 5:
                # 1.95x is all the exchange lends: with more than three slots each position must be smaller
                self.engine.params = replace(self.engine.params, max_positions=int(slots),
                                             max_notional=min(self.engine.params.max_notional, round(1.95 / int(slots), 4)))
            # A pause or an emergency stop survives a restart: trading resumes only when the operator says so
            if cfg.get("emergency_stopped"):
                self.emergency_stopped, self.running = True, False
            elif cfg.get("trading_enabled") is False:
                self.running = False
        except Exception as e:
            logger.warning(f"Could not load bot config: {e}")

    def _save_config(self) -> None:
        if not self.config_path:
            return
        try:
            s = self.engine.settings
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "baseline_jpy": s.baseline_jpy,
                        "capital_limit_jpy": s.capital_limit_jpy,
                        "goal_target_jpy": self.goal_target_jpy,
                        "equity_floor_jpy": s.equity_floor_jpy,
                        "manual_stop_pct": round(s.manual_stop_pct * 100.0, 3),
                        "risk_per_trade_pct": round(self.engine.params.risk_per_trade * 100.0, 3),
                        "max_positions": self.engine.params.max_positions,
                        "trading_enabled": self.running,
                        "emergency_stopped": self.emergency_stopped,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"Could not save bot config: {e}")

    def update_config(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        capital_limit_jpy: Optional[float] = None,
        baseline_jpy: Optional[float] = None,
        goal_target_jpy: Optional[float] = None,
        **_ignored: Any,
    ) -> Dict[str, Any]:
        """Update the Bitbank API credentials, capital limit, baseline and/or goal while running."""
        changed: List[str] = []
        s = self.engine.settings
        with self.lock:
            if api_key and api_secret:
                key_clean = api_key.strip()
                sec_clean = api_secret.strip()
                os.environ["API_KEY"] = key_clean
                os.environ["SECRET_KEY"] = sec_clean
                _save_env_keys(self.env_path, key_clean, sec_clean)
                self.engine.client = Bitbank(key=key_clean, secret=sec_clean)
                changed.append("api_credentials")

            if capital_limit_jpy is not None:
                s.capital_limit_jpy = float(capital_limit_jpy) if capital_limit_jpy > 0 else None
                if s.capital_limit_jpy and baseline_jpy is None:
                    s.baseline_jpy = s.capital_limit_jpy
                changed.append("capital_limit_jpy")

            if baseline_jpy is not None and baseline_jpy > 0:
                s.baseline_jpy = float(baseline_jpy)
                changed.append("baseline_jpy")

            if goal_target_jpy is not None:
                self.goal_target_jpy = float(goal_target_jpy) if goal_target_jpy > 0 else None
                changed.append("goal_target_jpy")

            if changed:
                self._save_config()

        return {
            "ok": True,
            "updated": changed,
            "capital_limit_jpy": s.capital_limit_jpy,
            "baseline_jpy": s.baseline_jpy,
            "goal_target_jpy": self.goal_target_jpy,
        }

    def remove_api_key(self) -> Dict[str, Any]:
        """Remove stored Bitbank API credentials and clear client keys."""
        with self.lock:
            for env_k in ("API_KEY", "SECRET_KEY", "BITBANK_API_KEY", "BITBANK_API_SECRET"):
                os.environ.pop(env_k, None)
            _remove_env_keys(self.env_path)
            new_client = Bitbank(key="", secret="")
            new_client.key = None
            new_client.secret = None
            self.engine.client = new_client
        return {"ok": True, "api_key_configured": False}

    def _load_history(self) -> None:
        if not self.history_path or not os.path.exists(self.history_path):
            return
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.equity_history = data[-self.MAX_HISTORY_POINTS:]
        except Exception as e:
            logger.warning(f"Could not load equity history: {e}")

    def _save_history(self) -> None:
        if not self.history_path:
            return
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.equity_history[-self.MAX_HISTORY_POINTS:], f)
        except Exception as e:
            logger.warning(f"Could not save equity history: {e}")

    def _load_trade_audit(self) -> None:
        if not self.trade_log_path or not os.path.exists(self.trade_log_path):
            return
        try:
            with open(self.trade_log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.trade_audit = data[-300:]
        except Exception as e:
            logger.warning(f"Could not load trade audit log: {e}")

    def _save_trade_audit(self) -> None:
        if not self.trade_log_path:
            return
        try:
            with open(self.trade_log_path, "w", encoding="utf-8") as f:
                json.dump(self.trade_audit[-300:], f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save trade audit log: {e}")

    def sync_exchange_trades(self) -> int:
        """Sync recent Bitbank fills (bot and manual) into the local audit log."""
        with self.lock:
            client = self.engine.client
            dry_run = self.engine.dry_run
            bot_closes = [(str(j.get("pair")), float(j.get("timestamp") or 0.0)) for j in self.engine.journal]
        if dry_run or client is None or not getattr(client, "key", None):
            return 0
        try:
            res = client._get("/user/spot/trade_history", {"count": "100", "order": "desc"})
            trades = res.get("trades", []) if isinstance(res, dict) else []
        except Exception as e:
            logger.debug(f"Trade history sync skipped: {e}")
            return 0
        if not isinstance(trades, list) or not trades:
            return 0

        jst = timezone(timedelta(hours=9))
        added = 0
        with self.lock:
            seen_ids = {str(x.get("trade_id")) for x in self.trade_audit if x.get("trade_id") is not None}
            for t in reversed(trades):
                tid = t.get("trade_id")
                if tid is None or str(tid) in seen_ids:
                    continue
                pair = str(t.get("pair") or "")
                side = str(t.get("side") or "")
                pos_side = t.get("position_side")
                amt = float(t.get("amount") or 0.0)
                px = float(t.get("price") or 0.0)
                fee_q = float(t.get("fee_occurred_amount_quote") or t.get("fee_amount_quote") or 0.0)
                interest = float(t.get("interest") or 0.0)
                raw_pnl = float(t.get("profit_loss") or 0.0)
                is_close = (
                    (pos_side == "short" and side == "buy")
                    or (pos_side == "long" and side == "sell")
                    or abs(raw_pnl) > 0.01
                )
                # profit_loss on a closing margin fill is already net of the entry and exit fees
                net_pnl = round(raw_pnl - interest, 2) if (pos_side and is_close) else 0.0
                ts_ms = int(t.get("executed_at") or 0)
                ts_sec = int(ts_ms / 1000) if ts_ms > 0 else int(time.time())
                is_bot = any(bp == pair and abs(bts - ts_sec) <= 90 for bp, bts in bot_closes)
                self.trade_audit.append({
                    "trade_id": tid,
                    "ts": ts_sec,
                    "time_jst": datetime.fromtimestamp(ts_sec, tz=jst).strftime("%Y-%m-%d %H:%M:%S"),
                    "pair": pair,
                    "side": f"{side} ({pos_side})" if pos_side else f"{side} (spot)",
                    "raw_side": side,
                    "position_side": pos_side,
                    "is_close": bool(is_close),
                    "amount": amt,
                    "price_jpy": px,
                    "gross_pnl_jpy": round(raw_pnl, 2),
                    "fee_jpy": round(fee_q, 2),
                    "interest_jpy": round(interest, 2),
                    "net_pnl_jpy": net_pnl,
                    "source": "bot" if is_bot else "manual",
                })
                seen_ids.add(str(tid))
                added += 1
            if added > 0:
                self.trade_audit.sort(key=lambda r: int(r.get("ts") or 0))
                self.trade_audit = self.trade_audit[-300:]
                self._save_trade_audit()
            self._last_sync_ts = time.time()
        return added

    def start_loop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="EngineLoop")
        self._thread.start()

    def stop_loop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _run_loop(self) -> None:
        self.sync_exchange_trades()
        while not self._stop_event.is_set():
            # The engine ticks even while paused or stopped: it then opens nothing new, but open positions
            # keep their exchange stops (and the bot's own positions keep trailing).
            self.engine.entries_enabled = self.running and not self.emergency_stopped
            try:
                res = self.engine.tick()
                now = time.time()
                with self.lock:
                    self.last_tick_ts = now
                    self.last_error = self.engine.last_step_error
                    if now - self._last_history_ts >= self.HISTORY_EVERY_SEC:
                        self._last_history_ts = now
                        self.equity_history.append({"ts": int(now), "equity": round(float(res["equity_jpy"]), 2)})
                        self.equity_history = self.equity_history[-self.MAX_HISTORY_POINTS:]
                        self._save_history()
                if now - self._last_sync_ts >= 60.0:
                    self.sync_exchange_trades()
            except Exception as e:
                with self.lock:
                    repeated = self.last_error == str(e)
                    self.last_error = str(e)
                if not repeated:
                    logger.error(f"Engine tick failed: {e}", exc_info=not isinstance(e, BitbankError))
            self._stop_event.wait(self.engine.TICK_INTERVAL_SEC)

    def pause(self) -> Dict[str, Any]:
        with self.lock:
            self.running = False
            self._save_config()
        return {"status": "PAUSED", "running": self.running}

    def resume(self) -> Dict[str, Any]:
        with self.lock:
            self.emergency_stopped = False
            self.running = True
            self._save_config()
        return {"status": "RUNNING", "running": self.running}

    def emergency_stop_all(self) -> Dict[str, Any]:
        """Halt new entries, cancel every active order and close every open position at market."""
        with self.lock:
            self.running = False
            self.emergency_stopped = True
            self._save_config()
        self.engine.entries_enabled = False

        cancelled: List[Dict[str, Any]] = []
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        client = self.engine.client

        if not self.engine.dry_run and client is not None:
            try:
                for o in client._get("/user/spot/active_orders").get("orders", []):
                    oid, pair = o.get("order_id"), o.get("pair")
                    if oid is None or not pair:
                        continue
                    try:
                        client.cancel(pair, oid)
                        cancelled.append({"pair": pair, "order_id": oid, "type": o.get("type")})
                    except Exception as e:
                        errors.append(f"Cancel error on {pair} #{oid}: {e}")
            except Exception as e:
                errors.append(f"Could not list active orders: {e}")
            closed_now, close_errors = self._close_margin(client)
            closed += closed_now
            errors += close_errors
            closed_now, close_errors = self._sell_spot(client, list(PAIRS))
            closed += closed_now
            errors += close_errors
            self.engine.entries.clear()

        report = {
            "status": "EMERGENCY_STOPPED",
            "timestamp": int(time.time()),
            "cancelled_orders": cancelled,
            "closed_positions": closed,
            "errors": errors,
        }
        with self.lock:
            self.last_emergency_report = report
        logger.critical(f"EMERGENCY STOP ALL EXECUTED: {report}")
        return report

    @staticmethod
    def _close_margin(client: Any, pair: Optional[str] = None, side: Optional[str] = None):
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        try:
            for p in client.margin_positions():
                if float(p.get("open_amount", 0.0)) <= 0.00005:
                    continue
                if (pair and p.get("pair") != pair) or (side and p.get("position_side") != side):
                    continue
                p_side = p["position_side"]
                try:
                    res = client.order(p["pair"], side="buy" if p_side == "short" else "sell",
                                       amount=p["open_amount"], type_="market", position_side=p_side)
                    closed.append({"pair": p["pair"], "side": p_side, "amount": p["open_amount"],
                                   "order_id": res.get("order_id")})
                except Exception as e:
                    errors.append(f"Close error on {p['pair']} {p_side}: {e}")
        except Exception as e:
            errors.append(f"Could not read margin positions: {e}")
        return closed, errors

    @staticmethod
    def _sell_spot(client: Any, pairs: List[str]):
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        try:
            for a in client._get("/user/assets").get("assets", []):
                pair = f"{a.get('asset', '')}_jpy"
                free_amt = float(a.get("free_amount", 0.0))
                if pair not in pairs or free_amt <= 0.0001:
                    continue
                last_px = float((client.ticker(pair) or {}).get("last", 0.0))
                amount = floor_amount(pair, free_amt)
                if amount * last_px >= 500.0:
                    res = client.order(pair, side="sell", amount=fmt_amount(pair, amount), type_="market")
                    closed.append({"pair": pair, "side": "spot", "amount": fmt_amount(pair, amount),
                                   "order_id": res.get("order_id")})
        except Exception as e:
            errors.append(f"Spot close error: {e}")
        return closed, errors

    def close_position(self, pair: str, position_side: Optional[str] = None) -> Dict[str, Any]:
        """Cancel active orders for a pair and market-close the open position."""
        if pair not in PAIRS:
            raise HTTPException(status_code=400, detail=f"Unsupported pair: {pair}")

        cancelled: List[Dict[str, Any]] = []
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        client = self.engine.client

        if not self.engine.dry_run and client is not None:
            try:
                for o in client._get("/user/spot/active_orders", {"pair": pair}).get("orders", []):
                    oid = o.get("order_id")
                    if oid is not None:
                        client.cancel(pair, oid)
                        cancelled.append({"pair": pair, "order_id": oid, "type": o.get("type")})
            except Exception as e:
                errors.append(f"Cancel error on {pair}: {e}")
            side = position_side if position_side in ("long", "short") else None
            closed, close_errors = self._close_margin(client, pair, side)
            errors += close_errors
            if not closed and position_side in (None, "spot", "long"):
                closed, close_errors = self._sell_spot(client, [pair])
                errors += close_errors
            self.engine.entries.pop(pair, None)

        logger.warning(f"MANUAL CLOSE EXECUTED on {pair} ({position_side}): closed={closed}, cancelled={cancelled}, errors={errors}")
        return {
            "status": "CLOSED",
            "pair": pair,
            "timestamp": int(time.time()),
            "cancelled_orders": cancelled,
            "closed_positions": closed,
            "errors": errors,
        }

    def get_status(self) -> Dict[str, Any]:
        for _ in range(3):
            try:
                return self._build_status()
            except RuntimeError:      # the engine thread changed a dict while it was being read: read again
                time.sleep(0.05)
        return self._build_status()

    def _build_status(self) -> Dict[str, Any]:
        eng = self.engine
        acct = eng.account
        s = eng.settings
        baseline = s.baseline_jpy
        equity = acct.equity if acct else baseline
        free_cash = acct.free_jpy if acct else baseline
        total_pnl = equity - baseline
        total_pnl_pct = (total_pnl / baseline * 100.0) if baseline > 0 else 0.0

        orders = list(acct.orders) if acct else []
        active_stops = [o for o in orders if o.get("type") == "stop"]
        open_positions: List[Dict[str, Any]] = []
        in_trade_pnl = in_trade_notional = in_trade_est_net = 0.0
        for (pair, side), pos in (acct.positions.items() if acct else []):
            notional = pos.amount * pos.last
            est_fee = round(notional * 0.0012, 2)
            est_net = round(pos.upnl - est_fee, 2)
            row: Dict[str, Any] = {
                "pair": pair,
                "position_side": side,
                "open_amount": f"{pos.amount:.4f}",
                "amount": pos.amount,
                "average_price": f"{pos.avg:.4f}",
                "avg_price": pos.avg,
                "last_price": pos.last,
                "unrealized_pnl_jpy": pos.upnl,
                "notional_jpy": notional,
                "est_close_fee_jpy": est_fee,
                "est_net_close_pnl_jpy": est_net,
                "owner": "bot" if (side == "long" and pair in eng.positions) else "manual",
            }
            close_side = "sell" if side == "long" else "buy"
            trigs = [float(o.get("trigger_price") or 0.0) for o in active_stops
                     if o.get("pair") == pair and o.get("position_side") == side and o.get("side") == close_side]
            if trigs and pos.avg > 0:
                trig = max(trigs) if side == "long" else min(trigs)
                gross = pos.amount * ((trig - pos.avg) if side == "long" else (pos.avg - trig))
                row["stop_trigger_price"] = trig
                row["est_stop_pnl_jpy"] = round(gross - pos.amount * trig * 0.0012, 2)
            open_positions.append(row)
            in_trade_pnl += pos.upnl
            in_trade_notional += notional
            in_trade_est_net += est_net
        in_trade_pct = (in_trade_pnl / in_trade_notional * 100.0) if in_trade_notional > 0 else 0.0

        # Resting limit orders (the bot's maker buy, or the operator's own) with the stop they will get
        pending_orders = []
        for o in orders:
            try:
                if o.get("type") != "limit":
                    continue
                o_px = float(o.get("price") or 0.0)
                o_amt = _order_amount(o)
                if o_px <= 0 or o_amt <= 0:
                    continue
                is_short = o.get("side") == "sell"
                entry = eng.entries.get(o.get("pair")) if not is_short else None
                if entry is not None and entry.get("order_id") == o.get("order_id"):
                    o_stop = float(entry["stop"])
                else:
                    o_stop = o_px * (1.0 + s.manual_stop_pct) if is_short else o_px * (1.0 - s.manual_stop_pct)
                pending_orders.append({
                    "pair": o.get("pair"),
                    "order_id": o.get("order_id"),
                    "side": "short" if is_short else "long",
                    "price": o_px,
                    "amount": o_amt,
                    "planned_stop_price": round(o_stop, 4),
                    "planned_take_profit_price": None,
                    "est_stop_pnl_jpy": round(-o_amt * abs(o_stop - o_px) - o_amt * o_stop * 0.0012, 2),
                    "est_tp_pnl_jpy": None,
                })
            except (TypeError, ValueError):
                continue

        if 95000.0 <= baseline <= 105000.0:
            t2x, t5x, t10x = 200000.0, 500000.0, 1000000.0
        elif baseline >= 10000.0:
            t2x = float(round(baseline * 2.0, -3))
            t5x = float(round(baseline * 5.0, -3))
            t10x = float(round(baseline * 10.0, -3))
        else:
            t2x, t5x, t10x = 20000.0, 50000.0, 100000.0

        if self.goal_target_jpy is not None and self.goal_target_jpy > 0:
            t2x = float(self.goal_target_jpy)

        def _ms(target: float) -> Dict[str, Any]:
            req = max(1.0, target - baseline)
            pct = min(100.0, max(0.0, (equity - baseline) / req * 100.0))
            return {"target": target, "pct": round(pct, 1), "remaining": round(max(0.0, target - equity), 2)}

        journal = list(eng.journal)
        lessons = [
            {
                "pair": j.get("pair"),
                "side": j.get("side", "long"),
                "pnl_jpy": j.get("pnl_jpy", 0.0),
                "cause": f"{float(j.get('r') or 0.0):+.2f}R in {j.get('days', 0)} days",
                "fix": j.get("reason", ""),
                "is_loss": float(j.get("pnl_jpy") or 0.0) < 0,
            }
            for j in journal[-8:]
        ]
        trade_history = [
            {
                "pair": j.get("pair"),
                "side": j.get("side", "long"),
                "pnl_jpy": round(float(j.get("pnl_jpy") or 0.0), 2),
                "pnl_pct": round(float(j.get("r") or 0.0) * eng.params.risk_per_trade * 100.0, 2),
                "equity_after": round(float(j.get("equity_after") or equity), 2),
                "is_loss": float(j.get("pnl_jpy") or 0.0) < 0,
                "ts": int(float(j.get("timestamp") or 0.0)),
                "source": "bot",
            }
            for j in journal[-16:]
        ]

        with self.lock:
            audit_copy = list(self.trade_audit)

        for row in audit_copy:
            if row.get("source") != "manual" or not row.get("position_side"):
                continue
            # Ignore opening margin fills (which only carry maker rebates with gross_pnl == 0)
            gross_pnl = float(row.get("gross_pnl_jpy") or 0.0)
            if not row.get("is_close") and abs(gross_pnl) < 0.01:
                continue
            pnl = gross_pnl - float(row.get("interest_jpy") or 0.0)   # recomputed: older rows took the fee off twice
            if abs(pnl) < 0.01:
                continue
            ts_row = int(row.get("ts") or 0)
            pair_row = str(row.get("pair") or "")
            existing = next(
                (h for h in trade_history if h["pair"] == pair_row and abs(h["ts"] - ts_row) <= 90),
                None,
            )
            if existing is not None:
                # Merge partial fills of the same manual close rather than dropping the rest
                if existing.get("source") == "manual":
                    existing["pnl_jpy"] = round(float(existing["pnl_jpy"]) + pnl, 2)
                    existing["is_loss"] = existing["pnl_jpy"] < 0
                continue
            trade_history.append({
                "pair": pair_row,
                "side": str(row.get("position_side") or row.get("side") or ""),
                "pnl_jpy": round(pnl, 2),
                "pnl_pct": 0.0,
                "equity_after": round(equity, 2),
                "is_loss": pnl < 0,
                "ts": ts_row,
                "source": "manual",
            })
        trade_history.sort(key=lambda x: int(x.get("ts") or 0))
        trade_history = trade_history[-16:]

        with self.lock:
            state_label = (
                "EMERGENCY_STOPPED"
                if self.emergency_stopped
                else ("RUNNING" if self.running else "PAUSED")
            )
            history = list(self.equity_history)
            err = self.last_error
            em_report = self.last_emergency_report

        raw_key = getattr(eng.client, "key", None) or os.environ.get("API_KEY") or ""
        api_key_masked = ("****" + raw_key[-4:]) if len(raw_key) >= 4 else ("SET" if raw_key else "NOT SET")
        p = eng.params
        days = p.channel_bars * 4 // 24

        return {
            "state": state_label,
            "mode": eng.mode.upper(),
            "tick_count": eng.tick_count,
            "api_key_configured": bool(raw_key),
            "api_key_masked": api_key_masked,
            "capital_limit_jpy": s.capital_limit_jpy,
            "baseline_jpy": round(baseline, 2),
            "goal_target_jpy": self.goal_target_jpy,
            "equity_jpy": round(equity, 2),
            "free_cash_jpy": round(free_cash, 2),
            "buying_power_jpy": round(equity * p.max_notional * p.max_positions, 2),
            "total_pnl_jpy": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "in_trade_pnl_jpy": round(in_trade_pnl, 2),
            "in_trade_pnl_pct": round(in_trade_pct, 2),
            "in_trade_est_net_pnl_jpy": round(in_trade_est_net, 2),
            "milestones": {"x2": _ms(t2x), "x5": _ms(t5x), "x10": _ms(t10x)},
            "open_positions": open_positions,
            "active_stops": active_stops,
            "pending_orders": pending_orders,
            "signals": eng.watchlist(),
            "rule": {
                "summary": (f"Buys a coin when a 4-hour candle closes above its {days}-day high. The stop starts "
                            f"{p.atr_mult:g} ATR below the entry and follows the price up; it never moves down. "
                            f"Each trade risks {p.risk_per_trade * 100:g}% of equity, with at most {p.max_positions} "
                            f"positions. Long only; there is no profit target."),
                "risk_per_trade_pct": round(p.risk_per_trade * 100.0, 3),
                "max_positions": p.max_positions,
                "channel_days": days,
                "atr_mult": p.atr_mult,
            },
            "entries_enabled": bool(eng.entries_enabled),
            "equity_floor_jpy": s.equity_floor_jpy,
            "equity_floor_hit": bool(eng.floor_hit),
            "circuit_breaker_sec": 0,
            "cooldown_sec": 0,
            "daily_loss_halted": False,
            "news_override": None,
            "macro": None,
            "lessons": list(reversed(lessons)),
            "trade_history": trade_history,
            "equity_history": history,
            "last_error": err,
            "last_emergency_report": em_report,
        }

    def get_candles(self, pair: str = "btc_jpy", tf: str = "15min", limit: int = 200) -> Dict[str, Any]:
        """Fetch OHLCV candles from Bitbank's public API for the live chart."""
        valid_tfs = {"5min", "15min", "1hour", "4hour"}
        tf_clean = tf if tf in valid_tfs else "15min"
        pair_clean = pair if pair in PAIRS else "btc_jpy"
        now_utc = datetime.now(timezone.utc)
        if tf_clean == "4hour":
            periods = [str(now_utc.year - 1), str(now_utc.year)]
        else:
            days_back = {"5min": 1, "15min": 3, "1hour": 9}.get(tf_clean, 1)
            periods = [(now_utc - timedelta(days=d)).strftime("%Y%m%d") for d in range(days_back, -1, -1)]
        raw_rows: List[Any] = []
        try:
            for period in periods:
                # Finished periods never change; only the current one is refetched (every 10 seconds at most)
                ttl = 10.0 if period == periods[-1] else 6 * 3600.0
                key = (pair_clean, tf_clean, period)
                hit = self._candle_cache.get(key)
                if hit is None or time.time() - hit[0] > ttl:
                    try:
                        hit = (time.time(), self.engine.client.candles(pair_clean, tf_clean, period) or [])
                        self._candle_cache[key] = hit
                    except Exception:
                        hit = hit or (0.0, [])
                raw_rows.extend(hit[1])
            candles = []
            for row in raw_rows[-max(10, min(limit, 200)):]:
                if len(row) >= 6:
                    candles.append({
                        "o": float(row[0]),
                        "h": float(row[1]),
                        "l": float(row[2]),
                        "c": float(row[3]),
                        "v": float(row[4]),
                        "t": int(row[5]),
                    })
            return {"pair": pair_clean, "tf": tf_clean, "candles": candles}
        except Exception as e:
            return {"pair": pair_clean, "tf": tf_clean, "candles": [], "error": str(e)}

    def get_tax_report(self, year: Optional[int] = None) -> Dict[str, Any]:
        """Build the Japan Crypto Tax (確定申告 / 雑所得) report for the selected year."""
        with self.lock:
            prof = load_tax_profile(self.tax_profile_path)
            if year is not None and year > 2000:
                prof.tax_year = int(year)
            client = self.engine.client
            lessons = list(self.engine.journal)
            cache_path = f"tax_cache_{prof.tax_year}.json" if self.tax_profile_path else ""
        return build_tax_report(client, prof, fallback_lessons=lessons, cache_path=cache_path)

    def update_tax_profile(
        self,
        tax_year: Optional[int] = None,
        employment_type: Optional[str] = None,
        annual_salary_jpy: Optional[float] = None,
        other_misc_income_jpy: Optional[float] = None,
        filing_threshold_jpy: Optional[float] = None,
        taxpayer_name: Optional[str] = None,
        tax_office: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update and persist Japan tax details, returning the recalculated tax report."""
        with self.lock:
            prof = load_tax_profile(self.tax_profile_path)
            if tax_year is not None and int(tax_year) > 2000:
                prof.tax_year = int(tax_year)
            if employment_type in ("salary", "other"):
                prof.employment_type = str(employment_type)
            if annual_salary_jpy is not None and float(annual_salary_jpy) >= 0:
                prof.annual_salary_jpy = float(annual_salary_jpy)
            if other_misc_income_jpy is not None and float(other_misc_income_jpy) >= 0:
                prof.other_misc_income_jpy = float(other_misc_income_jpy)
            if filing_threshold_jpy is not None and float(filing_threshold_jpy) >= 0:
                prof.filing_threshold_jpy = float(filing_threshold_jpy)
            if taxpayer_name is not None:
                prof.taxpayer_name = taxpayer_name.strip()[:80]
            if tax_office is not None:
                prof.tax_office = tax_office.strip()[:80]
            save_tax_profile(prof, self.tax_profile_path)
            client = self.engine.client
            lessons = list(self.engine.journal)
            cache_path = f"tax_cache_{prof.tax_year}.json" if self.tax_profile_path else ""
        return build_tax_report(client, prof, fallback_lessons=lessons, cache_path=cache_path)


def _order_amount(order: Dict[str, Any]) -> float:
    return float(order.get("remaining_amount") or order.get("start_amount") or order.get("amount") or 0.0)


# DASHBOARD_HTML imported from tradingbot.dashboard_html


_SESSION_COOKIE = "bb_session"
_SESSION_TTL_SEC = 7 * 86400


def _sign_session(user: str, password: str, exp: int) -> str:
    payload = f"{user}:{exp}"
    sig = hmac.new(password.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _verify_session(token: str, expected_user: str, expected_pass: str) -> bool:
    if not token or "." not in token:
        return False
    exp_str, sig = token.split(".", 1)
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    expected_sig = _sign_session(expected_user, expected_pass, exp).split(".", 1)[1]
    return secrets.compare_digest(sig, expected_sig)


def create_app(controller: BotController) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        controller.start_loop()
        try:
            yield
        finally:
            controller.stop_loop()

    app = FastAPI(title="Bitbank Autonomous Trading API", lifespan=lifespan)
    security = HTTPBasic(auto_error=False)

    def _auth_config() -> tuple[str, str]:
        expected_pass = os.environ.get("DASHBOARD_PASS", "").strip()
        expected_user = os.environ.get("DASHBOARD_USER", "admin").strip() or "admin"
        return expected_user, expected_pass

    def _is_authenticated(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = None,
    ) -> bool:
        expected_user, expected_pass = _auth_config()
        if not expected_pass:
            return True
        cookie_token = request.cookies.get(_SESSION_COOKIE, "")
        if _verify_session(cookie_token, expected_user, expected_pass):
            return True
        if credentials is not None:
            user_ok = secrets.compare_digest(credentials.username.encode("utf-8"), expected_user.encode("utf-8"))
            pass_ok = secrets.compare_digest(credentials.password.encode("utf-8"), expected_pass.encode("utf-8"))
            if user_ok and pass_ok:
                return True
        return False

    def require_auth(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = Depends(security),
    ) -> None:
        if not _is_authenticated(request, credentials):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

    @app.get("/login", response_class=HTMLResponse)
    def login_page(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = Depends(security),
    ):
        if _is_authenticated(request, credentials):
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        return HTMLResponse(render_login_html())

    @app.post("/login")
    async def login_submit(request: Request):
        expected_user, expected_pass = _auth_config()
        if not expected_pass:
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

        raw = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(raw)
        username = (form.get("username", [""])[0] or "").strip()
        password = form.get("password", [""])[0] or ""

        user_ok = secrets.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
        pass_ok = secrets.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
        if not (user_ok and pass_ok):
            return HTMLResponse(render_login_html("Invalid username or password."), status_code=status.HTTP_401_UNAUTHORIZED)

        exp = int(time.time()) + _SESSION_TTL_SEC
        token = _sign_session(expected_user, expected_pass, exp)
        is_https = (request.headers.get("x-forwarded-proto", "").lower() == "https") or (request.url.scheme == "https")
        resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(
            key=_SESSION_COOKIE,
            value=token,
            max_age=_SESSION_TTL_SEC,
            httponly=True,
            samesite="lax",
            secure=is_https,
        )
        return resp

    @app.get("/logout")
    @app.post("/logout")
    def logout():
        resp = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        resp.delete_cookie(_SESSION_COOKIE)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        credentials: Optional[HTTPBasicCredentials] = Depends(security),
    ):
        if not _is_authenticated(request, credentials):
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/health")
    def health():
        return {"ok": True, "state": controller.get_status()["state"]}

    @app.get("/manifest.webmanifest")
    def pwa_manifest():
        manifest = {
            "name": "Bitbank AI Trading Desk",
            "short_name": "Bitbank Bot",
            "description": "Autonomous Bitbank Spot Long & Margin Short Trading Dashboard",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#e0f2fe",
            "theme_color": "#0f172a",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        }
        return JSONResponse(manifest, media_type="application/manifest+json")

    @app.get("/sw.js")
    def pwa_service_worker():
        sw_code = """const CACHE_NAME = 'bitbank-bot-v1';
const STATIC_ASSETS = ['/static/icon-192.png', '/static/icon-512.png', '/static/icon-180.png', '/manifest.webmanifest'];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(STATIC_ASSETS)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;
  if (STATIC_ASSETS.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
    return;
  }
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""
        return Response(content=sw_code, media_type="application/javascript")

    @app.get("/static/{filename}")
    def pwa_static_icon(filename: str):
        allowed = {"icon-180.png", "icon-192.png", "icon-512.png"}
        if filename not in allowed:
            raise HTTPException(status_code=404, detail="Not found")
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
        path = os.path.join(static_dir, filename)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Icon not found")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/status", dependencies=[Depends(require_auth)])
    def api_status():
        return JSONResponse(controller.get_status())

    @app.get("/api/candles", dependencies=[Depends(require_auth)])
    def api_candles(pair: str = "btc_jpy", tf: str = "15min"):
        return JSONResponse(controller.get_candles(pair=pair, tf=tf))

    @app.post("/api/pause", dependencies=[Depends(require_auth)])
    def api_pause():
        return JSONResponse(controller.pause())

    @app.post("/api/resume", dependencies=[Depends(require_auth)])
    def api_resume():
        return JSONResponse(controller.resume())

    @app.post("/api/emergency-stop", dependencies=[Depends(require_auth)])
    def api_emergency_stop():
        return JSONResponse(controller.emergency_stop_all())

    @app.post("/api/close-position", dependencies=[Depends(require_auth)])
    def api_close_position(req: ClosePositionRequest):
        return JSONResponse(controller.close_position(req.pair, req.position_side))

    @app.post("/api/config", dependencies=[Depends(require_auth)])
    def api_config(req: ConfigRequest):
        return JSONResponse(
            controller.update_config(
                api_key=req.api_key,
                api_secret=req.api_secret,
                capital_limit_jpy=req.capital_limit_jpy,
                baseline_jpy=req.baseline_jpy,
                goal_target_jpy=req.goal_target_jpy,
                allow_shorts=req.allow_shorts,
                force_profit_close_jpy=req.force_profit_close_jpy,
                allow_counter_trend_longs=req.allow_counter_trend_longs,
            )
        )

    @app.post("/api/config/remove-key", dependencies=[Depends(require_auth)])
    def api_remove_key():
        return JSONResponse(controller.remove_api_key())

    @app.get("/api/tax", dependencies=[Depends(require_auth)])
    def api_tax_report(year: Optional[int] = None):
        return JSONResponse(controller.get_tax_report(year=year))

    @app.post("/api/tax/profile", dependencies=[Depends(require_auth)])
    def api_tax_profile(req: TaxProfileRequest):
        return JSONResponse(
            controller.update_tax_profile(
                tax_year=req.tax_year,
                employment_type=req.employment_type,
                annual_salary_jpy=req.annual_salary_jpy,
                other_misc_income_jpy=req.other_misc_income_jpy,
                filing_threshold_jpy=req.filing_threshold_jpy,
                taxpayer_name=req.taxpayer_name,
                tax_office=req.tax_office,
            )
        )

    @app.get("/api/tax/csv", dependencies=[Depends(require_auth)])
    def api_tax_csv(year: Optional[int] = None):
        report = controller.get_tax_report(year=year)
        csv_text = render_tax_csv(report)
        tax_year = report.get("tax_year", 2026)
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="bitbank_tax_{tax_year}.csv"'
            },
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitbank trading bot: engine, control API and web dashboard")
    parser.add_argument("--mode", choices=["live", "dry-run"], default="dry-run")
    parser.add_argument("--baseline", type=float, default=20000.0)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _load_env_file(".env")
    engine = Engine(mode=args.mode, settings=Settings(baseline_jpy=args.baseline))
    controller = BotController(engine, auto_start=True)
    app = create_app(controller)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
