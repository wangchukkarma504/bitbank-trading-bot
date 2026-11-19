"""Can machine learning pick the better breakouts? A walk-forward test.

The live rule (tradingbot/strategy.py) buys every 20-day breakout. This script asks whether a model can tell
in advance which breakouts are worth taking, using only what is known when the signal candle closes:

  1. Replay 2017-2026 with no limit on open positions, so every breakout gets its own result in R.
  2. Describe each breakout by 19 patterns: volatility, breakout strength, momentum over 7/30/90 days, trend
     against the 50- and 200-day averages, volume, candle shape, distance from the 1-year high, RSI,
     Bitcoin's trend, how many coins are in an uptrend, how many broke out in the last week, and so on.
  3. Walk forward one year at a time from 2019: train only on trades that had closed before that year began,
     then score that year's breakouts. Nothing from the year being scored is used.
  4. Replay the real portfolio (3 positions, 2% risk) taking only the breakouts the model rates above the
     30th percentile of its training scores. Compare with taking all of them, and with skipping the same
     share of breakouts at random (skipping alone changes the results, so the model must beat chance).

The bot does not use this. It would only be added if a model beats both comparisons on the unseen years,
before and after 2023.

    pip install numpy scikit-learn
    python3 research/ml_filter.py [--cache candle_cache] [--offline]
"""

import argparse
import bisect
from datetime import datetime
import os
import random
import sys
from typing import Dict, List, Set, Tuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tradingbot import backtest as bt, strategy  # noqa: E402
from tradingbot.strategy import BAR_MS, Params  # noqa: E402

SKIP_SHARE = 0.30          # the model skips breakouts scored below this quantile of its training scores
FIRST_TEST_YEAR = 2019     # 2017-2018 only train
SPLIT_YEAR = 2023          # results are shown before and after this year separately
RANDOM_RUNS = 30
FEATURES = ("atr", "break", "mom7", "mom30", "mom90", "trend50", "trend200", "vol_bar", "vol_day", "squeeze",
            "range_pos", "body", "days_since", "from_1y_high", "rsi", "btc_trend50", "btc_mom7", "breadth",
            "breaks_7d")
Key = Tuple[int, float]    # (close time of the signal candle, its close): identifies a breakout


def year_ms(y: int) -> int:
    return int(datetime(y, 1, 1, tzinfo=bt.JST).timestamp() * 1000)


