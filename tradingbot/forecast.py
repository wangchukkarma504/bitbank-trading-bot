"""Experimental price forecast for the dashboard's Prediction page. It never places or changes an order.

A ridge regression, one per chart timeframe, trained by research/train_forecast.py on Bitbank candles of all five
coins. From the candles up to the last closed one it predicts where the close will be after each of the next
candles, in units of the coin's current volatility (ATR), plus a band the price stayed inside 80% of the time on
held-out data. The same feature code is used for training and here, so what was tested is what is shown.

The page asks for a chart timeframe and how far ahead: 15-minute candles one hour ahead are 4 candles, 1-hour
candles one day ahead are 24, and so on. The predicted candles start after the candle that is still forming.
"""

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forecast_model.json")
TIMEFRAMES = {"5min": 300_000, "15min": 900_000, "1hour": 3_600_000, "4hour": 14_400_000}
AHEAD = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
MAX_STEPS = {"5min": 49, "15min": 97, "1hour": 25, "4hour": 7}   # furthest step each model predicts (+1: live candle)
FEATURES = ("r1", "r2", "r4", "r8", "r16", "r32", "dev20", "dev50", "atr", "rsi", "pos", "vol")
WARMUP = 50

_model_cache: Dict[str, Any] = {}


def feature_series(bars: Sequence[Sequence[float]]) -> List[Optional[List[float]]]:
    """Features of every candle [t, o, h, l, c, v], each from that candle and the ones before it.
    None while there is not enough history. The last entry also carries the ATR share used for scaling."""
    out: List[Optional[List[float]]] = []
    closes: List[float] = []
    vols: List[float] = []
    atr = up = dn = None
    s20 = s50 = 0.0
    for i, (_t, o, h, l, c, v) in enumerate(bars):
        prev = closes[-1] if closes else None
        tr = (h - l) if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        ch = 0.0 if prev is None else c - prev
        up = max(ch, 0.0) if up is None else (up * 13 + max(ch, 0.0)) / 14
        dn = max(-ch, 0.0) if dn is None else (dn * 13 + max(-ch, 0.0)) / 14
        closes.append(c)
        vols.append(v)
        s20 += c - (closes[-21] if len(closes) > 20 else 0.0)
        s50 += c - (closes[-51] if len(closes) > 50 else 0.0)
        if i < WARMUP or c <= 0 or atr <= 0 or min(closes[-33:]) <= 0:
            out.append(None)
            continue
        vol_prev = sum(vols[-21:-1]) / 20.0
        rsi = 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)
        f = [math.log(c / closes[-1 - k]) for k in (1, 2, 4, 8, 16, 32)]
        f += [math.log(c / (s20 / 20.0)), math.log(c / (s50 / 50.0)), atr / c, rsi / 100.0 - 0.5,
              ((c - l) / (h - l) - 0.5) if h > l else 0.0,
              max(-3.0, min(3.0, math.log(v / vol_prev))) if v > 0 and vol_prev > 0 else 0.0]
        out.append(f)
    return out


def load_model(path: str = MODEL_PATH) -> Optional[Dict[str, Any]]:
    try:
        mtime = os.path.getmtime(path)
        if _model_cache.get("mtime") != mtime:
            with open(path, "r", encoding="utf-8") as fh:
                _model_cache.update(model=json.load(fh), mtime=mtime)
        return _model_cache["model"]
    except Exception:
        return None


def _predict_steps(m: Dict[str, Any], f: List[float]) -> List[float]:
    """Predicted cumulative move after each step, in ATRs."""
    z = [(x - mu) / sd for x, mu, sd in zip(f, m["mean"], m["std"])]
    return [b0 + sum(w * x for w, x in zip(ws, z)) for b0, ws in zip(m["intercept"], m["coef"])]


def candles_ahead(tf: str, ahead: str) -> int:
    """How many candles of `tf` make `ahead`; 0 when that combination is not offered."""
    if tf not in TIMEFRAMES or ahead not in AHEAD:
        return 0
    k = AHEAD[ahead] // TIMEFRAMES[tf]
    return k if 1 <= k and k + 1 <= MAX_STEPS[tf] else 0


def options() -> Dict[str, List[str]]:
    return {tf: [a for a in AHEAD if candles_ahead(tf, a)] for tf in TIMEFRAMES}


def forecast(candles: List[Dict[str, Any]], tf: str, ahead: str, now_ms: int, model: Optional[Dict[str, Any]] = None,
             history: int = 40) -> Dict[str, Any]:
    """Predicted candles for `ahead` after the candle that is still forming, and the one-candle-ahead
    predictions the model made for the last `history` closed candles."""
    tf = tf if tf in TIMEFRAMES else "15min"
    step_ms, k = TIMEFRAMES[tf], candles_ahead(tf, ahead)
    if not k:
        return {"error": f"'{ahead}' ahead is not offered on {tf} candles", "options": options()}
    model = model or load_model()
    m = (model or {}).get("timeframes", {}).get(tf)
    if m is None or len(m["coef"]) < k + 1:
        return {"error": "no trained model for this timeframe", "options": options()}
    closed = [c for c in candles if int(c["t"]) + step_ms <= now_ms]
    bars = [(int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c["v"])) for c in closed]
    feats = feature_series(bars)
    if not bars or feats[-1] is None:
        return {"error": "not enough candles yet", "options": options()}
    last = len(bars) - 1
    t0, c0, a = bars[last][0], bars[last][4], feats[last][8]
    steps = _predict_steps(m, feats[last])
    live = next((c for c in candles if int(c["t"]) == t0 + step_ms), None)

    def candle(t: int, o: float, y: float, band: List[float]) -> Dict[str, float]:
        c = c0 * math.exp(a * y)
        return {"t": t, "o": o, "c": c, "h": max(o, c) * math.exp(a * m["wick_up"]),
                "l": min(o, c) * math.exp(-a * m["wick_down"]),
                "band_lo": c0 * math.exp(a * (y + band[0])), "band_hi": c0 * math.exp(a * (y + band[1]))}

    out = []
    o = float(live["c"]) if live else c0 * math.exp(a * steps[0])
    for j in range(1, k + 1):
        out.append(candle(t0 + (j + 1) * step_ms, o, steps[j], m["band"][j]))
        o = out[-1]["c"]
    past, hits, moved = [], 0, 0
    for i in range(max(0, last - history), last):
        if feats[i] is None:
            continue
        y1 = _predict_steps(m, feats[i])[0]
        ci, ai = bars[i][4], feats[i][8]
        pc = ci * math.exp(ai * y1)
        p = {"t": bars[i + 1][0], "o": ci, "c": pc, "h": max(ci, pc) * math.exp(ai * m["wick_up"]),
             "l": min(ci, pc) * math.exp(-ai * m["wick_down"])}
        if bars[i + 1][4] != ci:
            moved += 1
            hits += (pc > ci) == (bars[i + 1][4] > ci)
        p["hit"] = (pc > ci) == (bars[i + 1][4] > ci)
        past.append(p)
    mt = {key: v for key, v in m["metrics"].items() if not key.endswith("_by_step")}
    for key in ("hit_by_step", "majority_by_step", "coverage_by_step"):     # the figures for this horizon only
        if key in m["metrics"]:
            mt[key.replace("_by_step", "")] = m["metrics"][key][k]
    return {"tf": tf, "ahead": ahead, "candles_ahead": k, "step_ms": step_ms, "anchor_t": t0, "anchor_close": c0,
            "forecast": out, "past": past, "recent_hit_rate": round(hits / moved, 3) if moved else None,
            "metrics": mt, "trained": (model or {}).get("trained"), "options": options()}
