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

    sig = StrategyEngine().evaluate(eng)
    assert sig is not None
    assert sig.side == "LONG"
    assert sig.confidence >= 60
    assert sig.stop is not None and sig.stop < sig.price
    assert sig.target is not None and sig.target > sig.price
    assert len(sig.reasons) >= 2


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
    assert StrategyEngine(require_level=True).evaluate(eng) is None
