"""Order-flow pattern analysers.

Each analyser is a pure function over recent :class:`Bar` history (and, where
relevant, the latest :class:`OrderBookSnapshot`). They return a
:class:`Detection` with a side (``long``/``short``/``neutral``) and a strength
score in ``[0, 1]`` so the strategy layer can combine them by confluence.

Implemented patterns (mapped to the user's strategy catalogue):

* :func:`stacked_imbalance`  - #2 Imbalance (diagonal footprint imbalances)
* :func:`delta_divergence`   - #3 Delta-based / #4 VP confluence
* :func:`absorption`         - #1 Absorption / responsive flow (#9)
* :func:`exhaustion`         - #10 Volume exhaustion & climax
* :func:`cvd_trend`          - #3 Cumulative-delta trend / initiative flow
"""
from __future__ import annotations

from dataclasses import dataclass

from .book import BookTracker
from .models import Bar, OrderBookSnapshot

LONG = "long"
SHORT = "short"
NEUTRAL = "neutral"


@dataclass(slots=True)
class Detection:
    name: str
    side: str
    score: float  # 0..1
    detail: str

    @property
    def hit(self) -> bool:
        return self.side != NEUTRAL and self.score > 0.0


def _avg_volume(bars: list[Bar]) -> float:
    if not bars:
        return 0.0
    return sum(b.volume for b in bars) / len(bars)


def stacked_imbalance(
    bar: Bar,
    ratio: float = 3.0,
    min_stack: int = 3,
    min_level_volume: float = 0.0,
    min_level_factor: float = 0.5,
) -> Detection:
    """Detect stacked *diagonal* footprint imbalances inside one bar.

    Diagonal comparison (the standard): the ask volume traded at price ``p``
    (aggressive buys) is compared with the bid volume traded one level *below*
    (aggressive sells). ``ratio``+ consecutive levels in one direction = a
    stacked imbalance, a strong initiative footprint.

    Thin levels are ignored: a level only counts if its aggressive volume is at
    least ``min_level_factor`` of the bar's mean per-level volume (or the
    explicit ``min_level_volume`` floor), so a 2:0 print on a near-empty level
    can't masquerade as an imbalance.
    """
    fp = bar.footprint
    if len(fp) < min_stack + 1:
        return Detection("stacked_imbalance", NEUTRAL, 0.0, "insufficient levels")

    levels = sorted(fp)
    step = bar.price_step
    eps = 1e-9
    mean_level = sum(b + s for b, s in fp.values()) / len(fp)
    floor = max(min_level_volume, mean_level * min_level_factor)

    buy_flags: list[bool] = []
    sell_flags: list[bool] = []
    for i, p in enumerate(levels):
        ask_vol = fp[p][0]               # buys lifting the ask at p
        bid_vol = fp[p][1]               # sells hitting the bid at p
        below = round(p - step, 10)
        above = round(p + step, 10)
        bid_below = fp.get(below, [0.0, 0.0])[1]
        ask_above = fp.get(above, [0.0, 0.0])[0]
        buy_flags.append(
            ask_vol >= floor and ask_vol >= ratio * (bid_below + eps)
        )
        sell_flags.append(
            bid_vol >= floor and bid_vol >= ratio * (ask_above + eps)
        )

    def longest_run(flags: list[bool]) -> int:
        best = run = 0
        for f in flags:
            run = run + 1 if f else 0
            best = max(best, run)
        return best

    buy_run = longest_run(buy_flags)
    sell_run = longest_run(sell_flags)

    if buy_run >= min_stack and buy_run >= sell_run:
        score = min(1.0, buy_run / (min_stack * 2))
        return Detection(
            "stacked_imbalance", LONG, score,
            f"{buy_run} stacked buy imbalances (>= {ratio:g}:1)",
        )
    if sell_run >= min_stack:
        score = min(1.0, sell_run / (min_stack * 2))
        return Detection(
            "stacked_imbalance", SHORT, score,
            f"{sell_run} stacked sell imbalances (>= {ratio:g}:1)",
        )
    return Detection("stacked_imbalance", NEUTRAL, 0.0, "no stacked imbalance")


