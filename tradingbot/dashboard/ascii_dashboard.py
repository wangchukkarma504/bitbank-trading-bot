"""ASCII Easy Dashboard for Bitbank Autonomous Trading System.

Renders real-time status reporting matching user requirements and institutional aesthetics:
- Header: Starting Budget, 2.0x Buying Power [Max 80% used], Live Total Value, Total PnL.
- Capital Growth Milestones with 16-character Unicode progress bars (█ and ░):
  • Near-term 2X: ¥20,000.00 JPY
  • Mid-term 5X: ¥50,000.00 JPY
  • Long-term 10X: ¥100,000.00 JPY
- Active Trades: Pair, side, size, entry px, current px, uPnL, margin ratio, target ladder.
- Active Exchange Stop Orders: Pair, side, trigger px, protected amount, status, order ID.
- Target Milestones: Break-Even, Profit-Lock, and Take-Profit exit targets.
- 5-Pair Market Radar & 6-Role Consensus.
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def calc_milestone_progress(
    current_equity: float,
    baseline: float = 10001.0,
    target: float = 20000.0,
) -> Tuple[float, float, str]:
    """Calculate milestone progress percentage, remaining distance, and 16-char bar string.

    Returns:
        (progress_pct, to_go_jpy, bar_str)
    """
    gain = max(0.0, current_equity - baseline)
    required_gain = max(1.0, target - baseline)
    progress_pct = min(100.0, (gain / required_gain) * 100.0)
    to_go_jpy = max(0.0, target - current_equity)

    filled = int(round((progress_pct / 100.0) * 16))
    filled = max(0, min(16, filled))
    bar_str = "█" * filled + "░" * (16 - filled)

    return progress_pct, to_go_jpy, bar_str


def calc_target_ladder_progress(
    entry_price: float,
    last_price: float,
    target_price: float,
    side: str = "short",
) -> Tuple[float, str]:
    """Calculate target ladder progress for open position.

    Returns:
        (progress_pct, bar_str)
    """
    if side == "short":
        total_dist = entry_price - target_price
        traveled = entry_price - last_price
    else:
        total_dist = target_price - entry_price
        traveled = last_price - entry_price

    if total_dist <= 0.0:
        return 0.0, "░" * 16

    progress_pct = max(0.0, min(100.0, (traveled / total_dist) * 100.0))
    filled = int(round((progress_pct / 100.0) * 16))
    filled = max(0, min(16, filled))
    bar_str = "█" * filled + "░" * (16 - filled)

    return progress_pct, bar_str


def render_ascii_dashboard(
    client: Optional[Any] = None,
    starting_budget: float = 10001.0,
    usdjpy: float = 154.5,
    position_review: Optional[Any] = None,
    signals: Optional[Dict[str, Any]] = None,
    open_positions: Optional[List[Dict[str, Any]]] = None,
    active_stops: Optional[List[Dict[str, Any]]] = None,
    total_equity: Optional[float] = None,
    macro_report: Optional[Any] = None,
    alt_candidates: Optional[List[Any]] = None,
) -> str:
    """Render full ASCII Easy Dashboard output conforming to test contracts and aesthetics."""
    # 1. Resolve Total Equity
    if total_equity is None:
        if position_review is not None and hasattr(position_review, "total_equity_jpy"):
            total_equity = float(position_review.total_equity_jpy)
        elif client is not None and hasattr(client, "calculate_total_equity") and callable(client.calculate_total_equity):
            total_equity = float(client.calculate_total_equity())
        elif client is not None and hasattr(client, "_get"):
            # Real Bitbank API client fallback
            try:
                assets_res = client._get("/user/assets")
                assets_list = assets_res.get("assets", []) if isinstance(assets_res, dict) else []
                cash = 0.0
                crypto_val = 0.0
                for a in assets_list:
                    asset = a.get("asset")
                    free_amt = float(a.get("free_amount", 0.0))
                    locked_amt = float(a.get("locked_amount", 0.0))
                    tot = free_amt + locked_amt
                    if asset == "jpy":
                        cash += tot
                    elif tot > 0.0001:
                        try:
                            tk = client.ticker(f"{asset}_jpy")
                            crypto_val += tot * float(tk.get("last", 0.0))
                        except Exception:
                            pass

                positions = client.margin_positions()
                u_pnl = 0.0
                for p in positions:
                    amt = float(p.get("open_amount", 0.0))
                    if amt > 0:
                        pair = p.get("pair")
                        pos_side = p.get("position_side", "short")
                        avg_p = float(p.get("average_price", 0.0))
                        try:
                            tk = client.ticker(pair)
                            last_p = float(tk.get("last", avg_p))
                        except Exception:
                            last_p = avg_p
                        u_pnl += amt * (avg_p - last_p) if pos_side == "short" else amt * (last_p - avg_p)

                total_equity = cash + crypto_val + u_pnl
            except Exception:
                total_equity = starting_budget
        else:
            total_equity = starting_budget

    total_equity = float(total_equity)
    buying_power = total_equity * 2.0
    total_pnl = total_equity - starting_budget
    total_pnl_pct = (total_pnl / starting_budget) * 100.0 if starting_budget > 0 else 0.0

    # Resolve Open Positions & Active Stops early so In-Trade PnL is shown in header
    if open_positions is None:
        if position_review is not None and hasattr(position_review, "open_positions"):
            open_positions = position_review.open_positions
        elif client is not None and hasattr(client, "get_open_positions") and callable(client.get_open_positions):
            open_positions = client.get_open_positions()
        else:
            open_positions = []

    if active_stops is None:
        if position_review is not None and hasattr(position_review, "active_stops"):
            active_stops = position_review.active_stops
        elif client is not None and hasattr(client, "orders"):
            active_stops = [
                o for o in client.orders.values()
                if o.get("type") == "stop" and o.get("status") in ("UNFILLED", "INACTIVE")
            ]
        else:
            active_stops = []

    in_trade_pnl = 0.0
    in_trade_notional = 0.0
    for p in (open_positions or []):
        p_pair = p.get("pair", "")
        p_side = p.get("position_side", "short")
        p_amt = float(p.get("open_amount", p.get("amount", 0.0)))
        p_avg = float(p.get("avg_price", p.get("average_price", 0.0)))
        p_last = float(p.get("last_price", 0.0))
        if (p_last <= 0 or p_last == p_avg) and client is not None and p_pair:
            try:
                tk = client.ticker(p_pair)
                p_last = float(tk.get("last", p_avg))
            except Exception:
                p_last = p_avg
        in_trade_pnl += p_amt * (p_avg - p_last) if p_side == "short" else p_amt * (p_last - p_avg)
        in_trade_notional += p_amt * p_avg

    in_trade_pct = (in_trade_pnl / in_trade_notional) * 100.0 if in_trade_notional > 0 else 0.0
    in_trade_usd = in_trade_pnl / usdjpy
    in_sign = "+" if in_trade_pnl >= 0 else ""

    sign = "+" if total_pnl >= 0 else ""
    pnl_usd = total_pnl / usdjpy
    equity_usd = total_equity / usdjpy
    budget_usd = starting_budget / usdjpy
    buying_power_usd = buying_power / usdjpy

    if starting_budget >= 50000.0:
        t2x = 200000.0 if starting_budget <= 120000.0 else round(starting_budget * 2.0, -3)
        t5x = 500000.0 if starting_budget <= 120000.0 else round(starting_budget * 5.0, -3)
        t10x = 1000000.0 if starting_budget <= 120000.0 else round(starting_budget * 10.0, -3)
    else:
        t2x, t5x, t10x = 20000.0, 50000.0, 100000.0

    p2x, rem2x, bar2x = calc_milestone_progress(total_equity, baseline=starting_budget, target=t2x)
    p5x, rem5x, bar5x = calc_milestone_progress(total_equity, baseline=starting_budget, target=t5x)
    p10x, rem10x, bar10x = calc_milestone_progress(total_equity, baseline=starting_budget, target=t10x)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════════╗",
        "║               📈 BITBANK CRYPTO BOT: EASY DASHBOARD                      ║",
        "╚══════════════════════════════════════════════════════════════════════════╝",
        f" 💰 Starting Budget       : ¥{starting_budget:,.0f} (${budget_usd:.2f} USDT)",
        f" ⚡ 2.0x Buying Power     : ¥{buying_power:,.0f} (${buying_power_usd:.2f} USDT) [1.95x Max Short]",
        f" 🏦 Current Total Value   : ¥{total_equity:,.1f} (${equity_usd:.2f} USDT)",
        f" 📊 Total Profit / Loss   : {sign}¥{total_pnl:,.1f} ({sign}${pnl_usd:.2f} | {sign}{total_pnl_pct:.2f}%)",
        f" 📈 In-Trade Unrealized   : {in_sign}¥{in_trade_pnl:,.1f} ({in_sign}${in_trade_usd:.2f} | {in_sign}{in_trade_pct:.2f}%)",
        "╶──────────────────────────────────────────────────────────────────────────╴",
        " 🎯 CAPITAL MILESTONES:",
        f"   • 2X Milestone  [¥{t2x:,.0f} JPY] : [{bar2x}] {p2x:4.1f}% (¥{rem2x:,.2f} to go)",
        f"   • 5X Milestone  [¥{t5x:,.0f} JPY] : [{bar5x}] {p5x:4.1f}% (¥{rem5x:,.2f} to go)",
        f"   • 10X Milestone [¥{t10x:,.0f} JPY]: [{bar10x}] {p10x:4.1f}% (¥{rem10x:,.2f} to go)",
        "╶──────────────────────────────────────────────────────────────────────────╴",
    ]

    active_count = len(open_positions) if open_positions else 0
    active_orders_count = len(active_stops) if active_stops else 0
    status_label = f"{active_count} running" if active_count > 0 else f"{active_orders_count} pending fill"
    lines.append(f" 🎯 ACTIVE TRADES ({status_label}):")

    if open_positions:
        for p in open_positions:
            pair = p.get("pair", "")
            side = p.get("position_side", "short")
            amt = float(p.get("open_amount", p.get("amount", 0.0)))
            avg_px = float(p.get("avg_price", p.get("average_price", 0.0)))

            last_px = float(p.get("last_price", 0.0))
            if (last_px <= 0 or last_px == avg_px) and client is not None:
                try:
                    tk = client.ticker(pair)
                    last_px = float(tk.get("last", avg_px))
                except Exception:
                    last_px = avg_px

            pnl = amt * (avg_px - last_px) if side == "short" else amt * (last_px - avg_px)
            pnl_sign = "+" if pnl >= 0 else ""
            notional = amt * avg_px

            target_px = avg_px * 0.98 if side == "short" else avg_px * 1.02
            ladder_pct, ladder_bar = calc_target_ladder_progress(avg_px, last_px, target_px, side=side)

            # Milestones for target ladder
            if side == "short":
                be_target = avg_px
                lock_target = avg_px * 0.99
            else:
                be_target = avg_px
                lock_target = avg_px * 1.01

            # Match active stop order if present
            matching_stops = [
                s for s in (active_stops or [])
                if s.get("pair") == pair and s.get("status") in ("UNFILLED", "INACTIVE")
            ]
            stop_info = "ARMED"
            if matching_stops:
                st = matching_stops[0]
                trig = float(st.get("trigger_price", 0.0))
                oid = st.get("order_id", "")
                stop_info = f"{trig:,.1f} JPY [Order #{oid}] (Exchange-Side Active)"
            else:
                stop_info = "Auto-supervised"

            pair_label = pair.replace("_", "").upper()
            lines.extend([
                f"   [{pair_label}] MARGIN {side.upper()} (Size: ¥{notional:,.0f} | {amt:.4f} | 1.60x Lev)",
                f"   • Current PnL   : {pnl_sign}¥{pnl:,.1f}",
                f"   • Entry Price   : {avg_px:,.1f} JPY",
                f"   • Current Price : {last_px:,.1f} JPY",
                f"   • Safety Stop   : {stop_info}",
                f"   • Profit Target : {target_px:,.1f} JPY",
                f"   • Target Ladder : [{ladder_bar}] {ladder_pct:.1f}% toward target",
                f"   • Milestones    : Break-Even: {be_target:,.1f} JPY | Profit-Lock: {lock_target:,.1f} JPY | Take-Profit: {target_px:,.1f} JPY",
            ])
    else:
        lines.append("   No open positions. Actively scanning Bitbank pairs.")

    # 3. Active Exchange Stop Orders Table
    if active_stops:
        lines.append("╶──────────────────────────────────────────────────────────────────────────╴")
        lines.append(" 🛡️ ACTIVE EXCHANGE STOP ORDERS:")
        lines.append("   PAIR       SIDE   TRIGGER PX      AMOUNT    STATUS     ORDER ID")
        for s in active_stops:
            spair = s.get("pair", "").ljust(10)
            sside = s.get("side", "").upper().ljust(6)
            trig_val = float(s.get("trigger_price", 0.0))
            strig = f"{trig_val:,.1f} JPY".ljust(15)
            amt_val = float(s.get("start_amount", s.get("amount", 0.0)))
            samt = f"{amt_val:.4f}".ljust(9)
            sstat = s.get("status", "UNFILLED").ljust(10)
            soid = str(s.get("order_id", ""))
            lines.append(f"   {spair} {sside} {strig} {samt} {sstat} #{soid}")

    # 4. 5-Pair Market Radar & 6-Role Consensus
    if signals:
        lines.append("╶──────────────────────────────────────────────────────────────────────────╴")
        lines.append(" 📡 5-PAIR MARKET RADAR & 6-ROLE CONSENSUS:")
        lines.append("   PAIR       BIAS          ALIGNMENT    WICK PATTERN         DEPTH RATIO")
        for pair_name, sig in signals.items():
            s_pair = pair_name.ljust(10)
            bias = (sig.action if hasattr(sig, "action") else sig.get("action", "NEUTRAL")).ljust(13)
            align = (sig.trend_alignment if hasattr(sig, "trend_alignment") else sig.get("trend_alignment", "NEUTRAL")).ljust(12)
            wick = (sig.wick_classification if hasattr(sig, "wick_classification") else sig.get("wick_classification", "NEUTRAL")).ljust(20)
            dr_val = sig.depth_ratio if hasattr(sig, "depth_ratio") else sig.get("depth_ratio", 1.0)
            lines.append(f"   {s_pair} {bias} {align} {wick} {dr_val:.2f}")

    # 5. Live Macro & Catalyst Prediction (when available)
    if macro_report is not None:
        lines.append("╶──────────────────────────────────────────────────────────────────────────╴")
        fng_v = getattr(macro_report, "fear_and_greed_value", 50)
        fng_l = getattr(macro_report, "fear_and_greed_label", "Neutral")
        summary = getattr(macro_report, "prediction_summary", "")
        lines.append(f" 🌐 MACRO & CATALYST PREDICTION | Fear & Greed: {fng_v} ({fng_l})")
        lines.append(f"   {summary}")
        for ev in getattr(macro_report, "events", [])[:2]:
            lines.append(f"   • [{ev.source}] ({ev.impact_score:+.2f}) {ev.headline[:70]}")

    # 6. 60+ Altcoin Hidden Breakout Radar
    if alt_candidates:
        lines.append("╶──────────────────────────────────────────────────────────────────────────╴")
        lines.append(" 🚀 ALTCOIN 20% BREAKOUT RADAR (60+ BITBANK PAIRS):")
        for ac in alt_candidates[:3]:
            status_tag = "READY" if getattr(ac, "actionable", False) else "WATCH"
            lines.append(
                f"   • {ac.pair.upper():<9} | 24h: {ac.change_24h_pct:+5.1f}% | VolSurge: {ac.volume_surge_ratio:4.1f}x | Score: {ac.breakout_score:4.1f} [{status_tag}]"
            )

    lines.append("════════════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


class AsciiDashboard:
    """ASCII Easy Dashboard renderer matching user requirements and institutional aesthetics."""

    def __init__(self, starting_budget: float = 10001.0, usdjpy: float = 154.5):
        self.starting_budget = starting_budget
        self.usdjpy = usdjpy

    def render(
        self,
        client: Optional[Any] = None,
        position_review: Optional[Any] = None,
        signals: Optional[Dict[str, Any]] = None,
        open_positions: Optional[List[Dict[str, Any]]] = None,
        active_stops: Optional[List[Dict[str, Any]]] = None,
        total_equity: Optional[float] = None,
        macro_report: Optional[Any] = None,
        alt_candidates: Optional[List[Any]] = None,
    ) -> str:
        """Render the ASCII Easy Dashboard string."""
        return render_ascii_dashboard(
            client=client,
            starting_budget=self.starting_budget,
            usdjpy=self.usdjpy,
            position_review=position_review,
            signals=signals,
            open_positions=open_positions,
            active_stops=active_stops,
            total_equity=total_equity,
            macro_report=macro_report,
            alt_candidates=alt_candidates,
        )
