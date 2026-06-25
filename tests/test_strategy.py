from auraorderflow.orderflow.engine import OrderFlowEngine
from auraorderflow.signals.strategy import StrategyEngine
from tests.helpers import raw_bar


def _engine_with(bars):
    eng = OrderFlowEngine("TEST", period_s=60, price_step=1.0)
    for b in bars:
        eng.bars.append(b)
    eng.cvd = bars[-1].cvd
    return eng


def test_confluence_long_signal_at_level():
    # 29 quiet bars building a POC at 100, CVD drifting up
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=float(i))
        for i in range(29)
    ]
    # climactic bar: heavy selling absorbed at the level, new low, CVD jumps
    # (absorption + delta divergence + rising CVD all point LONG)
    bars.append(
        raw_bar(open=100, high=101, low=99, close=100, buy=5, sell=45, cvd=80.0,
                footprint={100.0: [5.0, 45.0]})
    )
    eng = _engine_with(bars)

    # explicit thresholds so this stays decoupled from production defaults
    sig = StrategyEngine(min_confidence=60, min_confirmations=2).evaluate(eng)
    assert sig is not None
    assert sig.side == "LONG"
    assert sig.confidence >= 60
    assert sig.stop is not None and sig.stop < sig.price
    assert sig.target is not None and sig.target > sig.price
    assert len(sig.reasons) >= 2


def _responsive_short_bars(close, footprint_level):
    # 29 quiet bars build support at 100, then a responsive SHORT bar
    # (heavy buying absorbed + climax into a new high)
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=0.0)
        for _ in range(29)
    ]
    bars.append(
        raw_bar(open=100.1, high=101, low=100, close=close, buy=45, sell=5, cvd=0.0,
                footprint={footprint_level: [45.0, 5.0]})
    )
    return bars


def test_responsive_short_rejected_above_support():
    # price sits just ABOVE the level (100) -> the level is support beneath.
    # A responsive (reversal) short there would be fading into support -> reject.
    eng = _engine_with(_responsive_short_bars(close=100.05, footprint_level=100.0))
    sig = StrategyEngine(min_confidence=60, min_confirmations=2).evaluate(eng)
    assert sig is None


def test_responsive_short_allowed_at_resistance():
    # same setup but price just BELOW the level -> level is resistance overhead,
    # the correct side for a responsive short -> allowed.
    eng = _engine_with(_responsive_short_bars(close=99.95, footprint_level=100.0))
    sig = StrategyEngine(min_confidence=60, min_confirmations=2).evaluate(eng)
    assert sig is not None and sig.side == "SHORT"


def test_no_signal_in_quiet_range():
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=0.0)
        for _ in range(30)
    ]
    eng = _engine_with(bars)
    assert StrategyEngine().evaluate(eng) is None


def test_signal_requires_structural_level():
    # strong flow but price far from any built level, with require_level on
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=float(i),
                footprint={100.0: [5.0, 5.0]})
        for i in range(29)
    ]
    bars.append(
        raw_bar(open=200, high=201, low=199, close=200, buy=5, sell=45, cvd=80.0,
                footprint={200.0: [5.0, 45.0]})
    )
    eng = _engine_with(bars)
    # price 200 is nowhere near the POC at 100 -> no trade in the middle
    assert StrategyEngine(
        require_level=True, min_confidence=60, min_confirmations=2
    ).evaluate(eng) is None
