"""Experimental price forecast for the dashboard's Prediction page. It never places or changes an order.

A ridge regression, one per timeframe, trained by research/train_forecast.py on Bitbank candles of all five
coins. From the candles up to the last closed one it predicts where the close will be after 1, 2, ... n more
candles, in units of the coin's current volatility (ATR), plus a band the price stayed inside 80% of the time
on held-out data. The same feature code is used for training and here, so what was tested is what is shown.

    5-minute chart  ->  the next 12 candles (1 hour)
    15-minute chart ->  the next 8 candles (2 hours)
    1-hour chart    ->  the next 8 candles (8 hours)
    4-hour chart    ->  the next 6 candles (1 day)
"""

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forecast_model.json")
HORIZONS = {   # chart timeframe -> (timeframe, candle length in ms, candles predicted)
    "5min": ("5min", 300_000, 12),
    "15min": ("15min", 900_000, 8),
    "1hour": ("1hour", 3_600_000, 8),
    "4hour": ("4hour", 14_400_000, 6),
}
OLD_NAMES = {"1h": "15min", "4h": "1hour", "1d": "4hour"}
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


def forecast(candles: List[Dict[str, Any]], horizon: str, now_ms: int, model: Optional[Dict[str, Any]] = None,
             history: int = 40) -> Dict[str, Any]:
    """Predicted candles after the last closed candle, and the one-step predictions the model made for the
    last `history` candles (so the page can show how close they came)."""
    horizon = OLD_NAMES.get(horizon, horizon)
    tf, step_ms, n = HORIZONS.get(horizon, HORIZONS["15min"])
    model = model or load_model()
    m = (model or {}).get("timeframes", {}).get(tf)
    if m is None:
        return {"error": "no trained model for this timeframe"}
    closed = [k for k in candles if int(k["t"]) + step_ms <= now_ms]
    bars = [(int(k["t"]), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])) for k in closed]
    feats = feature_series(bars)
    if not bars or feats[-1] is None:
        return {"error": "not enough candles yet"}

    def candles_from(i: int, steps: List[float]) -> List[Dict[str, float]]:
        c0, a = bars[i][4], feats[i][8]
        out, o = [], c0
        for k, y in enumerate(steps):
            c = c0 * math.exp(a * y)
            out.append({"t": bars[i][0] + (k + 1) * step_ms, "o": o, "c": c,
                        "h": max(o, c) * math.exp(a * m["wick_up"]), "l": min(o, c) * math.exp(-a * m["wick_down"]),
                        "band_lo": c0 * math.exp(a * (y + m["band"][k][0])),
                        "band_hi": c0 * math.exp(a * (y + m["band"][k][1]))})
            o = c
        return out

    last = len(bars) - 1
    future = candles_from(last, _predict_steps(m, feats[last]))
    past, hits = [], 0
    for i in range(max(0, last - history), last):
        if feats[i] is None:
            continue
        p = candles_from(i, _predict_steps(m, feats[i])[:1])[0]
        actual = bars[i + 1]
        said_up, went_up = p["c"] > bars[i][4], actual[4] > bars[i][4]
        if actual[4] != bars[i][4]:
            hits += said_up == went_up
        past.append(dict(p, hit=said_up == went_up))
    return {"horizon": horizon, "tf": tf, "step_ms": step_ms, "anchor_t": bars[last][0], "anchor_close": bars[last][4],
            "forecast": future, "past": past,
            "recent_hit_rate": round(hits / len(past), 3) if past else None,
            "metrics": m["metrics"], "trained": (model or {}).get("trained")}
