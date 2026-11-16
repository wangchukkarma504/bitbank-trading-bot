"""Live Macro & Catalyst Predictor (Market Intelligence Context).

Polls live macro/crypto news RSS feeds and the Crypto Fear & Greed Index to detect
high-impact market-moving catalysts (e.g., major tech/crypto executive resignations,
NVIDIA/AI shocks, Fed rate surprises, CPI prints, SEC actions, ETF flows, exchange hacks).

Produces probabilistic market direction context and displays it on the dashboard.
Headlines provide macro context and conviction weighting alongside technicals,
never bypassing core regime gates or risk limits.
"""

from dataclasses import dataclass, field
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import requests


FEEDS: Dict[str, str] = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "CNBC_Tech": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",
    "CNBC_Finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
}

USER_AGENT = {"User-Agent": "Mozilla/5.0 (BitbankTradingBot/2.0 MacroIntel)"}

# Weighted probabilistic catalyst keywords: (keyword_phrase, weight, rationale)
# Negative weight = Bearish / Risk-Off probability; Positive weight = Bullish / Risk-On probability.
BEARISH_CATALYSTS: List[Tuple[str, float, str]] = [
    ("ceo resign", -0.45, "Major executive resignation shock -> elevated risk-off selloff probability"),
    ("ceo steps down", -0.45, "Executive departure uncertainty -> heightened volatility & downside bias"),
    ("nvidia", -0.15, "NVIDIA/AI sector bellwether headline -> high equity-to-crypto correlation"),
    ("sec sues", -0.40, "Regulatory enforcement action -> bearish crypto sentiment"),
    ("lawsuit", -0.25, "Legal/regulatory overhang -> risk-off pressure"),
    ("hack", -0.45, "Security breach / exploit -> acute liquidity & confidence shock"),
    ("exploited", -0.40, "Protocol exploit -> risk-off contagion risk"),
    ("insolven", -0.50, "Insolvency risk -> severe systemic downside probability"),
    ("bankrupt", -0.50, "Bankruptcy event -> risk-off contagion"),
    ("rate hike", -0.35, "Hawkish monetary policy -> tightening liquidity"),
    ("hawkish", -0.30, "Hawkish central bank tone -> bearish risk assets"),
    ("inflation surges", -0.35, "Hot inflation print -> delayed rate cuts"),
    ("hotter than expected", -0.30, "Macro data beat to upside on inflation -> risk-off"),
    ("etf outflow", -0.30, "Institutional ETF outflows -> net selling pressure"),
    ("liquidation", -0.25, "Cascading margin liquidations -> downward momentum"),
    ("crash", -0.30, "Market crash / sharp selloff in progress"),
    ("plunge", -0.25, "Sharp downside price acceleration"),
    ("tariff", -0.20, "Trade/tariff friction -> macro risk-off"),
    ("war", -0.30, "Geopolitical escalation -> flight to safety"),
    ("ban", -0.30, "Regulatory ban threat -> bearish crypto pressure"),
]

BULLISH_CATALYSTS: List[Tuple[str, float, str]] = [
    ("etf inflow", 0.35, "Strong institutional ETF inflows -> net spot demand"),
    ("etf approv", 0.45, "ETF approval catalyst -> structural bullish inflow"),
    ("rate cut", 0.35, "Dovish monetary easing -> expanding liquidity"),
    ("dovish", 0.30, "Dovish central bank guidance -> risk-on tailwind"),
    ("inflation cools", 0.30, "Cooling inflation -> higher probability of rate cuts"),
    ("strategic reserve", 0.40, "Sovereign/institutional reserve adoption -> strong bullish catalyst"),
    ("institutional adoption", 0.25, "Institutional capital entry -> bullish demand"),
    ("all-time high", 0.20, "Breakout momentum -> trend continuation"),
    ("short squeeze", 0.25, "Short covering acceleration -> upside squeeze"),
    ("beats expectations", 0.20, "Strong macro/earnings beat -> risk-on sentiment"),
]


@dataclass
class CatalystEvent:
    source: str
    headline: str
    impact_score: float
    rationale: str


@dataclass
class MacroCatalystReport:
    fear_and_greed_value: int = 50
    fear_and_greed_label: str = "Neutral"
    catalyst_bias: str = "NEUTRAL"  # "BEARISH", "BULLISH", "NEUTRAL"
    catalyst_score: float = 0.0     # Clamped [-1.0, +1.0]
    events: List[CatalystEvent] = field(default_factory=list)
    prediction_summary: str = "No major macro shocks detected; follow technical trend."
    timestamp: float = 0.0