def delta_divergence(bars: list[Bar], lookback: int = 20) -> Detection:
    """Price/cumulative-delta divergence over a lookback window.

    Bullish: price prints a new low but CVD holds *above* its level at the prior
    low (sellers can't push delta lower => absorption / buyers stepping in).
    Bearish is the mirror image at new highs.
    """
    window = bars[-lookback:]
    if len(window) < 5:
        return Detection("delta_divergence", NEUTRAL, 0.0, "insufficient history")

    last = window[-1]
    prior = window[:-1]

    # bullish divergence at a new low
    prior_low_bar = min(prior, key=lambda b: b.low)
    if last.low < prior_low_bar.low and last.cvd > prior_low_bar.cvd:
        strength = _norm(last.cvd - prior_low_bar.cvd, window)
        return Detection(
            "delta_divergence", LONG, strength,
            "new price low but CVD higher (bullish divergence)",
        )

    # bearish divergence at a new high
    prior_high_bar = max(prior, key=lambda b: b.high)
    if last.high > prior_high_bar.high and last.cvd < prior_high_bar.cvd:
        strength = _norm(prior_high_bar.cvd - last.cvd, window)
        return Detection(
            "delta_divergence", SHORT, strength,
            "new price high but CVD lower (bearish divergence)",
        )

    return Detection("delta_divergence", NEUTRAL, 0.0, "no divergence")


def _norm(delta_gap: float, window: list[Bar]) -> float:
    """Scale a CVD gap to ``[0, 1]`` against typical per-bar |delta|."""
    typical = _avg_volume(window) or 1.0
    return max(0.0, min(1.0, abs(delta_gap) / (typical * 2)))


def absorption(
    bar: Bar,
    bars: list[Bar],
    book: OrderBookSnapshot | None = None,
    vol_factor: float = 1.8,
    delta_ratio: float = 0.35,
    body_ratio: float = 0.5,
) -> Detection:
    """Aggressive one-sided flow that fails to move price = absorption.

    A heavy, strongly one-sided bar whose *result* (the close) does not extend
    in the direction of that aggression means resting limits absorbed it. Heavy
    selling that closes firm => bullish; heavy buying that closes weak =>
    bearish. The "fails to move price" part is enforced by ``body_ratio``: the
    candle body must be no more than that fraction of its range (effort without
    result). When a book snapshot is available, confirmation requires sizeable
    resting liquidity on the side that did the absorbing.
    """
    history = bars[-30:]
    avg = _avg_volume(history[:-1]) if len(history) > 1 else 0.0
    if avg <= 0 or bar.volume < avg * vol_factor:
        return Detection("absorption", NEUTRAL, 0.0, "no volume spike")
    if bar.range <= 0:
        return Detection("absorption", NEUTRAL, 0.0, "no range")

    one_sided = abs(bar.delta) / bar.volume if bar.volume else 0.0
    if one_sided < delta_ratio:
        return Detection("absorption", NEUTRAL, 0.0, "delta not one-sided")

    body = abs(bar.close - bar.open) / bar.range  # small body => effort w/o result
    if body > body_ratio:
        return Detection("absorption", NEUTRAL, 0.0, "body too large (price moved)")

    # Heavy selling (delta<0) but price held -> buyers absorbed -> LONG
    if bar.delta < 0 and bar.close >= bar.open:
        score = min(1.0, one_sided * (bar.volume / (avg * vol_factor)))
        if book is not None and book.imbalance() < 0.05:
            score *= 0.6  # no resting bid support -> weaker
        return Detection(
            "absorption", LONG, min(1.0, score),
            f"heavy sell delta {bar.delta:.1f} absorbed, price held",
        )
    # Heavy buying (delta>0) but price stalled -> sellers absorbed -> SHORT
    if bar.delta > 0 and bar.close <= bar.open:
        score = min(1.0, one_sided * (bar.volume / (avg * vol_factor)))
        if book is not None and book.imbalance() > -0.05:
            score *= 0.6
        return Detection(
            "absorption", SHORT, min(1.0, score),
            f"heavy buy delta +{bar.delta:.1f} absorbed, price stalled",
        )
    return Detection("absorption", NEUTRAL, 0.0, "effort matched by result")


