"""Market Analysis Engine exports (Roles 3, 4, 5)."""

from tradingbot.analysis.market_trend import (
    MarketTrendAnalyst,
    calc_ema,
    calc_ema_series,
    cull_forming_candle,
    evaluate_btc_macro_regime,
    parse_raw_ohlcv,
    resolve_date_param,
)
from tradingbot.analysis.wick_anatomy import (
    WickAnatomyAnalyst,
    calc_recommended_entry,
    calc_rolling_wick_ratio,
    classify_candle,
    decompose_candle,
    detect_exhaustion,
)
from tradingbot.analysis.technical_depth import (
    TechnicalDepthAnalyst,
    analyze_order_book,
    calc_rsi,
    calc_rsi_series,
    detect_rsi_divergence,
    parse_order_book_levels,
)

__all__ = [
    # Role 3: Market Trend Analyst
    "MarketTrendAnalyst",
    "calc_ema",
    "calc_ema_series",
    "cull_forming_candle",
    "evaluate_btc_macro_regime",
    "parse_raw_ohlcv",
    "resolve_date_param",
    # Role 4: Wick & Candlestick Anatomy Analyst
    "WickAnatomyAnalyst",
    "calc_recommended_entry",
    "calc_rolling_wick_ratio",
    "classify_candle",
    "decompose_candle",
    "detect_exhaustion",
    # Role 5: Technical & Order Book Analyst
    "TechnicalDepthAnalyst",
    "analyze_order_book",
    "calc_rsi",
    "calc_rsi_series",
    "detect_rsi_divergence",
    "parse_order_book_levels",
]