def score_headlines(headlines: List[Tuple[str, str]]) -> Tuple[float, List[CatalystEvent]]:
    """Score a list of (source, title) headlines using probabilistic catalyst weights."""
    total_score = 0.0
    events: List[CatalystEvent] = []

    for source, title in headlines:
        lower = title.lower()
        event_score = 0.0
        matched_rationales: List[str] = []

        for kw, weight, rationale in BEARISH_CATALYSTS:
            if kw in lower:
                event_score += weight
                matched_rationales.append(rationale)

        for kw, weight, rationale in BULLISH_CATALYSTS:
            if kw in lower:
                event_score += weight
                matched_rationales.append(rationale)

        if abs(event_score) >= 0.20:
            # Cap single-headline contribution at [-0.65, +0.65]
            capped = max(-0.65, min(0.65, event_score))
            total_score += capped
            events.append(
                CatalystEvent(
                    source=source,
                    headline=title,
                    impact_score=round(capped, 2),
                    rationale=matched_rationales[0] if matched_rationales else "Macro catalyst",
                )
            )

    # Sort strongest absolute impact first
    events.sort(key=lambda e: abs(e.impact_score), reverse=True)
    clamped_total = max(-1.0, min(1.0, round(total_score, 2)))
    return clamped_total, events[:5]


class MacroCatalystAnalyst:
    """Fetches and caches live Fear & Greed + RSS news catalysts for market predictions."""

    CACHE_TTL_SEC: float = 300.0  # Refresh every 5 minutes

    def __init__(self, cache_ttl_sec: float = 300.0):
        self.cache_ttl_sec = cache_ttl_sec
        self._cached_report: Optional[MacroCatalystReport] = None
        self._last_fetch_ts: float = 0.0

    def fetch_fear_and_greed(self) -> Tuple[int, str]:
        """Fetch latest Crypto Fear & Greed Index."""
        try:
            resp = requests.get(
                "https://api.alternative.me/fng/",
                params={"limit": 1},
                headers=USER_AGENT,
                timeout=5,
            )
            data = resp.json().get("data", [])
            if data:
                return int(data[0]["value"]), str(data[0]["value_classification"])
        except Exception:
            pass
        return 50, "Neutral"

    def fetch_headlines(self, per_feed: int = 5) -> List[Tuple[str, str]]:
        """Fetch latest headlines across crypto & macro/tech RSS feeds."""
        out: List[Tuple[str, str]] = []
        for name, url in FEEDS.items():
            try:
                resp = requests.get(url, headers=USER_AGENT, timeout=5)
                root = ET.fromstring(resp.content)
                count = 0
                for item in root.iter("item"):
                    title = (item.findtext("title") or "").strip()
                    if title:
                        out.append((name, title))
                        count += 1
                    if count >= per_feed:
                        break
            except Exception:
                continue
        return out

    def analyze(self, force_refresh: bool = False) -> MacroCatalystReport:
        """Return cached or freshly evaluated MacroCatalystReport."""
        now = time.time()
        if (
            not force_refresh
            and self._cached_report is not None
            and (now - self._last_fetch_ts) < self.cache_ttl_sec
        ):
            return self._cached_report

        fng_val, fng_label = self.fetch_fear_and_greed()
        raw_headlines = self.fetch_headlines(per_feed=5)
        headline_score, events = score_headlines(raw_headlines)

        # Combine headline catalyst score with Fear & Greed regime tilt
        fng_tilt = 0.0
        if fng_val <= 25:
            fng_tilt = -0.20  # Extreme Fear -> risk-off / crash continuation risk
        elif fng_val <= 40:
            fng_tilt = -0.10
        elif fng_val >= 75:
            fng_tilt = 0.20
        elif fng_val >= 60:
            fng_tilt = 0.10

        combined_score = max(-1.0, min(1.0, round(headline_score + fng_tilt, 2)))

        if combined_score <= -0.25:
            bias = "BEARISH"
            top_msg = events[0].rationale if events else f"Fear & Greed at {fng_val} ({fng_label})"
            prediction = f"BEARISH RISK-OFF ({combined_score:+.2f}): {top_msg}. Prioritize Shorts."
        elif combined_score >= 0.25:
            bias = "BULLISH"
            top_msg = events[0].rationale if events else f"Fear & Greed at {fng_val} ({fng_label})"
            prediction = f"BULLISH RISK-ON ({combined_score:+.2f}): {top_msg}. Favor Longs if 4h confirms."
        else:
            bias = "NEUTRAL"
            prediction = f"NEUTRAL MACRO ({combined_score:+.2f}) | F&G: {fng_val} ({fng_label}). Follow technical trend."

        report = MacroCatalystReport(
            fear_and_greed_value=fng_val,
            fear_and_greed_label=fng_label,
            catalyst_bias=bias,
            catalyst_score=combined_score,
            events=events,
            prediction_summary=prediction,
            timestamp=now,
        )
        self._cached_report = report
        self._last_fetch_ts = now
        return report
