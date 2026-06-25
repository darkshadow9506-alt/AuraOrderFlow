"""Builders for deterministic order-flow test fixtures."""
from __future__ import annotations

from auraorderflow.orderflow.models import Bar, Trade


def trade(price=100.0, qty=1.0, sell=False, ts=0, symbol="TEST") -> Trade:
    """`sell=True` => aggressive sell (buyer is maker)."""
    return Trade(symbol=symbol, price=price, qty=qty, is_buyer_maker=sell, timestamp=ts)


def bar_from_trades(specs, *, start=0, step=1.0, symbol="TEST", cvd=0.0) -> Bar:
    """`specs` = list of (price, qty, sell)."""
    bar = Bar(symbol=symbol, start_ms=start, end_ms=start + 60000, price_step=step)
    for price, qty, sell in specs:
        bar.add_trade(trade(price=price, qty=qty, sell=sell, ts=start, symbol=symbol))
    bar.cvd = cvd
    bar.closed = True
    return bar


def raw_bar(
    *,
    open=100.0,
    high=100.0,
    low=100.0,
    close=100.0,
    buy=5.0,
    sell=5.0,
    cvd=0.0,
    step=1.0,
    start=0,
    symbol="TEST",
    footprint=None,
) -> Bar:
    """Build a bar with fields set directly (full control for analyser tests)."""
    bar = Bar(
        symbol=symbol,
        start_ms=start,
        end_ms=start + 60000,
        price_step=step,
        open=open,
        high=high,
        low=low,
        close=close,
        buy_volume=buy,
        sell_volume=sell,
        volume=buy + sell,
        cvd=cvd,
        trades=int(buy + sell) or 1,
        closed=True,
        footprint=footprint or {round(close, 10): [buy, sell]},
    )
    return bar
