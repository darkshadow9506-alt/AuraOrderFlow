from auraorderflow.orderflow.models import OrderBookSnapshot
from tests.helpers import bar_from_trades, trade


def test_aggressor_side_convention():
    buy = trade(sell=False)        # buyer is taker -> aggressive buy
    sell = trade(sell=True)        # buyer is maker -> aggressive sell
    assert buy.is_buy and buy.buy_qty == 1.0 and buy.sell_qty == 0.0
    assert not sell.is_buy and sell.sell_qty == 1.0
    assert buy.signed_qty == 1.0 and sell.signed_qty == -1.0


def test_bar_ohlc_volume_and_delta():
    bar = bar_from_trades(
        [
            (100.0, 2.0, False),   # buy 2
            (101.0, 1.0, False),   # buy 1
            (99.0, 4.0, True),     # sell 4
        ]
    )
    assert bar.open == 100.0
    assert bar.high == 101.0
    assert bar.low == 99.0
    assert bar.close == 99.0
    assert bar.volume == 7.0
    assert bar.buy_volume == 3.0
    assert bar.sell_volume == 4.0
    assert bar.delta == -1.0


def test_bar_footprint_buckets_by_step():
    bar = bar_from_trades([(100.2, 1.0, False), (100.4, 1.0, True)], step=1.0)
    # both prices snap to the 100 bucket
    assert set(bar.footprint) == {100.0}
    assert bar.footprint[100.0] == [1.0, 1.0]


def test_orderbook_imbalance():
    ob = OrderBookSnapshot(
        symbol="TEST",
        timestamp=0,
        bids=[(99.0, 30.0), (98.0, 10.0)],
        asks=[(100.0, 10.0), (101.0, 10.0)],
    )
    assert ob.best_bid == 99.0 and ob.best_ask == 100.0
    assert ob.mid == 99.5
    assert ob.imbalance(levels=2) > 0  # more resting bids -> buy pressure