def exhaustion(
    bar: Bar,
    bars: list[Bar],
    vol_factor: float = 2.0,
    retrace: float = 0.5,
) -> Detection:
    """Climax / exhaustion: extreme volume at an extreme with a poor result.

    A volume climax printing the window's high/low but closing back through
    ``retrace`` of its own range is effort that failed = likely exhaustion of
    the move, faded in the opposite direction.
    """
    history = bars[-30:]
    if len(history) < 5:
        return Detection("exhaustion", NEUTRAL, 0.0, "insufficient history")
    avg = _avg_volume(history[:-1])
    if avg <= 0 or bar.volume < avg * vol_factor or bar.range <= 0:
        return Detection("exhaustion", NEUTRAL, 0.0, "no climax volume")

    window_high = max(b.high for b in history[:-1])
    window_low = min(b.low for b in history[:-1])

    # spike to new high then closes back down -> short exhaustion
    if bar.high >= window_high and (bar.high - bar.close) / bar.range >= retrace:
        return Detection(
            "exhaustion", SHORT, min(1.0, bar.volume / (avg * vol_factor) - 0.5),
            "climax volume into new high, closed back (buy exhaustion)",
        )
    # spike to new low then closes back up -> long exhaustion
    if bar.low <= window_low and (bar.close - bar.low) / bar.range >= retrace:
        return Detection(
            "exhaustion", LONG, min(1.0, bar.volume / (avg * vol_factor) - 0.5),
            "climax volume into new low, closed back (sell exhaustion)",
        )
    return Detection("exhaustion", NEUTRAL, 0.0, "no exhaustion")


def cvd_trend(bars: list[Bar], lookback: int = 10) -> Detection:
    """Direction of cumulative delta over a short lookback (initiative flow)."""
    window = bars[-lookback:]
    if len(window) < 3:
        return Detection("cvd_trend", NEUTRAL, 0.0, "insufficient history")
    change = window[-1].cvd - window[0].cvd
    scale = (_avg_volume(window) or 1.0) * len(window)
    score = max(0.0, min(1.0, abs(change) / (scale + 1e-9)))
    if change > 0:
        return Detection("cvd_trend", LONG, score, f"CVD rising (+{change:.1f})")
    if change < 0:
        return Detection("cvd_trend", SHORT, score, f"CVD falling ({change:.1f})")
    return Detection("cvd_trend", NEUTRAL, 0.0, "flat CVD")


def stop_run(bars: list[Bar], lookback: int = 20) -> Detection:
    """Stop run / liquidity grab (#5): sweep a swing then reject back inside.

    Price pushes *beyond* the prior swing (running stops / triggering breakout
    orders) but closes back on the other side of that level — a failed auction
    that traps the breakout crowd and tends to reverse. A swept **high** that
    closes back below = SHORT; a swept **low** reclaimed = LONG.
    """
    window = bars[-lookback:]
    if len(window) < 5:
        return Detection("stop_run", NEUTRAL, 0.0, "insufficient history")
    last = window[-1]
    prior = window[:-1]
    if last.range <= 0:
        return Detection("stop_run", NEUTRAL, 0.0, "no range")

    swing_hi = max(b.high for b in prior)
    swing_lo = min(b.low for b in prior)
    avg_rng = sum(b.range for b in prior) / len(prior) or last.range
    margin = avg_rng * 0.05

    # swept the highs, closed back below -> trapped longs -> SHORT
    if last.high > swing_hi + margin and last.close < swing_hi:
        wick = (last.high - last.close) / last.range
        return Detection(
            "stop_run", SHORT, min(1.0, wick),
            "swept prior highs then rejected (liquidity grab)",
        )
    # swept the lows, reclaimed -> trapped shorts -> LONG
    if last.low < swing_lo - margin and last.close > swing_lo:
        wick = (last.close - last.low) / last.range
        return Detection(
            "stop_run", LONG, min(1.0, wick),
            "swept prior lows then reclaimed (liquidity grab)",
        )
    return Detection("stop_run", NEUTRAL, 0.0, "no sweep")


