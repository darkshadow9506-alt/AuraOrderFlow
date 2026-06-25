from auraorderflow.orderflow.analyzers import (
    LONG,
    SHORT,
    book_pressure,
    iceberg,
    liquidity_pull,
    stop_run,
)
from auraorderflow.orderflow.book import BookTracker
from auraorderflow.orderflow.models import OrderBookSnapshot
from tests.helpers import raw_bar


def _book(bids, asks, ts=0):
    return OrderBookSnapshot(symbol="TEST", timestamp=ts, bids=bids, asks=asks)


def test_stop_run_long_on_swept_low_reclaimed():
    prior = [raw_bar(open=100, high=100.5, low=100, close=100.2) for _ in range(10)]
    last = raw_bar(open=100, high=101, low=98, close=100.5)  # swept lows, reclaimed
    det = stop_run(prior + [last])
    assert det.side == LONG and det.hit


def test_stop_run_short_on_swept_high_rejected():
    prior = [raw_bar(open=100, high=100, low=99.5, close=99.8) for _ in range(10)]
    last = raw_bar(open=100, high=102, low=99, close=99.5)   # swept highs, rejected
    det = stop_run(prior + [last])
    assert det.side == SHORT and det.hit


def test_iceberg_long_when_executed_size_dwarfs_shown_bid():
    bar = raw_bar(open=100, close=100, footprint={100.0: [2.0, 40.0]})
    book = _book(bids=[(100.0, 5.0)], asks=[(101.0, 5.0)])
    det = iceberg(bar, book, fill_factor=4.0)
    assert det.side == LONG and det.hit


def test_iceberg_short_when_executed_size_dwarfs_shown_ask():
    bar = raw_bar(open=100, close=100, footprint={100.0: [40.0, 2.0]})
    book = _book(bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    det = iceberg(bar, book, fill_factor=4.0)
    assert det.side == SHORT and det.hit


def test_iceberg_neutral_without_book():
    bar = raw_bar(footprint={100.0: [2.0, 40.0]})
    assert not iceberg(bar, None).hit


def test_book_pressure_from_sustained_imbalance():
    tr = BookTracker()
    for i in range(10):
        tr.update(_book(bids=[(99.0, 80.0)], asks=[(100.0, 20.0)], ts=i))
    assert book_pressure(tr, threshold=0.25).side == LONG


def test_liquidity_pull_detects_vanished_bid():
    tr = BookTracker()
    for i in range(5):
        tr.update(_book(bids=[(99.0, 100.0)], asks=[(100.0, 50.0)], ts=i))
    tr.update(_book(bids=[(99.0, 10.0)], asks=[(100.0, 50.0)], ts=5))  # bid pulled
    det = liquidity_pull(tr)
    assert det.side == SHORT and det.hit
