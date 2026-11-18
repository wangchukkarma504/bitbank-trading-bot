"""Trade review: summarise the journal in loss_lessons.json so rule changes rest on evidence.

Run: python3 -m tradingbot.analysis.trade_review [path] [--since YYYY-MM-DD]

Groups closed trades by setup (side, 15m RSI band, trend stack) and by exit reason, and compares the
live average result with the +0.2% per trade the 150-day candle replay gave for the current short rule.
A bucket needs MIN_SAMPLE trades before its numbers mean anything; below that it is flagged as too few.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import sys
from typing import Any, Dict, List

MIN_SAMPLE = 20
BACKTEST_AVG_PCT_ON_NOTIONAL = 0.20
JST = timezone(timedelta(hours=9))


def _rsi_band(rsi: float) -> str:
    if rsi <= 0:
        return "rsi n/a"
    if rsi >= 70:
        return "rsi 70+"
    if rsi >= 65:
        return "rsi 65-70"
    return "rsi <65"


def summarise(lessons: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    if not lessons:
        return ["No closed trades in range."]
    wins = [l for l in lessons if not l.get("is_loss")]
    total = sum(float(l.get("pnl_jpy", 0.0)) for l in lessons)
    lines.append(
        f"{len(lessons)} trades | win rate {100.0 * len(wins) / len(lessons):.0f}% | net {total:+,.0f} JPY | "
        f"avg {total / len(lessons):+,.0f} JPY/trade"
    )

    def table(title: str, key) -> None:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for l in lessons:
            groups[key(l)].append(l)
        lines.append(f"\n{title}")
        for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            pnl = sum(float(r.get("pnl_jpy", 0.0)) for r in rows)
            wr = 100.0 * sum(1 for r in rows if not r.get("is_loss")) / len(rows)
            flag = "" if len(rows) >= MIN_SAMPLE else "  (too few to act on)"
            lines.append(f"  {name:44s} n={len(rows):3d} win={wr:3.0f}% net={pnl:+8,.0f} JPY{flag}")

    table("By setup", lambda l: f"{l.get('side', '?')} | {_rsi_band(float(l.get('entry_rsi', 0.0) or 0.0))} | "
                                f"4h {l.get('trend_4h') or '?'} 1h {l.get('trend_1h') or '?'} 15m {l.get('trend_15m') or '?'}")
    table("By exit", lambda l: l.get("exit_reason") or "unrecorded")
    table("By pair", lambda l: l.get("pair", "?"))
    table("By diagnosed cause", lambda l: l.get("root_cause", "?"))
    lines.append(
        f"\nBacktest expectation for the current short rule: about +{BACKTEST_AVG_PCT_ON_NOTIONAL:.1f}% of notional "
        f"per trade. Change a rule only when a bucket with n >= {MIN_SAMPLE} disagrees and a candle replay confirms it."
    )
    return lines


def main(argv: List[str]) -> None:
    path = "loss_lessons.json"
    since_ts = 0.0
    args = list(argv)
    if "--since" in args:
        i = args.index("--since")
        since_ts = datetime.strptime(args[i + 1], "%Y-%m-%d").replace(tzinfo=JST).timestamp()
        del args[i:i + 2]
    if args:
        path = args[0]
    with open(path, "r", encoding="utf-8") as f:
        lessons = [l for l in json.load(f).get("lessons", []) if float(l.get("timestamp", 0.0)) >= since_ts]
    print("\n".join(summarise(lessons)))


if __name__ == "__main__":
    main(sys.argv[1:])
