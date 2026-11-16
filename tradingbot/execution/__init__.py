"""Execution module for Bitbank Autonomous Trading System.

Contains:
- Role 1: PositionReviewer (equity accounting, collateral, naked position audit)
- Role 2: DirectionalStrategist (regime selection, BTC macro filter gating, multi-role signals)
- Role 6: RiskManager (sizing plans, native stops, atomic sync, maker rebates, ratchets)
"""

from .position_reviewer import PositionReviewer, PositionReviewResult
from .directional_strategist import DirectionalStrategist, DirectionalSignal
from .risk_manager import (
    RiskManager,
    StopSyncManager,
    calculate_margin_short_size,
    calculate_spot_long_size,
)

__all__ = [
    "PositionReviewer",
    "PositionReviewResult",
    "DirectionalStrategist",
    "DirectionalSignal",
    "RiskManager",
    "StopSyncManager",
    "calculate_margin_short_size",
    "calculate_spot_long_size",
]
