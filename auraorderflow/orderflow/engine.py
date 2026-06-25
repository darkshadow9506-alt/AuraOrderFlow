"""The per-symbol order-flow engine.

Feed it trades (and optionally order-book snapshots); it maintains time bars
with footprints, a running cumulative-delta, a rolling window of recent bars and
the latest book snapshot. Closed bars are returned from :meth:`on_trade` so the
caller can run analysis exactly once per completed bar.
"""
from __future__ import annotations

from collections import deque

from .book import BookTracker
from .models import Bar, OrderBookSnapshot, Trade
from .volume_profile import VolumeProfile, build_profile


class OrderFlowEngine:
    def __init__(
        self,
        symbol: str,
        period_s: int = 60,
        price_step: float = 1.0,
        window: int = 240,
        profile_window: int = 240,
    ) -> None:
        self.symbol = symbol
        self.period_ms = period_s * 1000
        self.price_step = price_step
        self.profile_window = profile_window
        self.bars: deque[Bar] = deque(maxlen=window)
        self.current: Bar | None = None
        self.cvd = 0.0
        self.book: OrderBookSnapshot | None = None
        self.book_tracker = BookTracker()

    # -- ingestion ----------------------------------------------------------
    def _bar_start(self, ts: int) -> int:
        return ts - (ts % self.period_ms)

    def on_trade(self, trade: Trade) -> Bar | None:
        """Add a trade. Returns a freshly *closed* bar, or ``None``."""
        start = self._bar_start(trade.timestamp)
        closed: Bar | None = None

        if self.current is None:
            self.current = self._new_bar(start)
        elif start > self.current.start_ms:
            closed = self._close_current()
            # Handle quiet gaps: only the bar that actually receives the trade
            # is created; empty intermediate minutes are simply skipped.
            self.current = self._new_bar(start)

        self.cvd += trade.signed_qty
        self.current.add_trade(trade)
        self.current.cvd = self.cvd
        return closed

    def on_orderbook(self, snapshot: OrderBookSnapshot) -> None:
        self.book = snapshot
        self.book_tracker.update(snapshot)

    def _new_bar(self, start_ms: int) -> Bar:
        return Bar(
            symbol=self.symbol,
            start_ms=start_ms,
            end_ms=start_ms + self.period_ms,
            price_step=self.price_step,
        )

    def _close_current(self) -> Bar | None:
        if self.current is None:
            return None
        self.current.closed = True
        self.bars.append(self.current)
        return self.current

    # -- views --------------------------------------------------------------
    def recent_bars(self, n: int) -> list[Bar]:
        return list(self.bars)[-n:]

    def volume_profile(self, n: int | None = None) -> VolumeProfile:
        n = n or self.profile_window
        return build_profile(self.recent_bars(n), self.price_step)

    @property
    def last_price(self) -> float | None:
        if self.current is not None and self.current.trades:
            return self.current.close
        if self.bars:
            return self.bars[-1].close
        return None
