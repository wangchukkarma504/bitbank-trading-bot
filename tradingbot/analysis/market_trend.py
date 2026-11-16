"""Market Trend Analyst (Role 3).

Evaluates multi-timeframe trend alignment (15m EMA20/50, 1h EMA50/200, 4h EMA200, 4h EMA30/90),
strictly resolves Bitbank candlestick date parameters (YYYY vs YYYYMMDD), culls in-progress
forming candles, and determines the BTC macro regime filter.
"""

from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Union
import time

from tradingbot.models import Candle, MarketTrendResult, TrendAlignment, RegimeType


TF_SECONDS: Dict[str, int] = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "1hour": 3600,
    "4hour": 14400,
    "8hour": 28800,
    "12hour": 43200,
    "1day": 86400,
    "1week": 604800,
}


def resolve_date_param(timeframe: str, target_date: Optional[Union[datetime, date]] = None) -> str:
    """Strictly resolve the date query string for Bitbank candlestick API.

    - Macro timeframes (>= 4hour): MUST use 4-digit year string 'YYYY'
    - Intraday timeframes (<= 1hour): MUST use 8-digit date string 'YYYYMMDD'
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc)

    if isinstance(target_date, datetime):
        d = target_date.date()
    else:
        d = target_date

    # Macro check: 4hour, 8hour, 12hour, 1day, 1week, 1month
    if TF_SECONDS.get(timeframe, 0) >= 14400 or timeframe in ("4hour", "8hour", "12hour", "1day", "1week", "1month"):
        return str(d.year)
    return d.strftime("%Y%m%d")


def parse_raw_ohlcv(raw_rows: List[Union[list, tuple]]) -> List[Candle]:
    """Parse raw Bitbank OHLCV strings [[o,h,l,c,v,ts_ms], ...] into sorted Candle objects.
    Deduplicates timestamps and sorts chronologically.
    """
    seen = set()
    candles: List[Candle] = []
    for row in raw_rows:
        try:
            ts = int(row[5])
            if ts in seen:
                continue
            seen.add(ts)
            candles.append(
                Candle(
                    timestamp=ts,
                    open=float(row[0]),
                    high=float(row[1]),
                    low=float(row[2]),
                    close=float(row[3]),
                    volume=float(row[4]),
                )
            )
        except (IndexError, ValueError, TypeError):
            continue

    candles.sort(key=lambda c: c.timestamp)
    return candles


def cull_forming_candle(
    candles: List[Candle],
    timeframe: str,
    current_time_sec: Optional[float] = None,
) -> List[Candle]:
    """Cull the currently forming (unclosed) candle to eliminate false indicator flicker.
    Condition: now - candle_ts < tf_seconds (or candle_ts_sec + tf_sec > now_sec).
    """
    if not candles:
        return []
    if current_time_sec is None:
        current_time_sec = time.time()

    tf_sec = TF_SECONDS.get(timeframe, 3600)
    last = candles[-1]
    last_ts_sec = last.timestamp / 1000.0

    if (current_time_sec - last_ts_sec) < tf_sec:
        return candles[:-1]
    return list(candles)


def calc_ema_series(values: List[float], period: int) -> List[float]:
    """Compute Exponential Moving Average series using Simple Moving Average seed."""
    if not values:
        return []
    if period <= 0:
        raise ValueError(f"Period must be positive, got {period}")

    effective_period = min(period, len(values))
    k = 2.0 / (period + 1)

    # Initial SMA seed
    sma_seed = sum(values[:effective_period]) / effective_period
    ema_series = [sma_seed] * effective_period

    curr = sma_seed
    for val in values[effective_period:]:
        curr = val * k + curr * (1.0 - k)
        ema_series.append(curr)

    return ema_series


def calc_ema(values: List[float], period: int) -> Optional[float]:
    """Compute current EMA value for a sequence of values."""
    series = calc_ema_series(values, period)
    return series[-1] if series else None


def evaluate_btc_macro_regime(
    btc_4h_candles: List[Candle],
) -> Tuple[bool, str, Dict[str, float]]:
    """Evaluates whether BTC is in a Bull or Bear macro regime.

    BULL REGIME: BTC Price > 4h EMA200 AND 4h EMA30 > 4h EMA90.
    BEAR REGIME: BTC Price < 4h EMA200 OR 4h EMA30 < 4h EMA90.
    """
    if not btc_4h_candles:
        return False, RegimeType.BEAR.value, {}

    closes = [c.close for c in btc_4h_candles]
    last_close = closes[-1]
    ema30 = calc_ema(closes, 30) or last_close
    ema90 = calc_ema(closes, 90) or last_close
    ema200 = calc_ema(closes, 200) or last_close

    is_bull = (last_close > ema200) and (ema30 > ema90)
    regime = RegimeType.BULL.value if is_bull else RegimeType.BEAR.value
    metrics = {
        "btc_close": last_close,
        "btc_ema30": ema30,
        "btc_ema90": ema90,
        "btc_ema200": ema200,
    }
    return is_bull, regime, metrics


class MarketTrendAnalyst:
    """Role 3: Market Trend Analyst.

    Orchestrates multi-timeframe trend evaluation and BTC macro filtering.
    """

    def __init__(self, bitbank_client=None):
        self.client = bitbank_client
        # Cache raw rows keyed by (id(client), pair, timeframe, date_str) -> (fetched_at_ts, rows)
        self._candle_cache: Dict[Tuple[int, str, str, str], Tuple[float, List[Union[list, tuple]]]] = {}

    def _get_cached_or_fetch_rows(
        self,
        active_client,
        pair: str,
        timeframe: str,
        date_str: str,
        ttl_sec: float,
    ) -> List[Union[list, tuple]]:
        """Fetch OHLCV rows with a client-scoped TTL cache to eliminate rate-limit 10009 errors."""
        cache_key = (id(active_client), pair, timeframe, date_str)
        now_ts = time.time()
        cached = self._candle_cache.get(cache_key)
        if cached is not None:
            fetched_ts, cached_rows = cached
            if (now_ts - fetched_ts) < ttl_sec:
                return cached_rows

        rows = active_client.candles(pair, timeframe, date_str)
        if rows:
            self._candle_cache[cache_key] = (now_ts, rows)
        return rows

    def fetch_candles(
        self,
        pair: str,
        timeframe: str,
        days: int = 3,
        cull_forming: bool = True,
        client=None,
    ) -> List[Candle]:
        """Fetch historical candles from Bitbank with strict date format resolution and TTL caching."""
        active_client = client or self.client
        if active_client is None:
            raise ValueError("Bitbank client is required to fetch remote candles")

        now = datetime.now(timezone.utc)
        raw_rows: List[Union[list, tuple]] = []

        if TF_SECONDS.get(timeframe, 0) >= 14400 or timeframe in ("4hour", "8hour", "12hour", "1day"):
            # Fetch for current year and previous year to guarantee >= 200 bars for EMA200
            years = [now.year - 1, now.year]
            for y in years:
                ttl = 3600.0 if y < now.year else 90.0
                try:
                    rows = self._get_cached_or_fetch_rows(active_client, pair, timeframe, str(y), ttl)
                    raw_rows.extend(rows)
                except Exception:
                    continue
        else:
            # Intraday: query day-by-day with YYYYMMDD; past days are immutable (cache 3600s)
            fetch_days = max(1, days)
            today_str = now.strftime("%Y%m%d")
            ttl_today = 15.0 if timeframe in ("1min", "5min", "15min") else 45.0
            for d in range(fetch_days, -1, -1):
                day_dt = now - timedelta(days=d)
                day_str = resolve_date_param(timeframe, day_dt)
                ttl = ttl_today if day_str == today_str else 3600.0
                try:
                    rows = self._get_cached_or_fetch_rows(active_client, pair, timeframe, day_str, ttl)
                    raw_rows.extend(rows)
                except Exception:
                    continue

        candles = parse_raw_ohlcv(raw_rows)
        if cull_forming:
            candles = cull_forming_candle(candles, timeframe)
        return candles

    def evaluate_btc_regime(
        self,
        btc_candles_4h: Optional[List[Candle]] = None,
        client=None,
    ) -> bool:
        """Check whether BTC macro regime is bullish."""
        active_client = client or self.client
        if btc_candles_4h is None and active_client is not None:
            btc_candles_4h = self.fetch_candles("btc_jpy", "4hour", cull_forming=True, client=active_client)

        if not btc_candles_4h:
            return False

        is_bull, _, _ = evaluate_btc_macro_regime(btc_candles_4h)
        return is_bull

    def analyze(
        self,
        pair: str,
        timeframe: str = "4hour",
        candles: Optional[List[Candle]] = None,
        btc_regime_bullish: Optional[bool] = None,
        client=None,
    ) -> MarketTrendResult:
        """Analyze trend alignment for a specific pair and timeframe."""
        active_client = client or self.client
        if candles is None:
            if active_client is None:
                raise ValueError("Must provide either candles or an active Bitbank client")
            days = 20 if timeframe == "1hour" else (3 if timeframe == "15min" else 30)
            candles = self.fetch_candles(pair, timeframe, days=days, cull_forming=True, client=active_client)

        if not candles:
            return MarketTrendResult(
                pair=pair,
                timeframe=timeframe,
                ema20=0.0,
                ema50=0.0,
                ema200=0.0,
                trend_alignment=TrendAlignment.NEUTRAL.value,
                btc_regime_bullish=bool(btc_regime_bullish),
                close=0.0,
                score=0.0,
            )

        closes = [c.close for c in candles]
        last_close = closes[-1]

        ema20 = calc_ema(closes, 20) or last_close
        ema50 = calc_ema(closes, 50) or last_close
        ema200 = calc_ema(closes, 200) or last_close
        ema30 = calc_ema(closes, 30) or last_close
        ema90 = calc_ema(closes, 90) or last_close

        if btc_regime_bullish is None:
            if active_client is not None and pair != "btc_jpy":
                btc_regime_bullish = self.evaluate_btc_regime(client=active_client)
            elif pair == "btc_jpy" and timeframe == "4hour":
                btc_regime_bullish, _, _ = evaluate_btc_macro_regime(candles)
            elif active_client is not None:
                btc_regime_bullish = self.evaluate_btc_regime(client=active_client)
            else:
                btc_regime_bullish = False

        alignment = TrendAlignment.NEUTRAL.value
        score = 0.0

        if timeframe == "15min":
            # 15m focus: EMA20 & EMA50
            if last_close > ema20 > ema50:
                alignment = TrendAlignment.BULLISH.value
                score = 1.0
            elif last_close < ema20 < ema50:
                alignment = TrendAlignment.BEARISH.value
                score = -1.0
            else:
                alignment = TrendAlignment.NEUTRAL.value
                score = 0.0

        elif timeframe == "1hour":
            # 1h focus: EMA50 & EMA200
            if last_close > ema50 > ema200:
                alignment = TrendAlignment.BULLISH.value
                score = 1.5
            elif last_close < ema50 < ema200:
                alignment = TrendAlignment.BEARISH.value
                score = -1.5
            else:
                alignment = TrendAlignment.NEUTRAL.value
                score = 0.0

        else:
            # 4h / macro focus: EMA200, EMA30, EMA90
            if last_close > ema200 and ema30 > ema90:
                alignment = TrendAlignment.BULLISH.value
                score = 2.0
            elif last_close < ema200 and ema30 < ema90:
                alignment = TrendAlignment.BEARISH.value
                score = -2.0
            elif last_close > ema200:
                alignment = TrendAlignment.BULLISH.value
                score = 0.8
            elif last_close < ema200:
                alignment = TrendAlignment.BEARISH.value
                score = -0.8
            else:
                alignment = TrendAlignment.NEUTRAL.value
                score = 0.0

        return MarketTrendResult(
            pair=pair,
            timeframe=timeframe,
            ema20=round(ema20, 4),
            ema50=round(ema50, 4),
            ema200=round(ema200, 4),
            trend_alignment=alignment,
            btc_regime_bullish=btc_regime_bullish,
            ema30=round(ema30, 4),
            ema90=round(ema90, 4),
            close=round(last_close, 4),
            score=score,
        )

    def analyze_multi_timeframe(
        self,
        pair: str,
        custom_candles_map: Optional[Dict[str, List[Candle]]] = None,
        client=None,
    ) -> Dict[str, MarketTrendResult]:
        """Produce multi-timeframe analysis across 15m, 1h, and 4h."""
        active_client = client or self.client
        results: Dict[str, MarketTrendResult] = {}

        btc_regime = None
        if custom_candles_map and "btc_4h" in custom_candles_map:
            btc_regime, _, _ = evaluate_btc_macro_regime(custom_candles_map["btc_4h"])

        for tf in ("15min", "1hour", "4hour"):
            candles = custom_candles_map.get(tf) if custom_candles_map else None
            result = self.analyze(
                pair=pair,
                timeframe=tf,
                candles=candles,
                btc_regime_bullish=btc_regime,
                client=active_client,
            )
            results[tf] = result
            if btc_regime is None and result.btc_regime_bullish is not None:
                btc_regime = result.btc_regime_bullish

        return results