def load(pair: str, cache: str, net: bool) -> Tuple[np.ndarray, np.ndarray]:
    rows: List[list] = []
    for y in range(2017, datetime.now(bt.JST).year + 1):
        rows += bt.fetch_rows(pair, "4hour", str(y), cache, allow_network=net)
    d = {int(r[5]): r for r in rows}
    ts = np.array(sorted(d), dtype=np.int64)
    a = np.array([[float(d[t][k]) for k in range(5)] for t in ts]) if len(ts) else np.zeros((0, 5))
    return ts, a


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty(len(x))
    if len(x):
        out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def lag(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def rolling_max(x: np.ndarray, n: int, include_current: bool) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > n:
        m = sliding_window_view(x, n).max(axis=1)
        if include_current:
            out[n - 1:] = m
        else:
            out[n:] = m[:-1]
    return out


def pair_features(ts: np.ndarray, a: np.ndarray, p: Params) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Features of every candle of one coin, each using only that candle and the ones before it."""
    o, h, l, c, v = a.T
    with np.errstate(divide="ignore", invalid="ignore"):
        prev_c = lag(c, 1)
        tr = np.where(np.isnan(prev_c), h - l, np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c))))
        atr14, atr100 = wilder(tr, p.atr_bars), wilder(tr, 100)
        chan = rolling_max(h, p.channel_bars, include_current=False)
        raw = np.zeros(len(c), dtype=bool)
        ok = ~np.isnan(chan)
        raw[ok] = c[ok] > chan[ok]
        up, dn = wilder(np.clip(np.diff(c, prepend=c[0]), 0, None), 14), wilder(np.clip(-np.diff(c, prepend=c[0]), 0, None), 14)
        days_since = np.full(len(c), 60.0)
        last = None
        for i in np.flatnonzero(raw):
            if last is not None:
                days_since[i] = min(60.0, (i - last) / 6.0)
            last = i
        f = {
            "atr": atr14 / c,
            "break": c / chan - 1.0,
            "mom7": c / lag(c, 42) - 1.0,
            "mom30": c / lag(c, 180) - 1.0,
            "mom90": c / lag(c, 540) - 1.0,
            "trend50": c / sma(c, 300) - 1.0,
            "trend200": c / sma(c, 1200) - 1.0,
            "vol_bar": v / lag(sma(v, 30), 1),
            "vol_day": sma(v, 6) / lag(sma(v, 180), 6),
            "squeeze": atr14 / atr100,
            "range_pos": np.where(h > l, (c - l) / (h - l), np.nan),
            "body": (c - o) / atr14,
            "days_since": days_since,
            "from_1y_high": c / rolling_max(h, 2190, include_current=True) - 1.0,
            "rsi": np.where(dn > 0, 100.0 - 100.0 / (1.0 + up / dn), 100.0),
        }
    for k in f:
        f[k] = np.where(np.isfinite(f[k]), f[k], np.nan)
    return f, raw


def build(cache: str, net: bool, p: Params):
    data = {pair: load(pair, cache, net) for pair in bt.PAIRS}
    feats = {pair: pair_features(ts, a, p) for pair, (ts, a) in data.items()}
    index = {pair: {int(t): i for i, t in enumerate(ts)} for pair, (ts, _) in data.items()}
    signals = sorted(int(data[pair][0][i]) for pair in bt.PAIRS for i in np.flatnonzero(feats[pair][1]))
    warmup = p.channel_bars + 5 * p.atr_bars
    rows, keys, owners = [], [], []
    for pair, (ts, a) in data.items():
        f, raw = feats[pair]
        for i in np.flatnonzero(raw):
            if i < warmup:
                continue
            t = int(ts[i])
            bi = index["btc_jpy"].get(t)
            btc = feats["btc_jpy"][0]
            trends = [feats[q][0]["trend50"][index[q][t]] for q in bt.PAIRS if t in index[q]]
            trends = [x for x in trends if not np.isnan(x)]
            x = [f[name][i] for name in FEATURES[:15]] + [
                btc["trend50"][bi] if bi is not None else np.nan,
                btc["mom7"][bi] if bi is not None else np.nan,
                float(np.mean([x > 0 for x in trends])) if trends else np.nan,
                float(bisect.bisect_left(signals, t) - bisect.bisect_left(signals, t - 42 * BAR_MS)),
            ]
            rows.append(x)
            keys.append((t + BAR_MS, float(a[i, 3])))
            owners.append(pair)
    bars = {pair: [(int(t), *map(float, a[i, :4])) for i, t in enumerate(ts)] for pair, (ts, a) in data.items()}
    return np.array(rows, dtype=float), keys, owners, bars


def replay_skipping(bars, p: Params, start: int, end: int, skip: Set[Key]):
    """The production replay, with the breakouts in `skip` not taken."""
    original = strategy.signal
    strategy.signal = lambda s, q: original(s, q) and (s.ts, s.close) not in skip
    try:
        return bt.replay(bars, p, start, end)
    finally:
        strategy.signal = original


MODELS = {
    "logistic regression (win?)": (lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                                          LogisticRegression(C=0.5, max_iter=5000)), "win"),
    "boosted trees (win?)": (lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                                    min_samples_leaf=25, l2_regularization=1.0,
                                                                    random_state=0), "win"),
    "boosted trees (size of R)": (lambda: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200,
                                                                        min_samples_leaf=25, l2_regularization=1.0,
                                                                        random_state=0), "r"),
}


def score(model, X: np.ndarray, target: str) -> np.ndarray:
    return model.predict_proba(X)[:, 1] if target == "win" else model.predict(X)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default="candle_cache")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    p = Params()
    X, keys, owners, bars = build(args.cache, not args.offline, p)
    close_ts = np.array([k[0] for k in keys])
    end = max(b[-1][0] for b in bars.values() if b) + BAR_MS
    start_all = min(b[0][0] for b in bars.values() if b)

    # 1. every breakout's own result (no limit on positions)
    outcome = {(t.pair, t.signal_ts): t for t in bt.replay(bars, Params(max_positions=99), start_all, end)}
    r = np.array([outcome[(o, k[0])].r if (o, k[0]) in outcome else np.nan for o, k in zip(owners, keys)])
    exit_ts = np.array([outcome[(o, k[0])].exit_ts if (o, k[0]) in outcome else 0 for o, k in zip(owners, keys)])
    labelled = ~np.isnan(r)
    print(f"Breakout candles 2017-2026: {len(keys)}; {labelled.sum()} of them opened a trade in the unlimited replay "
          f"({np.mean(r[labelled] > 0) * 100:.0f}% winners, average {np.nanmean(r):+.2f}R).")

    # 2. walk forward
    last_year = datetime.fromtimestamp(end / 1000, bt.JST).year
    years = range(FIRST_TEST_YEAR, last_year + 1)
    results = {}
    for name, (make, target) in MODELS.items():
        sc = np.full(len(keys), np.nan)
        keep = np.ones(len(keys), dtype=bool)
        for y in years:
            train = labelled & (exit_ts < year_ms(y))
            test = (close_ts >= year_ms(y)) & (close_ts < year_ms(y + 1))
            if train.sum() < 50 or not test.any():
                continue
            yv = (r[train] > 0).astype(int) if target == "win" else np.clip(r[train], -1.5, 5.0)
            m = make().fit(X[train], yv)
            sc[test] = score(m, X[test], target)
            keep[test] = sc[test] >= np.quantile(score(m, X[train], target), SKIP_SHARE)
        results[name] = (sc, keep)

    def period_mask(a: int, b: int) -> np.ndarray:
        return (close_ts >= year_ms(a)) & (close_ts < (year_ms(b) if b else end + 1))

    periods = (("2019-2022", FIRST_TEST_YEAR, SPLIT_YEAR), ("2023-2026", SPLIT_YEAR, None))
    print("\n1) On years it had not seen: does the model separate good breakouts from bad ones?")
    print(f"   {'model':28s}" + "".join(f" | {lbl}: AUC  avg R kept / skipped" for lbl, _, _ in periods))
    for name, (sc, keep) in results.items():
        line = f"   {name:28s}"
        for _, a, b in periods:
            mk = period_mask(a, b) & labelled & ~np.isnan(sc)
            auc = roc_auc_score(r[mk] > 0, sc[mk]) if len(set(r[mk] > 0)) > 1 else float("nan")
            kept, skipped = r[mk & keep], r[mk & ~keep]
            line += (f" | {'':9s} {auc:.2f}  {np.mean(kept):+.2f}R ({len(kept)}) / "
                     f"{(np.mean(skipped) if len(skipped) else float('nan')):+.2f}R ({len(skipped)})")
        print(line)

    print("\n2) The real portfolio (3 positions, 2% risk per trade) on the same unseen years")
    spans = (("2019-2022", year_ms(FIRST_TEST_YEAR), year_ms(SPLIT_YEAR)), ("2023-2026", year_ms(SPLIT_YEAR), end),
             ("2019-2026", year_ms(FIRST_TEST_YEAR), end))
    print(f"   {'':34s}" + "".join(f" | {lbl}: trades  avg R  growth/yr  worst DD" for lbl, _, _ in spans))

    def row(label: str, skip: Set[Key]) -> List[Dict[str, float]]:
        out = []
        line = f"   {label:34s}"
        for _, a, b in spans:
            s = bt.summary(replay_skipping(bars, p, a, b, skip), p, a, b)
            out.append(s)
            line += (f" | {'':9s} {s['trades']:4d}  {s['avg_r']:+.2f}R  {s['cagr'] * 100:+6.1f}%  "
                     f"{s['max_dd'] * 100:5.1f}%")
        print(line)
        return out

    base = row("take every breakout (the bot today)", set())
    model_rows = {name: row(f"ML filter: {name}", {k for k, kp in zip(keys, keep) if not kp})
                  for name, (_, keep) in results.items()}
    rng = random.Random(7)
    eval_keys = [k for k in keys if k[0] >= year_ms(FIRST_TEST_YEAR)]
    rand = []
    for _ in range(RANDOM_RUNS):
        skip = {k for k in eval_keys if rng.random() < SKIP_SHARE}
        rand.append([bt.summary(replay_skipping(bars, p, a, b, skip), p, a, b) for _, a, b in spans])
    line = f"   {f'skip 30% at random (avg of {RANDOM_RUNS})':34s}"
    for j in range(len(spans)):
        line += (f" | {'':9s} {np.mean([x[j]['trades'] for x in rand]):4.0f}  {np.mean([x[j]['avg_r'] for x in rand]):+.2f}R  "
                 f"{np.mean([x[j]['cagr'] for x in rand]) * 100:+6.1f}%  {np.mean([x[j]['max_dd'] for x in rand]) * 100:5.1f}%")
    print(line)

    print("\n3) Verdict (a model is used only if it beats both comparisons in both periods)")
    for name, rows_ in model_rows.items():
        wins = []
        for j in range(2):
            better_than_all = rows_[j]["cagr"] > base[j]["cagr"]
            pct = np.mean([rows_[j]["cagr"] > x[j]["cagr"] for x in rand]) * 100
            wins.append(better_than_all and pct >= 90)
            print(f"   {name:28s} {spans[j][0]}: growth {rows_[j]['cagr'] * 100:+.1f}% vs all {base[j]['cagr'] * 100:+.1f}%,"
                  f" beats {pct:.0f}% of random skips")
        print(f"   -> {'PASSES' if all(wins) else 'does not pass'}")

    # 4. which patterns the trees lean on (trained before 2023, measured on 2023-2026)
    make, target = MODELS["boosted trees (win?)"]
    train = labelled & (exit_ts < year_ms(SPLIT_YEAR))
    test = labelled & (close_ts >= year_ms(SPLIT_YEAR))
    m = make().fit(X[train], (r[train] > 0).astype(int))
    imp = permutation_importance(m, X[test], (r[test] > 0).astype(int), scoring="roc_auc", n_repeats=20, random_state=0)
    order = np.argsort(-imp.importances_mean)
    print("\n4) Patterns the boosted trees used most (drop in AUC on 2023-2026 when the pattern is shuffled)")
    print("   " + ", ".join(f"{FEATURES[i]} {imp.importances_mean[i]:+.3f}" for i in order[:6]))


if __name__ == "__main__":
    main()
