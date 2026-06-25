from auraorderflow.backtest import Backtester, simulate_trade
from auraorderflow.signals.models import Signal
from tests.helpers import raw_bar, trade


def _sig(side, price, stop, target):
    return Signal(symbol="T", side=side, price=price, timestamp=0, confidence=70,
                  stop=stop, target=target)


def test_simulate_long_win():
    bars = [raw_bar(close=100), raw_bar(open=100, high=104, low=99, close=103)]
    res = simulate_trade(_sig("LONG", 100, 98, 104), bars, 0, max_hold=10)
    assert res.outcome == "win"
    assert round(res.r_multiple, 3) == 2.0  # target was 2R away
    assert res.bars_held == 1


def test_simulate_long_loss():
    bars = [raw_bar(close=100), raw_bar(open=100, high=101, low=97, close=98)]
    res = simulate_trade(_sig("LONG", 100, 98, 104), bars, 0, max_hold=10)
    assert res.outcome == "loss"
    assert round(res.r_multiple, 3) == -1.0


def test_simulate_both_hit_counts_as_loss():
    bars = [raw_bar(close=100), raw_bar(open=100, high=104, low=97, close=100)]
    res = simulate_trade(_sig("LONG", 100, 98, 104), bars, 0, max_hold=10)
    assert res.outcome == "loss"  # pessimistic when a bar spans both


def test_simulate_short_win():
    bars = [raw_bar(close=100), raw_bar(open=100, high=101, low=95, close=96)]
    res = simulate_trade(_sig("SHORT", 100, 102, 96), bars, 0, max_hold=10)
    assert res.outcome == "win"
    assert round(res.r_multiple, 3) == 2.0


def test_simulate_timeout_marks_to_close():
    bars = [raw_bar(close=100), raw_bar(open=100, high=101, low=99, close=100.5)]
    res = simulate_trade(_sig("LONG", 100, 98, 104), bars, 0, max_hold=1)
    assert res.outcome == "timeout"
    assert round(res.r_multiple, 3) == 0.25  # (100.5-100)/2


def test_fee_is_charged_in_r():
    bars = [raw_bar(close=100), raw_bar(open=100, high=104, low=99, close=103)]
    res = simulate_trade(_sig("LONG", 100, 98, 104), bars, 0, max_hold=10, fee_r=0.1)
    assert round(res.r_multiple, 3) == 1.9


def test_backtester_runs_end_to_end_on_synthetic_stream():
    def stream():
        price = 100.0
        for minute in range(40):
            # drift price a little each minute, a few trades per bar
            for k in range(5):
                ts = minute * 60_000 + k * 1000
                sell = (minute + k) % 2 == 0
                price += 0.1 if not sell else -0.1
                yield trade(price=round(price, 2), qty=1.0, sell=sell, ts=ts)

    bt = Backtester("TEST", price_step=0.5, bar_period_s=60, max_hold=10)
    report = bt.run(stream(), span="synthetic")
    assert report.bars_built >= 38
    assert report.n >= 0
    assert "TEST" in report.format()
