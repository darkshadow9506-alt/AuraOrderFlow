"""Confluence strategy engine.

On every *closed* bar it asks three questions, in order:

1. **Are we at a structural level?** (volume-profile POC/VAH/VAL/HVN/LVN or a
   recent swing). Order flow is only traded at the edges of the auction, never
   in the middle of the range.
2. **What is the order flow saying?** Run every analyser and tally a weighted
   long/short confluence score.
3. **Is the evidence strong and agreeing?** Require a minimum confidence and a
   minimum number of confirming patterns before emitting a :class:`Signal`.
"""
from __future__ import annotations

from ..orderflow.analyzers import (
    LONG,
    SHORT,
    Detection,
    absorption,
    book_pressure,
    cvd_trend,
    delta_divergence,
    exhaustion,
    iceberg,
    liquidity_pull,
    stacked_imbalance,
    stop_run,
)
from ..orderflow.engine import OrderFlowEngine
from .models import Signal

# Per-analyser confluence weights. The high-conviction *triggers* (absorption,
# stacked imbalance, stop-run, iceberg, climax) carry the most weight; CVD/book
# context is only confirming.
DEFAULT_WEIGHTS = {
    "absorption": 1.3,
    "stacked_imbalance": 1.2,
    "stop_run": 1.2,
    "iceberg": 1.15,
    "exhaustion": 1.0,
    "delta_divergence": 1.0,
    "cvd_trend": 0.6,
    "book_pressure": 0.5,
    "liquidity_pull": 0.4,
}

# A valid setup needs at least one *primary* trigger on the chosen side — the
# way real order-flow traders work: a trigger at a level, then confirmation.
PRIMARY = {"absorption", "stacked_imbalance", "stop_run", "iceberg", "exhaustion"}


class StrategyEngine:
    def __init__(
        self,
        *,
        min_bars: int = 25,
        min_confidence: float = 72.0,
        min_confirmations: int = 3,
        require_level: bool = True,
        level_tolerance_pct: float = 0.0012,
        confidence_scale: float = 2.6,
        risk_reward: float = 2.0,
        imbalance_ratio: float = 3.0,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.min_bars = min_bars
        self.min_confidence = min_confidence
        self.min_confirmations = min_confirmations
        self.require_level = require_level
        self.level_tolerance_pct = level_tolerance_pct
        self.confidence_scale = confidence_scale
        self.risk_reward = risk_reward
        self.imbalance_ratio = imbalance_ratio
        self.weights = weights or DEFAULT_WEIGHTS

    # -- structural level detection ----------------------------------------
    def _nearest_level(self, engine: OrderFlowEngine, price: float):
        profile = engine.volume_profile()
        candidates: list[tuple[str, float]] = []
        if profile.poc is not None:
            candidates.append(("POC", profile.poc))
        if profile.vah is not None:
            candidates.append(("Value Area High", profile.vah))
        if profile.val is not None:
            candidates.append(("Value Area Low", profile.val))
        candidates += [("HVN", p) for p in profile.hvns]
        candidates += [("LVN", p) for p in profile.lvns]

        bars = engine.recent_bars(self.min_bars)
        if len(bars) >= 5:
            swing_hi = max(b.high for b in bars[:-1])
            swing_lo = min(b.low for b in bars[:-1])
            candidates.append(("Swing High", swing_hi))
            candidates.append(("Swing Low", swing_lo))

        tol = price * self.level_tolerance_pct
        best = None
        best_dist = tol
        for name, lvl in candidates:
            d = abs(price - lvl)
            if d <= best_dist:
                best, best_dist = (name, lvl), d
        return best  # (name, level) | None

    # -- main evaluation ----------------------------------------------------
    def evaluate(self, engine: OrderFlowEngine) -> Signal | None:
        bars = engine.recent_bars(max(self.min_bars, 30))
        if len(bars) < self.min_bars:
            return None
        last = bars[-1]
        price = last.close
        if price <= 0:
            return None

        level = self._nearest_level(engine, price)
        if self.require_level and level is None:
            return None

        detections: list[Detection] = [
            stacked_imbalance(last, ratio=self.imbalance_ratio),
            delta_divergence(bars),
            absorption(last, bars, engine.book),
            exhaustion(last, bars),
            stop_run(bars),
            iceberg(last, engine.book),
            cvd_trend(bars),
            book_pressure(engine.book_tracker),
            liquidity_pull(engine.book_tracker),
        ]

        agg = {
            LONG: {"score": 0.0, "reasons": [], "hits": 0, "primary": 0},
            SHORT: {"score": 0.0, "reasons": [], "hits": 0, "primary": 0},
        }
        for det in detections:
            if not det.hit or det.side not in agg:
                continue
            w = self.weights.get(det.name, 1.0)
            bucket = agg[det.side]
            bucket["score"] += w * det.score
            bucket["reasons"].append(det.detail)
            bucket["hits"] += 1
            if det.name in PRIMARY:
                bucket["primary"] += 1

        if agg[LONG]["score"] >= agg[SHORT]["score"]:
            side, win, opp = LONG, agg[LONG], agg[SHORT]
        else:
            side, win, opp = SHORT, agg[SHORT], agg[LONG]

        # net the opposing flow against us before scoring confidence
        net = win["score"] - 0.5 * opp["score"]
        confidence = max(0.0, min(100.0, net / self.confidence_scale * 100.0))

        if (
            win["primary"] < 1
            or win["hits"] < self.min_confirmations
            or confidence < self.min_confidence
        ):
            return None
        reasons = win["reasons"]

        stop, target = self._risk_levels(side, price, bars)
        level_name = f"{level[0]} @ {level[1]:g}" if level else "free flow"
        return Signal(
            symbol=engine.symbol,
            side="LONG" if side == LONG else "SHORT",
            price=price,
            timestamp=last.end_ms,
            confidence=confidence,
            reasons=reasons,
            level=level_name,
            stop=stop,
            target=target,
        )

    def _risk_levels(self, side: str, price: float, bars: list) -> tuple[float, float]:
        window = bars[-self.min_bars:]
        swing_lo = min(b.low for b in window)
        swing_hi = max(b.high for b in window)
        buffer = max((swing_hi - swing_lo) * 0.05, price * 0.0005)
        if side == LONG:
            stop = swing_lo - buffer
            risk = max(price - stop, price * 0.0005)
            target = price + risk * self.risk_reward
        else:
            stop = swing_hi + buffer
            risk = max(stop - price, price * 0.0005)
            target = price - risk * self.risk_reward
        return round(stop, 8), round(target, 8)
