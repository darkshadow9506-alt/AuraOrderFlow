"""Core data structures for the order-flow engine.

The three primitives:

* :class:`Trade`             - a single executed trade with aggressor side.
* :class:`Bar`               - a time bar carrying OHLC + a price->volume
                               *footprint* + signed delta + cumulative delta.
* :class:`OrderBookSnapshot` - top-of-book depth used for resting-liquidity
                               analysis (absorption / pulling / book pressure).

Aggressor-side convention (this matters a lot and is easy to get wrong):

    Binance ``aggTrade`` carries ``m`` = "is the buyer the market maker?".
      * ``m == True``  -> the *buyer* sat passively, an aggressive **SELL**
                          hit the bid.            => sell_volume / "bid" side
      * ``m == False`` -> the *seller* sat passively, an aggressive **BUY**
                          lifted the ask.         => buy_volume / "ask" side

    delta = buy_volume - sell_volume
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Trade:
    """A single executed (aggressive) trade."""

    symbol: str
    price: float
    qty: float
    is_buyer_maker: bool
    timestamp: int  # epoch milliseconds

    @property
    def is_buy(self) -> bool:
        """True when an aggressive buyer lifted the ask."""
        return not self.is_buyer_maker

    @property
    def buy_qty(self) -> float:
        return self.qty if self.is_buy else 0.0

    @property
    def sell_qty(self) -> float:
        return 0.0 if self.is_buy else self.qty

    @property
    def signed_qty(self) -> float:
        return self.qty if self.is_buy else -self.qty


@dataclass(slots=True)
class Bar:
    """A time bar with an embedded footprint.

    ``footprint`` maps a *bucketed* price to ``[buy_volume, sell_volume]`` where
    buy_volume is volume that lifted the ask at (or near) that price and
    sell_volume is volume that hit the bid.
    """

    symbol: str
    start_ms: int
    end_ms: int
    price_step: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    cvd: float = 0.0  # cumulative volume delta as of this bar's close
    trades: int = 0
    closed: bool = False
    footprint: dict[float, list[float]] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def is_up(self) -> bool:
        return self.close >= self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    def bucket(self, price: float) -> float:
        """Snap a price to the footprint grid."""
        if self.price_step <= 0:
            return price
        return round(round(price / self.price_step) * self.price_step, 10)

    def add_trade(self, trade: Trade) -> None:
        if self.trades == 0:
            self.open = self.high = self.low = trade.price
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.close = trade.price
        self.volume += trade.qty
        self.buy_volume += trade.buy_qty
        self.sell_volume += trade.sell_qty
        self.trades += 1

        level = self.footprint.setdefault(self.bucket(trade.price), [0.0, 0.0])
        if trade.is_buy:
            level[0] += trade.qty
        else:
            level[1] += trade.qty

    def poc(self) -> float | None:
        """Point of control of this single bar (max-volume price level)."""
        if not self.footprint:
            return None
        return max(self.footprint, key=lambda p: sum(self.footprint[p]))


@dataclass(slots=True)
class OrderBookSnapshot:
    """Top-of-book depth snapshot (already sorted best-first)."""

    symbol: str
    timestamp: int
    bids: list[tuple[float, float]]  # [(price, qty), ...] best bid first
    asks: list[tuple[float, float]]  # [(price, qty), ...] best ask first

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    def bid_size(self, levels: int = 10) -> float:
        return sum(q for _, q in self.bids[:levels])

    def ask_size(self, levels: int = 10) -> float:
        return sum(q for _, q in self.asks[:levels])

    def imbalance(self, levels: int = 10) -> float:
        """Book pressure in ``[-1, 1]``; >0 = more resting bids (buy pressure)."""
        b = self.bid_size(levels)
        a = self.ask_size(levels)
        total = a + b
        if total <= 0:
            return 0.0
        return (b - a) / total

    def size_at(self, price: float, side: str, tol: float) -> float:
        """Resting size within ``tol`` of ``price`` on the ``bid``/``ask`` side."""
        levels = self.bids if side == "bid" else self.asks
        return sum(q for p, q in levels if abs(p - price) <= tol)
