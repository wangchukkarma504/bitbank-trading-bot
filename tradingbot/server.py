"""FastAPI Live Control Server & Real-Time Web Dashboard for Bitbank Trading Bot.

Provides:
- Background TradingOrchestrator loop (10s ticks) with pause/resume control
- Real-time JSON API (/api/status, /api/pause, /api/resume, /api/emergency-stop, /health)
- Interactive Dark-Mode Web Dashboard (/) with live Equity Graph, Capital Milestones,
  Active Positions & Stops, 5-Pair Radar, Macro News Catalyst, Loss-Learner Lessons,
  and a BIG RED "STOP ALL TRADES" emergency kill switch.
"""

import argparse
from contextlib import asynccontextmanager
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

from tradingbot.bitbank import Bitbank
from tradingbot.dashboard_html import DASHBOARD_HTML, render_login_html
from tradingbot.models import MARGIN_PAIRS, PairConfig, SPOT_ONLY_PAIRS, SUPPORTED_PAIRS
from tradingbot.orchestrator import TradingOrchestrator
from tradingbot.tax_japan import (
    TaxProfile,
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
    """Thread-safe controller wrapping TradingOrchestrator + equity history + emergency stop."""

    MAX_HISTORY_POINTS = 500

    def __init__(
        self,
        orchestrator: TradingOrchestrator,
        history_path: str = "equity_history.json",
        config_path: str = "bot_config.json",
        env_path: str = ".env",
        tax_profile_path: str = "tax_profile.json",
        trade_log_path: str = "trade_audit_log.json",
        auto_start: bool = True,
    ):
        self.orchestrator = orchestrator
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
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_history()
        self._load_config()
        self._load_trade_audit()

    def _load_config(self) -> None:
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cap = cfg.get("capital_limit_jpy")
            if cap is not None and float(cap) > 0:
                self.orchestrator.capital_limit_jpy = float(cap)
            base = cfg.get("baseline_jpy")
            if base is not None and float(base) > 0:
                bval = float(base)
                self.orchestrator.baseline_budget_jpy = bval
                self.orchestrator.position_reviewer.baseline_budget_jpy = bval
                self.orchestrator.dashboard.starting_budget = bval
            goal = cfg.get("goal_target_jpy")
            if goal is not None and float(goal) > 0:
                self.goal_target_jpy = float(goal)
            if "allow_shorts" in cfg and cfg["allow_shorts"] is not None:
                self.orchestrator.allow_shorts = bool(cfg["allow_shorts"])
            fpc = cfg.get("force_profit_close_jpy")
            if fpc is not None and float(fpc) > 0:
                self.orchestrator.force_profit_close_jpy = float(fpc)
            if "allow_counter_trend_longs" in cfg and cfg["allow_counter_trend_longs"] is not None:
                val = bool(cfg["allow_counter_trend_longs"])
                self.orchestrator.allow_counter_trend_longs = val
                self.orchestrator.directional_strategist.allow_counter_trend_longs = val
        except Exception as e:
            logger.warning(f"Could not load bot config: {e}")

    def _save_config(self) -> None:
        if not self.config_path:
            return
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "capital_limit_jpy": self.orchestrator.capital_limit_jpy,
                        "baseline_jpy": self.orchestrator.baseline_budget_jpy,
                        "goal_target_jpy": self.goal_target_jpy,
                        "allow_shorts": self.orchestrator.allow_shorts,
                        "force_profit_close_jpy": self.orchestrator.force_profit_close_jpy,
                        "allow_counter_trend_longs": self.orchestrator.allow_counter_trend_longs,
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
        allow_shorts: Optional[bool] = None,
        force_profit_close_jpy: Optional[float] = None,
        allow_counter_trend_longs: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update Bitbank API credentials, capital limit, baseline, goal, and/or short mode live."""
        changed: List[str] = []
        with self.lock:
            if api_key and api_secret:
                key_clean = api_key.strip()
                sec_clean = api_secret.strip()
                os.environ["API_KEY"] = key_clean
                os.environ["SECRET_KEY"] = sec_clean
                _save_env_keys(self.env_path, key_clean, sec_clean)
                new_client = Bitbank(key=key_clean, secret=sec_clean)
                orch = self.orchestrator
                orch.client = new_client
                orch.position_reviewer.client = new_client
                orch.trend_analyst.client = new_client
                orch.wick_analyst.client = new_client
                orch.tech_analyst.client = new_client
                orch.alt_scanner.client = new_client
                orch.directional_strategist.client = new_client
                orch.risk_manager.client = new_client
                changed.append("api_credentials")

            if capital_limit_jpy is not None:
                if capital_limit_jpy > 0:
                    cap_val = float(capital_limit_jpy)
                    self.orchestrator.capital_limit_jpy = cap_val
                    if baseline_jpy is None:
                        self.orchestrator.baseline_budget_jpy = cap_val
                        self.orchestrator.position_reviewer.baseline_budget_jpy = cap_val
                        self.orchestrator.dashboard.starting_budget = cap_val
                else:
                    self.orchestrator.capital_limit_jpy = None
                self._save_config()
                changed.append("capital_limit_jpy")

            if baseline_jpy is not None and baseline_jpy > 0:
                bval = float(baseline_jpy)
                self.orchestrator.baseline_budget_jpy = bval
                self.orchestrator.position_reviewer.baseline_budget_jpy = bval
                self.orchestrator.dashboard.starting_budget = bval
                self.orchestrator._peak_equity_jpy = bval
                self._save_config()
                changed.append("baseline_jpy")

            if goal_target_jpy is not None:
                self.goal_target_jpy = float(goal_target_jpy) if goal_target_jpy > 0 else None
                self._save_config()
                changed.append("goal_target_jpy")

            if allow_shorts is not None:
                self.orchestrator.allow_shorts = bool(allow_shorts)
                self._save_config()
                changed.append("allow_shorts")

            if force_profit_close_jpy is not None:
                self.orchestrator.force_profit_close_jpy = (
                    float(force_profit_close_jpy) if force_profit_close_jpy > 0 else None
                )
                self._save_config()
                changed.append("force_profit_close_jpy")

            if allow_counter_trend_longs is not None:
                val = bool(allow_counter_trend_longs)
                self.orchestrator.allow_counter_trend_longs = val
                self.orchestrator.directional_strategist.allow_counter_trend_longs = val
                self._save_config()
                changed.append("allow_counter_trend_longs")

        return {
            "ok": True,
            "updated": changed,
            "capital_limit_jpy": self.orchestrator.capital_limit_jpy,
            "baseline_jpy": self.orchestrator.baseline_budget_jpy,
            "goal_target_jpy": self.goal_target_jpy,
            "allow_shorts": self.orchestrator.allow_shorts,
            "force_profit_close_jpy": self.orchestrator.force_profit_close_jpy,
            "allow_counter_trend_longs": self.orchestrator.allow_counter_trend_longs,
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
            orch = self.orchestrator
            orch.client = new_client
            orch.position_reviewer.client = new_client
            orch.trend_analyst.client = new_client
            orch.wick_analyst.client = new_client
            orch.tech_analyst.client = new_client
            orch.alt_scanner.client = new_client
            orch.directional_strategist.client = new_client
            orch.risk_manager.client = new_client
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
        """Sync recent Bitbank fills (including manual trades while paused/off) into local audit log."""
        with self.lock:
            client = self.orchestrator.client
            dry_run = self.orchestrator.dry_run
            lessons = list(self.orchestrator.loss_learner.lessons) if self.orchestrator.loss_learner else []
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
        bot_closes = [
            (l.pair, float(l.timestamp))
            for l in lessons
        ]
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
                net_pnl = round(raw_pnl - fee_q - interest, 2) if pos_side else 0.0
                ts_ms = int(t.get("executed_at") or 0)
                ts_sec = int(ts_ms / 1000) if ts_ms > 0 else int(time.time())
                is_bot = any(bp == pair and abs(bts - ts_sec) <= 25 for bp, bts in bot_closes)
                self.trade_audit.append({
                    "trade_id": tid,
                    "ts": ts_sec,
                    "time_jst": datetime.fromtimestamp(ts_sec, tz=jst).strftime("%Y-%m-%d %H:%M:%S"),
                    "pair": pair,
                    "side": f"{side} ({pos_side})" if pos_side else f"{side} (spot)",
                    "position_side": pos_side,
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
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OrchestratorLoop")
        self._thread.start()

    def stop_loop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _run_loop(self) -> None:
        self.sync_exchange_trades()
        while not self._stop_event.is_set():
            now = time.time()
            if self.running and not self.emergency_stopped:
                try:
                    res = self.orchestrator.tick()
                    eq = float(res.get("equity_jpy", self.orchestrator.baseline_budget_jpy))
                    now = time.time()
                    with self.lock:
                        self.last_tick_ts = now
                        self.last_error = None
                        self.equity_history.append({"ts": int(now), "equity": round(eq, 2)})
                        if len(self.equity_history) > self.MAX_HISTORY_POINTS:
                            self.equity_history = self.equity_history[-self.MAX_HISTORY_POINTS:]
                        self._save_history()
                    if now - self._last_sync_ts >= 60.0:
                        self.sync_exchange_trades()
                except Exception as e:
                    logger.error(f"Server tick error: {e}", exc_info=True)
                    with self.lock:
                        self.last_error = str(e)
            elif not self.emergency_stopped and (now - self._last_sync_ts >= 60.0):
                # Keep equity curve & manual Bitbank trades synced even while bot is PAUSED
                try:
                    if not self.orchestrator.dry_run and getattr(self.orchestrator.client, "key", None):
                        rev = self.orchestrator.position_reviewer.review()
                        self.orchestrator.last_review = rev
                        eq = float(rev.total_equity_jpy)
                        with self.lock:
                            self.equity_history.append({"ts": int(now), "equity": round(eq, 2)})
                            if len(self.equity_history) > self.MAX_HISTORY_POINTS:
                                self.equity_history = self.equity_history[-self.MAX_HISTORY_POINTS:]
                            self._save_history()
                    self.sync_exchange_trades()
                except Exception as e:
                    logger.debug(f"Paused sync skipped: {e}")
                    with self.lock:
                        self._last_sync_ts = time.time()
            self._stop_event.wait(self.orchestrator.TICK_INTERVAL_SEC)

    def pause(self) -> Dict[str, Any]:
        with self.lock:
            self.running = False
            self._last_sync_ts = 0.0
        return {"status": "PAUSED", "running": self.running}

    def resume(self) -> Dict[str, Any]:
        with self.lock:
            self.emergency_stopped = False
            self.orchestrator._circuit_breaker_until = 0.0
            self.orchestrator._global_cooldown_until = 0.0
            self.running = True
            self._last_sync_ts = 0.0
        return {"status": "RUNNING", "running": self.running}

    def emergency_stop_all(self) -> Dict[str, Any]:
        """Immediately halt the bot, cancel all active orders, and close all open margin positions."""
        with self.lock:
            self.running = False
            self.emergency_stopped = True

        cancelled: List[Dict[str, Any]] = []
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        client = self.orchestrator.client

        if not self.orchestrator.dry_run and client is not None:
            for pair in SUPPORTED_PAIRS:
                try:
                    orders = client._get("/user/spot/active_orders", {"pair": pair}).get("orders", [])
                    for o in orders:
                        oid = o.get("order_id")
                        if oid is not None:
                            client.cancel(pair, oid)
                            cancelled.append({"pair": pair, "order_id": oid, "type": o.get("type")})
                except Exception as e:
                    errors.append(f"Cancel error on {pair}: {e}")

            try:
                for p in client.margin_positions():
                    amt = float(p.get("open_amount", 0.0))
                    if amt > 0.0001:
                        pair = p["pair"]
                        side = p["position_side"]
                        close_side = "buy" if side == "short" else "sell"
                        res = client.order(
                            pair,
                            side=close_side,
                            amount=p["open_amount"],
                            type_="market",
                            position_side=side,
                        )
                        closed.append({
                            "pair": pair,
                            "side": side,
                            "amount": p["open_amount"],
                            "order_id": res.get("order_id"),
                        })
            except Exception as e:
                errors.append(f"Position close error: {e}")

            try:
                assets_res = client._get("/user/assets").get("assets", [])
                for a in assets_res:
                    asset = a.get("asset", "")
                    pair = f"{asset}_jpy"
                    if pair not in SUPPORTED_PAIRS:
                        continue
                    free_amt = float(a.get("free_amount", 0.0))
                    if free_amt <= 0.0001:
                        continue
                    try:
                        last_px = float((client.ticker(pair) or {}).get("last", 0.0))
                    except Exception:
                        last_px = 0.0
                    if free_amt * last_px >= 500.0:
                        cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS.get(pair) or PairConfig(pair=pair, price_digits=3, amount_digits=4)
                        amt_str = f"{free_amt:.{cfg.amount_digits}f}"
                        res = client.order(pair, side="sell", amount=amt_str, type_="market")
                        closed.append({"pair": pair, "side": "spot", "amount": amt_str, "order_id": res.get("order_id")})
            except Exception as e:
                errors.append(f"Spot close error: {e}")

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

    def close_position(self, pair: str, position_side: Optional[str] = None) -> Dict[str, Any]:
        """Cancel active orders for a pair and market-close the open position."""
        if pair not in SUPPORTED_PAIRS:
            raise HTTPException(status_code=400, detail=f"Unsupported pair: {pair}")

        cancelled: List[Dict[str, Any]] = []
        closed: List[Dict[str, Any]] = []
        errors: List[str] = []
        client = self.orchestrator.client

        if not self.orchestrator.dry_run and client is not None:
            try:
                orders = client._get("/user/spot/active_orders", {"pair": pair}).get("orders", [])
                for o in orders:
                    oid = o.get("order_id")
                    if oid is not None:
                        client.cancel(pair, oid)
                        cancelled.append({"pair": pair, "order_id": oid, "type": o.get("type")})
            except Exception as e:
                errors.append(f"Cancel error on {pair}: {e}")

            try:
                for p in client.margin_positions():
                    amt = float(p.get("open_amount", 0.0))
                    p_side = p.get("position_side")
                    if p.get("pair") == pair and amt > 0.0001:
                        if position_side and p_side != position_side:
                            continue
                        close_side = "buy" if p_side == "short" else "sell"
                        res = client.order(
                            pair,
                            side=close_side,
                            amount=p["open_amount"],
                            type_="market",
                            position_side=p_side,
                        )
                        closed.append({
                            "pair": pair,
                            "side": p_side,
                            "amount": p["open_amount"],
                            "order_id": res.get("order_id"),
                        })
            except Exception as e:
                errors.append(f"Margin close error on {pair}: {e}")

            # Also handle spot-only / spot long balances if no margin position was closed
            if not closed and (position_side in (None, "spot", "long")):
                try:
                    base_asset = pair.split("_")[0]
                    assets_res = client._get("/user/assets").get("assets", [])
                    for a in assets_res:
                        if a.get("asset") == base_asset:
                            free_amt = float(a.get("free_amount", 0.0))
                            if free_amt > 0.0001:
                                cfg = MARGIN_PAIRS.get(pair) or SPOT_ONLY_PAIRS.get(pair) or PairConfig(pair=pair, price_digits=3, amount_digits=4)
                                amt_str = f"{free_amt:.{cfg.amount_digits}f}"
                                res = client.order(pair, side="sell", amount=amt_str, type_="market")
                                closed.append({
                                    "pair": pair,
                                    "side": "spot",
                                    "amount": amt_str,
                                    "order_id": res.get("order_id"),
                                })
                except Exception as e:
                    errors.append(f"Spot close error on {pair}: {e}")

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
        orch = self.orchestrator
        rev = orch.last_review
        baseline = orch.baseline_budget_jpy
        equity = float(rev.total_equity_jpy) if rev else baseline
        free_cash = float(rev.free_cash_jpy) if rev else baseline
        buying_power = float(rev.buying_power_jpy) if rev else equity * 2.0
        total_pnl = equity - baseline
        total_pnl_pct = (total_pnl / baseline * 100.0) if baseline > 0 else 0.0

        open_positions = [dict(p) for p in (rev.open_positions if rev else [])]
        active_stops = rev.active_stops if rev else []
        in_trade_pnl = 0.0
        in_trade_notional = 0.0
        in_trade_est_net = 0.0
        for p in open_positions:
            upnl = float(p.get("unrealized_pnl_jpy", 0.0))
            notional = float(p.get("notional_jpy", 0.0))
            amt = float(p.get("amount", p.get("open_amount", 0.0)))
            avg_px = float(p.get("avg_price", p.get("average_price", 0.0)))
            p_side = p.get("position_side", "short")

            est_fee = round(notional * 0.0012, 2)
            est_net = round(upnl - est_fee, 2)
            p["est_close_fee_jpy"] = est_fee
            p["est_net_close_pnl_jpy"] = est_net

            match_stop = next(
                (s for s in active_stops if s.get("pair") == p.get("pair") and s.get("position_side") == p_side),
                None,
            )
            if match_stop and amt > 0 and avg_px > 0:
                trig = float(match_stop.get("trigger_price", 0.0))
                if trig > 0:
                    stop_gross = amt * (avg_px - trig) if p_side == "short" else amt * (trig - avg_px)
                    stop_fee = amt * trig * 0.0012
                    p["stop_trigger_price"] = trig
                    p["est_stop_pnl_jpy"] = round(stop_gross - stop_fee, 2)

            in_trade_pnl += upnl
            in_trade_notional += notional
            in_trade_est_net += est_net
        in_trade_pct = (in_trade_pnl / in_trade_notional * 100.0) if in_trade_notional > 0 else 0.0

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

        signals_out = []
        for pair, sig in (orch.last_signals or {}).items():
            signals_out.append({
                "pair": pair,
                "action": sig.action,
                "conviction": sig.conviction,
                "entry_price": sig.entry_price,
                "stop_loss_price": sig.stop_loss_price,
                "take_profit_price": sig.take_profit_price,
                "alignment": str(getattr(sig, "trend_alignment", "")),
                "wick": str(getattr(sig, "wick_classification", "")),
                "depth_ratio": round(float(getattr(sig, "depth_ratio", 1.0)), 2),
            })

        macro = orch.last_macro_report
        macro_out = None
        if macro is not None:
            macro_out = {
                "fear_greed": macro.fear_and_greed_value,
                "fear_greed_label": macro.fear_and_greed_label,
                "bias": macro.catalyst_bias,
                "score": macro.catalyst_score,
                "summary": macro.prediction_summary,
                "events": [
                    {"source": e.source, "headline": e.headline, "score": e.impact_score}
                    for e in (macro.events or [])[:4]
                ],
            }

        now = time.time()
        cb_rem = max(0, int(orch._circuit_breaker_until - now))
        cd_rem = max(0, int(orch._global_cooldown_until - now))
        lessons = [
            {
                "pair": l.pair,
                "side": l.side,
                "pnl_jpy": l.pnl_jpy,
                "pnl_pct": l.pnl_pct,
                "cause": l.root_cause,
                "fix": l.fix_applied,
                "is_loss": l.is_loss,
            }
            for l in (orch.loss_learner.lessons[-8:] if orch.loss_learner else [])
        ]
        trade_history = [
            {
                "pair": l.pair,
                "side": l.side,
                "pnl_jpy": round(float(l.pnl_jpy), 2),
                "pnl_pct": round(float(l.pnl_pct), 2),
                "equity_after": round(float(l.exit_equity_jpy), 2),
                "is_loss": bool(l.is_loss),
                "ts": int(l.timestamp),
                "source": "bot",
            }
            for l in (orch.loss_learner.lessons[-16:] if orch.loss_learner else [])
        ]

        with self.lock:
            audit_copy = list(self.trade_audit)

        for row in audit_copy:
            if row.get("source") != "manual" or not row.get("position_side"):
                continue
            pnl = float(row.get("net_pnl_jpy") or 0.0)
            if abs(pnl) < 0.01:
                continue
            ts_row = int(row.get("ts") or 0)
            pair_row = str(row.get("pair") or "")
            if any(h["pair"] == pair_row and abs(h["ts"] - ts_row) <= 25 for h in trade_history):
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

        raw_key = getattr(orch.client, "key", None) or os.environ.get("API_KEY") or ""
        api_key_masked = ("****" + raw_key[-4:]) if len(raw_key) >= 4 else ("SET" if raw_key else "NOT SET")

        return {
            "state": state_label,
            "mode": orch.mode.upper(),
            "tick_count": orch.tick_count,
            "api_key_configured": bool(raw_key),
            "api_key_masked": api_key_masked,
            "capital_limit_jpy": orch.capital_limit_jpy,
            "baseline_jpy": round(baseline, 2),
            "goal_target_jpy": self.goal_target_jpy,
            "allow_shorts": orch.allow_shorts,
            "force_profit_close_jpy": orch.force_profit_close_jpy,
            "allow_counter_trend_longs": orch.allow_counter_trend_longs,
            "equity_jpy": round(equity, 2),
            "free_cash_jpy": round(free_cash, 2),
            "buying_power_jpy": round(buying_power, 2),
            "total_pnl_jpy": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "in_trade_pnl_jpy": round(in_trade_pnl, 2),
            "in_trade_pnl_pct": round(in_trade_pct, 2),
            "in_trade_est_net_pnl_jpy": round(in_trade_est_net, 2),
            "milestones": {"x2": _ms(t2x), "x5": _ms(t5x), "x10": _ms(t10x)},
            "open_positions": open_positions,
            "active_stops": active_stops,
            "signals": signals_out,
            "macro": macro_out,
            "circuit_breaker_sec": cb_rem,
            "cooldown_sec": cd_rem,
            "lessons": list(reversed(lessons)),
            "trade_history": trade_history,
            "equity_history": history,
            "last_error": err,
            "last_emergency_report": em_report,
        }

    def get_candles(self, pair: str = "btc_jpy", tf: str = "15min", limit: int = 80) -> Dict[str, Any]:
        """Fetch OHLCV candles from Bitbank public API for the live chart."""
        valid_tfs = {"5min", "15min", "1hour", "4hour"}
        tf_clean = tf if tf in valid_tfs else "15min"
        pair_clean = pair if pair in SUPPORTED_PAIRS else "btc_jpy"
        now_utc = datetime.now(timezone.utc)
        raw_rows: List[Any] = []
        try:
            if tf_clean == "4hour":
                raw_rows = self.orchestrator.client.candles(pair_clean, tf_clean, now_utc.strftime("%Y")) or []
            else:
                yday = (now_utc - timedelta(days=1)).strftime("%Y%m%d")
                today = now_utc.strftime("%Y%m%d")
                for day_str in (yday, today):
                    try:
                        raw_rows.extend(self.orchestrator.client.candles(pair_clean, tf_clean, day_str) or [])
                    except Exception:
                        pass
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
            client = self.orchestrator.client
            lessons = list(self.orchestrator.loss_learner.lessons)
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
            client = self.orchestrator.client
            lessons = list(self.orchestrator.loss_learner.lessons)
            cache_path = f"tax_cache_{prof.tax_year}.json" if self.tax_profile_path else ""
        return build_tax_report(client, prof, fallback_lessons=lessons, cache_path=cache_path)


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
    parser = argparse.ArgumentParser(description="Bitbank FastAPI Control Server & Web Dashboard")
    parser.add_argument("--mode", choices=["live", "dry-run"], default="dry-run")
    parser.add_argument("--baseline", type=float, default=98874.1)
    parser.add_argument("--spot-only", action="store_true", help="Disable margin shorts (Spot Long-Only mode)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _load_env_file(".env")
    orch = TradingOrchestrator(
        baseline_budget_jpy=args.baseline,
        mode=args.mode,
        allow_shorts=not args.spot_only,
    )
    controller = BotController(orch, auto_start=True)
    app = create_app(controller)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