def iceberg(
    bar: Bar,
    book: OrderBookSnapshot | None,
    fill_factor: float = 4.0,
) -> Detection:
    """Iceberg / hidden-liquidity detection (#6).

    The defining iceberg tell: far more volume *executes* at a price than was
    ever *displayed* resting there, and price does not move through it — size is
    being constantly refilled from hidden orders. Heavy executed sells at a
    price showing only a small bid, with price holding => hidden buyer => LONG;
    the mirror at the ask => SHORT.
    """
    if book is None or not bar.footprint:
        return Detection("iceberg", NEUTRAL, 0.0, "no book / footprint")
    level = max(bar.footprint, key=lambda p: sum(bar.footprint[p]))
    buy_v, sell_v = bar.footprint[level]
    tol = bar.price_step

    if sell_v > buy_v:  # sells hammering the bid at this level
        resting = book.size_at(level, "bid", tol)
        if resting > 0 and sell_v >= fill_factor * resting and bar.close >= bar.open:
            score = min(1.0, sell_v / (fill_factor * resting) - 0.5)
            return Detection(
                "iceberg", LONG, max(0.1, score),
                f"{sell_v:.1f} sold into ~{resting:.1f} shown bid (buy iceberg)",
            )
    elif buy_v > sell_v:  # buys lifting a small ask repeatedly
        resting = book.size_at(level, "ask", tol)
        if resting > 0 and buy_v >= fill_factor * resting and bar.close <= bar.open:
            score = min(1.0, buy_v / (fill_factor * resting) - 0.5)
            return Detection(
                "iceberg", SHORT, max(0.1, score),
                f"{buy_v:.1f} bought into ~{resting:.1f} shown ask (sell iceberg)",
            )
    return Detection("iceberg", NEUTRAL, 0.0, "no hidden refill detected")


def book_pressure(
    tracker: BookTracker | None,
    threshold: float = 0.25,
    levels: int = 10,
) -> Detection:
    """Sustained DOM pressure (#8): time-averaged book imbalance."""
    if tracker is None:
        return Detection("book_pressure", NEUTRAL, 0.0, "no book")
    imb = tracker.avg_imbalance(levels)
    if imb > threshold:
        return Detection("book_pressure", LONG, min(1.0, imb),
                         f"resting bids dominate book ({imb:+.0%})")
    if imb < -threshold:
        return Detection("book_pressure", SHORT, min(1.0, -imb),
                         f"resting asks dominate book ({imb:+.0%})")
    return Detection("book_pressure", NEUTRAL, 0.0, "balanced book")


def liquidity_pull(tracker: BookTracker | None) -> Detection:
    """Spoofing / pulled-liquidity tell (#7): a large resting side vanished."""
    if tracker is None:
        return Detection("liquidity_pull", NEUTRAL, 0.0, "no book")
    res = tracker.detect_pull()
    if res is None:
        return Detection("liquidity_pull", NEUTRAL, 0.0, "no pull")
    side, strength = res
    where = "bid support" if side == SHORT else "ask resistance"
    return Detection("liquidity_pull", side, min(1.0, strength),
                     f"{where} pulled from the book")
