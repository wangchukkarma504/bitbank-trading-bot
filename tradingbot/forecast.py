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
from typing import Any, Callable, Dict, List, Optional, Sequence

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


BOOST_FEATURES = FEATURES + ("r64", "r128", "r256", "dev200", "hour_sin", "hour_cos", "weekday",
                             "btc_r1", "btc_r4", "btc_r16", "btc_dev20", "btc_atr", "btc_rsi", "btc_pos", "btc_vol")


def boost_features(bars: Sequence[Sequence[float]], btc_bars: Sequence[Sequence[float]]) -> List[Optional[List[float]]]:
    """The 27 patterns of the next-candle model: the 12 above, longer trends, time of day and week, and Bitcoin's
    own patterns at the same moment. Each row uses only that candle and earlier ones."""
    base = feature_series(bars)
    btc = {b[0]: f for b, f in zip(btc_bars, feature_series(btc_bars))}
    closes = [b[4] for b in bars]
    out: List[Optional[List[float]]] = []
    s200 = 0.0
    for i, b in enumerate(bars):
        c = b[4]
        s200 += c - (closes[i - 200] if i >= 200 else 0.0)
        f, g = base[i], btc.get(b[0])
        if f is None or g is None or i < 256 or min(closes[i - 256], closes[i - 128], closes[i - 64]) <= 0:
            out.append(None)
            continue
        hour = (b[0] // 3_600_000) % 24
        out.append(f + [math.log(c / closes[i - 64]), math.log(c / closes[i - 128]), math.log(c / closes[i - 256]),
                        math.log(c / (s200 / 200.0)), math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24),
                        float((b[0] // 86_400_000 + 4) % 7), g[0], g[2], g[4], g[6], g[8], g[9], g[10], g[11]])
    return out


INDICATORS = ("ema9", "ema21", "ema50", "ema100", "ema9_21", "ema21_50", "ema9_slope", "macd", "macd_hist", "bb_pos",
              "bb_width", "stoch_k", "stoch_d", "rsi7", "rsi28", "cci", "adx", "di_diff", "vol_z", "obv_slope",
              "vol_5_50", "body", "wick_up", "wick_down", "prev_body", "run", "range", "atr_ratio", "realized_vol",
              "from_high20", "from_low20", "from_high100", "from_low100")
BOOST_FEATURES_V2 = BOOST_FEATURES + INDICATORS + ("eth_r1", "eth_r4")


def indicator_features(bars: Sequence[Sequence[float]], keep: Optional[Callable[[int], bool]] = None) -> List[Optional[List[float]]]:
    """33 classic indicators per candle, all scale-free (distances in ATRs, oscillators centred on 0), each from that
    candle and the ones before it: EMA 9/21/50/100 distances and crossovers, MACD, Bollinger, Stochastic, RSI 7/28,
    CCI, ADX/DI, volume z-score, OBV slope, candle shape, squeeze, realized volatility, distance from highs and lows."""
    n = len(bars)
    out: List[Optional[List[float]]] = [None] * n
    o_, h_, l_, c_, v_ = ([b[k] for b in bars] for k in (1, 2, 3, 4, 5))
    ema = {p: None for p in (9, 12, 21, 26, 50, 100)}
    sig = None
    atr = atr50 = None
    up7 = dn7 = up28 = dn28 = None
    pdm = ndm = trs = adx = None
    obv = [0.0] * n
    rets: List[float] = []
    macd_prev = []
    k_hist: List[float] = []
    run = 0
    ema9_hist: List[float] = []
    for i in range(n):
        o, h, l, c, v = o_[i], h_[i], l_[i], c_[i], v_[i]
        pc = c_[i - 1] if i else c
        tr = h - l if not i else max(h - l, abs(h - pc), abs(l - pc))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        atr50 = tr if atr50 is None else (atr50 * 49 + tr) / 50
        for p in ema:
            ema[p] = c if ema[p] is None else ema[p] + (c - ema[p]) * 2 / (p + 1)
        macd = ema[12] - ema[26]
        sig = macd if sig is None else sig + (macd - sig) * 2 / 10
        ch = c - pc
        g, d = max(ch, 0.0), max(-ch, 0.0)
        up7 = g if up7 is None else (up7 * 6 + g) / 7
        dn7 = d if dn7 is None else (dn7 * 6 + d) / 7
        up28 = g if up28 is None else (up28 * 27 + g) / 28
        dn28 = d if dn28 is None else (dn28 * 27 + d) / 28
        if i:
            upm, dnm = h - h_[i - 1], l_[i - 1] - l
            p_dm = upm if upm > dnm and upm > 0 else 0.0
            n_dm = dnm if dnm > upm and dnm > 0 else 0.0
            pdm = p_dm if pdm is None else (pdm * 13 + p_dm) / 14
            ndm = n_dm if ndm is None else (ndm * 13 + n_dm) / 14
            trs = tr if trs is None else (trs * 13 + tr) / 14
            dip, dim = (100 * pdm / trs, 100 * ndm / trs) if trs else (0.0, 0.0)
            dx = 100 * abs(dip - dim) / (dip + dim) if dip + dim else 0.0
            adx = dx if adx is None else (adx * 13 + dx) / 14
            obv[i] = obv[i - 1] + (v if c > pc else -v if c < pc else 0.0)
            rets.append(math.log(c / pc) if c > 0 and pc > 0 else 0.0)
        run = (run + 1 if run >= 0 else 1) if ch > 0 else (run - 1 if run <= 0 else -1) if ch < 0 else run
        ema9_hist.append(ema[9])
        lo14, hi14 = min(l_[max(0, i - 13):i + 1]), max(h_[max(0, i - 13):i + 1])
        k_hist.append((c - lo14) / (hi14 - lo14) - 0.5 if hi14 > lo14 else 0.0)
        if i < 120 or (keep is not None and not keep(i)) or c <= 0 or atr <= 0:
            continue
        ap = atr / c                                   # ATR as a share of the price: the unit for distances
        lc = math.log(c)
        w20 = c_[i - 19:i + 1]
        m20 = sum(w20) / 20
        sd20 = math.sqrt(sum((x - m20) ** 2 for x in w20) / 20)
        tp = [(h_[j] + l_[j] + c_[j]) / 3 for j in range(i - 19, i + 1)]
        mtp = sum(tp) / 20
        md = sum(abs(x - mtp) for x in tp) / 20
        vw = v_[i - 19:i + 1]
        mv = sum(vw) / 20
        sdv = math.sqrt(sum((x - mv) ** 2 for x in vw) / 20)
        v5, v50 = sum(v_[i - 4:i + 1]) / 5, sum(v_[i - 49:i + 1]) / 50
        r20 = rets[-20:]
        mr = sum(r20) / 20
        hh20, ll20 = max(h_[i - 19:i + 1]), min(l_[i - 19:i + 1])
        hh100, ll100 = max(h_[i - 99:i + 1]), min(l_[i - 99:i + 1])
        vol10 = sum(v_[i - 9:i + 1])
        cl = lambda x, a=5.0: max(-a, min(a, x))
        out[i] = [
            cl((lc - math.log(ema[9])) / ap), cl((lc - math.log(ema[21])) / ap), cl((lc - math.log(ema[50])) / ap, 15),
            cl((lc - math.log(ema[100])) / ap, 25), cl(math.log(ema[9] / ema[21]) / ap), cl(math.log(ema[21] / ema[50]) / ap, 10),
            cl(math.log(ema[9] / ema9_hist[-4]) / ap), cl(macd / atr), cl((macd - sig) / atr),
            cl((c - (m20 - 2 * sd20)) / (4 * sd20) - 0.5 if sd20 > 0 else 0.0), cl(4 * sd20 / m20 / ap if m20 > 0 else 0.0, 20),
            k_hist[-1], sum(k_hist[-3:]) / 3,
            (100.0 - 100.0 / (1 + up7 / dn7) if dn7 else 100.0) / 100 - 0.5,
            (100.0 - 100.0 / (1 + up28 / dn28) if dn28 else 100.0) / 100 - 0.5,
            cl(((h + l + c) / 3 - mtp) / (0.015 * md) / 100 if md > 0 else 0.0), (adx or 0.0) / 100, (dip - dim) / 100,
            cl((v - mv) / sdv if sdv > 0 else 0.0), cl((obv[i] - obv[i - 10]) / vol10 if vol10 > 0 else 0.0),
            cl(math.log(v5 / v50) if v5 > 0 and v50 > 0 else 0.0), cl((c - o) / atr), cl((h - max(o, c)) / atr),
            cl((min(o, c) - l) / atr), cl((c_[i - 1] - o_[i - 1]) / atr), float(max(-8, min(8, run))), cl((h - l) / atr),
            atr / atr50 if atr50 else 1.0, cl(math.sqrt(sum((x - mr) ** 2 for x in r20) / 20) / ap),
            cl(math.log(hh20 / c) / ap, 20), cl(math.log(c / ll20) / ap, 20), cl(math.log(hh100 / c) / ap, 40),
            cl(math.log(c / ll100) / ap, 40)]
    return out


def boost_features_v2(bars, btc_bars, eth_bars, keep: Optional[Callable[[int], bool]] = None) -> List[Optional[List[float]]]:
    """The 27 patterns of boost_features plus the 33 indicators and Ethereum's last 1 and 4 candles: 62 in all."""
    v1 = boost_features(bars, btc_bars)
    ind = indicator_features(bars, keep)
    eth = {b[0]: f for b, f in zip(eth_bars, feature_series(eth_bars))}
    out: List[Optional[List[float]]] = []
    for i, b in enumerate(bars):
        e = eth.get(b[0])
        out.append(None if v1[i] is None or ind[i] is None or e is None else v1[i] + ind[i] + [e[0], e[2]])
    return out


def boost_p(bm: Dict[str, Any], x: List[float]) -> float:
    """Probability that the next candle closes higher, from the exported boosted trees."""
    raw = bm["base"]
    for tree in bm["trees"]:
        n = 0
        while True:
            feat, thr, miss_left, left, right, leaf, val = tree[n]
            if leaf:
                raw += val
                break
            v = x[feat]
            n = left if ((miss_left if v != v else v <= thr)) else right
    return 1.0 / (1.0 + math.exp(-raw))


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
             history: int = 300, btc_candles: Optional[List[Dict[str, Any]]] = None,
             eth_candles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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

    # The path starts from the live price (the candle now forming) and adds the model's further moves to it, so it
    # does not jump back to the last closed price.
    start = float(live["c"]) if live else c0 * math.exp(a * steps[0])
    shift = math.log(start / c0) / a - steps[0] if a > 0 and c0 > 0 else 0.0
    out = []
    o = start
    for j in range(1, k + 1):
        out.append(candle(t0 + (j + 1) * step_ms, o, steps[j] + shift, m["band"][j]))
        o = out[-1]["c"]
    # The model's candle for every past candle and for the candle now forming: the next-candle model (boosted trees)
    # where it is trained, the ridge regression's first step otherwise. Body = expected move, wicks = typical wicks.
    bm = m.get("boost")
    bx = None
    as_bars = lambda cs: [(int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c["v"]))
                          for c in cs if int(c["t"]) + step_ms <= now_ms]
    if bm and btc_candles is not None:
        btc_bars = as_bars(btc_candles)
        if bm.get("version") == 2:
            if eth_candles is not None:
                lo = max(0, last - history - 1)
                rows = boost_features_v2(bars, btc_bars, as_bars(eth_candles), lambda i: i >= lo)
                bx = [None if r is None else [r[j] for j in bm["cols"]] for r in rows]
        else:
            bx = boost_features(bars, btc_bars)
    past, hits, moved = [], 0, 0
    next_p = None
    for i in range(max(0, last - history), last + 1):
        if feats[i] is None:
            continue
        ci, ai = bars[i][4], feats[i][8]
        if bx is not None and bx[i] is not None:
            pu = boost_p(bm, bx[i])
            y1 = (2.0 * pu - 1.0) * bm["typical_move"]
        else:
            z = [(x - mu) / sd for x, mu, sd in zip(feats[i], m["mean"], m["std"])]
            y1 = m["intercept"][0] + sum(w * x for w, x in zip(m["coef"][0], z))      # first step only: cheap
            pu = None
        pc = ci * math.exp(ai * y1)
        p = {"t": bars[i][0] + step_ms, "o": ci, "c": pc, "h": max(ci, pc) * math.exp(ai * m["wick_up"]),
             "l": min(ci, pc) * math.exp(-ai * m["wick_down"]), "p_up": None if pu is None else round(pu, 4)}
        if i < last:
            if bars[i + 1][4] != ci:
                moved += 1
                hits += (pc > ci) == (bars[i + 1][4] > ci)
            p["hit"] = (pc > ci) == (bars[i + 1][4] > ci)
        else:
            p["hit"] = None                            # the candle now forming: not known yet
            next_p = p["p_up"]
        past.append(p)
    mt = {key: v for key, v in m["metrics"].items() if not key.endswith("_by_step")}
    for key in ("hit_by_step", "majority_by_step", "coverage_by_step"):     # the figures for this horizon only
        if key in m["metrics"]:
            mt[key.replace("_by_step", "")] = m["metrics"][key][k]
    return {"tf": tf, "ahead": ahead, "candles_ahead": k, "step_ms": step_ms, "anchor_t": t0, "anchor_close": c0,
            "forecast": out, "past": past, "recent_hit_rate": round(hits / moved, 3) if moved else None,
            "metrics": mt, "trained": (model or {}).get("trained"), "options": options(),
            "next_candle": {"p_up": next_p, **(bm["metrics"] if bm else {})}}
