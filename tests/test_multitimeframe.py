from auraorderflow.orderflow.engine import OrderFlowEngine
from auraorderflow.signals.strategy import StrategyEngine
from tests.helpers import bar_from_trades, raw_bar, trade

DAY_MS = 86_400_000


def _engine_with(bars):
    eng = OrderFlowEngine("T", period_s=60, price_step=1.0)
    for b in bars:
        eng.bars.append(b)
    eng.cvd = bars[-1].cvd
    return eng


# -- session VWAP + previous-day levels ------------------------------------
def test_engine_vwap_and_prev_day_rollover():
    eng = OrderFlowEngine("T", period_s=60, price_step=1.0)
    eng.on_trade(trade(price=100, qty=1, ts=10_000))
    eng.on_trade(trade(price=102, qty=3, ts=20_000))
    # VWAP = (100*1 + 102*3) / 4 = 101.5
    assert round(eng.vwap, 4) == 101.5
    assert eng.prev_day_high is None

    # cross into the next UTC day -> previous-day levels freeze, VWAP resets
    eng.on_trade(trade(price=99, qty=1, ts=DAY_MS + 10_000))
    assert eng.prev_day_high == 102
    assert eng.prev_day_low == 100
    assert eng.prev_day_close == 102
    assert eng.vwap == 99  # new day, single trade


# -- higher-timeframe bias --------------------------------------------------
def test_htf_bias_directions():
    se = StrategyEngine()
    up = _engine_with([raw_bar(close=100 + i * 0.1, cvd=float(i)) for i in range(20)])
    assert se._htf_bias(up) == "long"
    down = _engine_with([raw_bar(close=100 - i * 0.1, cvd=float(-i)) for i in range(20)])
    assert se._htf_bias(down) == "short"
    # price up but CVD down -> divergent -> neutral (no clear bias)
    div = _engine_with([raw_bar(close=100 + i * 0.1, cvd=float(-i)) for i in range(20)])
    assert se._htf_bias(div) == "neutral"
    # too little history -> neutral
    assert se._htf_bias(_engine_with([raw_bar() for _ in range(5)])) == "neutral"


# -- HTF alignment filter in evaluate() ------------------------------------
def _initiative_long_engine():
    # 25 quiet bars + a strong stacked-imbalance (initiative) long bar
    bars = [raw_bar(close=100, buy=5, sell=5, cvd=float(i)) for i in range(25)]
    specs = [(float(p), 30.0, False) for p in range(100, 106)]      # buys 100..105
    specs += [(float(p), 1.0, True) for p in range(100, 105)]        # tiny sells
    bars.append(bar_from_trades(specs, step=1.0, cvd=40.0))
    return _engine_with(bars)


def test_evaluate_rejects_initiative_against_htf_trend():
    eng = _initiative_long_engine()
    se = StrategyEngine(require_level=False, require_htf_alignment=True,
                        min_confidence=60, min_confirmations=2, confidence_scale=2.0)
    se._htf_bias = lambda engine: "short"   # higher timeframe is down
    assert se.evaluate(eng) is None          # initiative long vs HTF down -> skip


def test_evaluate_allows_initiative_when_alignment_disabled():
    eng = _initiative_long_engine()
    se = StrategyEngine(require_level=False, require_htf_alignment=False,
                        min_confidence=60, min_confirmations=2, confidence_scale=2.0)
    se._htf_bias = lambda engine: "short"
    sig = se.evaluate(eng)
    assert sig is not None and sig.side == "LONG"
