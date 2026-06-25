from auraorderflow.orderflow.engine import OrderFlowEngine
from auraorderflow.orderflow.volume_profile import build_profile
from tests.helpers import bar_from_trades, trade


def test_engine_closes_bars_on_period_boundary():
    eng = OrderFlowEngine("TEST", period_s=60, price_step=1.0)
    # two trades in minute 0, one in minute 1
    assert eng.on_trade(trade(price=100, ts=0)) is None
    assert eng.on_trade(trade(price=101, ts=30_000)) is None
    closed = eng.on_trade(trade(price=102, ts=61_000))
    assert closed is not None
    assert closed.start_ms == 0 and closed.trades == 2
    # running CVD accumulates across bars
    assert eng.cvd == 3.0  # three aggressive buys of qty 1


def test_engine_cvd_tracks_signed_flow():
    eng = OrderFlowEngine("TEST", period_s=60)
    eng.on_trade(trade(qty=5, sell=False, ts=0))   # +5
    eng.on_trade(trade(qty=2, sell=True, ts=1000))  # -2
    assert eng.cvd == 3.0


def test_volume_profile_poc_and_value_area():
    # concentrate volume at 100 -> POC=100; spread thin tails around it
    bars = [
        bar_from_trades([(100.0, 50.0, False)]),
        bar_from_trades([(101.0, 5.0, False)]),
        bar_from_trades([(99.0, 5.0, True)]),
        bar_from_trades([(102.0, 1.0, False)]),
        bar_from_trades([(98.0, 1.0, True)]),
    ]
    prof = build_profile(bars, price_step=1.0, value_area_pct=0.70)
    assert prof.poc == 100.0
    assert prof.val <= 100.0 <= prof.vah
    assert 100.0 in prof.hvns          # the heavy node
    assert prof.total_volume == 62.0
