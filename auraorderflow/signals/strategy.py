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
    NEUTRAL,
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

# Initiative vs responsive flow (auction market theory). Responsive patterns
# fade an extreme (reversal) and are only valid on the right side of a level —
# longs at support, shorts at resistance. Initiative patterns ride momentum and
# are not location-constrained.
RESPONSIVE = {"absorption", "exhaustion", "stop_run", "iceberg", "delta_divergence"}
INITIATIVE = {"stacked_imbalance", "cvd_trend", "book_pressure", "liquidity_pull"}


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
        htf_lookback_minutes: int = 60,
        require_htf_alignment: bool = True,
        use_vwap: bool = True,
        use_prev_day_levels: bool = True,
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
        self.htf_lookback_minutes = htf_lookback_minutes
        self.require_htf_alignment = require_htf_alignment
        self.use_vwap = use_vwap
        self.use_prev_day_levels = use_prev_day_levels
        self.weights = weights or DEFAULT_WEIGHTS

    # -- higher-timeframe bias ---------------------------------------------
    def _htf_bias(self, engine: OrderFlowEngine) -> str:
        """Coarse higher-timeframe trend from price + CVD slope.

        Long only when BOTH price and cumulative delta rose over the lookback
        window (genuine buyer-led uptrend), short when both fell, otherwise
        neutral. Bars are 1-minute, so ``htf_lookback_minutes`` ~= the higher
        timeframe in minutes.
        """
        bars = engine.recent_bars(self.htf_lookback_minutes)
        if len(bars) < 10:
            return NEUTRAL
        price_chg = bars[-1].close - bars[0].close
        cvd_chg = bars[-1].cvd - bars[0].cvd
        if price_chg > 0 and cvd_chg > 0:
            return LONG
        if price_chg < 0 and cvd_chg < 0:
            return SHORT
        return NEUTRAL

    # -- structural level detection ----------------------------------------
    def _level_context(self, engine: OrderFlowEngine, price: float):
        """Nearest structural level *and* whether it is support or resistance.

        ``kind`` = ``support`` when the level sits at/below price (price resting
        on it) and ``resistance`` when it sits at/above. This is what lets the
        strategy trade *responsive* reversals on the correct side of the
        auction instead of fading into the wrong edge.
        """
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

        # multi-timeframe / session structural levels
        if self.use_vwap and engine.vwap is not None:
            candidates.append(("VWAP", engine.vwap))
        if self.use_prev_day_levels:
            if engine.prev_day_high is not None:
                candidates.append(("Prev Day High", engine.prev_day_high))
            if engine.prev_day_low is not None:
                candidates.append(("Prev Day Low", engine.prev_day_low))

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
        if best is None:
            return None
        name, lvl = best
        kind = "support" if lvl <= price else "resistance"
        return (name, lvl, kind)

    # -- main evaluation ----------------------------------------------------
    def evaluate(self, engine: OrderFlowEngine) -> Signal | None:
        bars = engine.recent_bars(max(self.min_bars, 30))
        if len(bars) < self.min_bars:
            return None
        last = bars[-1]
        price = last.close
        if price <= 0:
            return None

        ctx = self._level_context(engine, price)
        if self.require_level and ctx is None:
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
            LONG: {"score": 0.0, "reasons": [], "hits": 0, "primary": 0,
                   "resp": 0.0, "init": 0.0},
            SHORT: {"score": 0.0, "reasons": [], "hits": 0, "primary": 0,
                    "resp": 0.0, "init": 0.0},
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
            if det.name in RESPONSIVE:
                bucket["resp"] += w * det.score
            elif det.name in INITIATIVE:
                bucket["init"] += w * det.score

        if agg[LONG]["score"] >= agg[SHORT]["score"]:
            side, win, opp = LONG, agg[LONG], agg[SHORT]
        else:
            side, win, opp = SHORT, agg[SHORT], agg[LONG]

        # net the opposing flow against us before scoring confidence
        net = win["score"] - 0.5 * opp["score"]
        confidence = max(0.0, min(100.0, net / self.confidence_scale * 100.0))

        if win["primary"] < 1 or win["hits"] < self.min_confirmations:
            return None

        # -- auction location logic (initiative vs responsive) --------------
        reasons = win["reasons"]
        responsive = win["resp"] >= win["init"]
        if responsive and ctx is not None:
            _, lvl, kind = ctx
            eps = price * 1e-6
            # don't fade into the wrong side of the auction
            if side == LONG and lvl > price + eps:
                return None  # responsive long beneath resistance
            if side == SHORT and lvl < price - eps:
                return None  # responsive short above support
            confidence = min(100.0, confidence * 1.05)  # location confluence
            reasons = [
                f"responsive {'long' if side == LONG else 'short'} at "
                f"{ctx[0]} ({kind})"
            ] + reasons
        elif ctx is not None:
            reasons = [f"initiative {'long' if side == LONG else 'short'} "
                       f"through {ctx[0]}"] + reasons

        # -- higher-timeframe alignment (multi-timeframe layer) -------------
        htf = self._htf_bias(engine)
        if htf != NEUTRAL:
            aligned = (side == LONG and htf == LONG) or (side == SHORT and htf == SHORT)
            # initiative/continuation must not fight the higher-timeframe trend;
            # responsive reversals at a level are allowed to fade it.
            if not aligned and not responsive and self.require_htf_alignment:
                return None
            if aligned:
                confidence = min(100.0, confidence * 1.05)
                trend = "uptrend" if htf == LONG else "downtrend"
                reasons = [f"with higher-timeframe {trend}"] + reasons

        if confidence < self.min_confidence:
            return None

        stop, target = self._risk_levels(side, price, bars)
        level_name = f"{ctx[0]} @ {ctx[1]:g}" if ctx else "free flow"
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
