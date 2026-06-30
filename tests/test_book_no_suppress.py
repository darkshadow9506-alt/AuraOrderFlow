"""Regression test for the live-suppression bug.

A roughly balanced order book used to multiply the absorption score by 0.6,
which silently pushed nearly every live signal under the confidence threshold
(backtests, having no book, never saw it -> zero live signals for days).
"""
from auraorderflow.orderflow.engine import OrderFlowEngine
from auraorderflow.orderflow.models import OrderBookSnapshot
from auraorderflow.signals.strategy import StrategyEngine
from tests.helpers import raw_bar


def _bullish_bars():
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=float(i))
        for i in range(29)
    ]
    bars.append(
        raw_bar(open=100, high=101, low=99, close=100, buy=5, sell=45, cvd=80.0,
                footprint={100.0: [5.0, 45.0]})
    )
    return bars


def _engine_with_book(imbalance):
    eng = OrderFlowEngine("T", price_step=1.0)
    for b in _bullish_bars():
        eng.bars.append(b)
    eng.cvd = 80.0
    if imbalance is not None:
        bid = 50 * (1 + imbalance)
        ask = 50 * (1 - imbalance)
        snap = OrderBookSnapshot("T", 0, [(99.0, bid)], [(101.0, ask)])
        eng.book = snap
        for _ in range(60):
            eng.book_tracker.update(snap)
    return eng


def test_balanced_book_does_not_suppress_signal():
    se = StrategyEngine(min_confidence=60, min_confirmations=2)
    no_book = se.evaluate(_engine_with_book(None))
    neutral = se.evaluate(_engine_with_book(0.0))
    assert no_book is not None
    assert neutral is not None and neutral.side == "LONG"
    # a balanced book must not materially cut confidence
    assert neutral.confidence >= no_book.confidence - 5


def test_strongly_opposing_book_dampens_but_keeps_signal():
    se = StrategyEngine(min_confidence=60, min_confirmations=2)
    sig = se.evaluate(_engine_with_book(-0.5))  # asks dominate against the long
    assert sig is not None and sig.side == "LONG"
