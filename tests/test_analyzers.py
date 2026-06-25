from auraorderflow.orderflow.analyzers import (
    LONG,
    SHORT,
    absorption,
    cvd_trend,
    delta_divergence,
    exhaustion,
    stacked_imbalance,
)
from tests.helpers import bar_from_trades, raw_bar


def test_stacked_buy_imbalance():
    # heavy buys lifting the ask at 100..103, tiny sells one level below each
    specs = []
    for p in (100, 101, 102, 103):
        specs.append((float(p), 30.0, False))   # aggressive buys
    for p in (99, 100, 101, 102):
        specs.append((float(p), 1.0, True))      # tiny aggressive sells
    bar = bar_from_trades(specs, step=1.0)
    det = stacked_imbalance(bar, ratio=3.0, min_stack=3)
    assert det.side == LONG and det.hit


def test_no_stacked_imbalance_when_balanced():
    specs = [(float(p), 10.0, False) for p in (100, 101, 102)]
    specs += [(float(p), 10.0, True) for p in (100, 101, 102)]
    bar = bar_from_trades(specs, step=1.0)
    det = stacked_imbalance(bar, ratio=3.0, min_stack=3)
    assert not det.hit


def test_absorption_long_on_absorbed_selling():
    history = [raw_bar(buy=5, sell=5, low=100, high=100, open=100, close=100)
               for _ in range(12)]
    # heavy selling but price holds (close >= open) -> buyers absorbing -> LONG
    spike = raw_bar(open=100, high=101, low=99, close=100, buy=5, sell=45)
    det = absorption(spike, history + [spike])
    assert det.side == LONG and det.hit


def test_absorption_short_on_absorbed_buying():
    history = [raw_bar(buy=5, sell=5) for _ in range(12)]
    spike = raw_bar(open=100, high=101, low=99, close=100, buy=45, sell=5)
    det = absorption(spike, history + [spike])
    assert det.side == SHORT and det.hit


def test_delta_divergence_bullish():
    bars = []
    for i in range(6):
        bars.append(raw_bar(low=100 - i * 0.1, high=101, close=100, cvd=float(i)))
    # new price low but CVD jumps up -> bullish divergence
    bars.append(raw_bar(low=99.0, high=101, close=99.5, cvd=50.0))
    det = delta_divergence(bars, lookback=20)
    assert det.side == LONG and det.hit


def test_exhaustion_short_on_climax_into_high():
    history = [raw_bar(buy=5, sell=5, high=100, low=99, close=99.5) for _ in range(10)]
    # climax volume into a new high that closes back down
    spike = raw_bar(open=100, high=110, low=100, close=101, buy=40, sell=40)
    det = exhaustion(spike, history + [spike])
    assert det.side == SHORT and det.hit


def test_cvd_trend_direction():
    rising = [raw_bar(cvd=float(i), buy=3, sell=3) for i in range(10)]
    assert cvd_trend(rising).side == LONG
    falling = [raw_bar(cvd=float(-i), buy=3, sell=3) for i in range(10)]
    assert cvd_trend(falling).side == SHORT
