"""Order-book state tracking over time.

A single :class:`OrderBookSnapshot` only shows *now*; real microstructure tells
(pulling/spoofing, sustained book pressure) need the recent *history* of the
book. :class:`BookTracker` keeps a short rolling window of snapshots and derives:

* a smoothed book imbalance (sustained DOM pressure), and
* "liquidity pulls" — a large resting side that recently vanished, the classic
  spoof / support-pulled-before-the-break tell.
"""
from __future__ import annotations

from collections import deque

from .models import OrderBookSnapshot


class BookTracker:
    def __init__(self, maxlen: int = 60) -> None:
        self.snapshots: deque[OrderBookSnapshot] = deque(maxlen=maxlen)

    def update(self, snap: OrderBookSnapshot) -> None:
        self.snapshots.append(snap)

    @property
    def latest(self) -> OrderBookSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def avg_imbalance(self, levels: int = 10) -> float:
        """Time-averaged book imbalance in ``[-1, 1]`` (sustained pressure)."""
        if not self.snapshots:
            return 0.0
        return sum(s.imbalance(levels) for s in self.snapshots) / len(self.snapshots)

    def detect_pull(
        self, levels: int = 10, drop_ratio: float = 0.6
    ) -> tuple[str, float] | None:
        """Detect a side whose resting size collapsed across the window.

        Returns ``(side, strength)`` where ``side`` is the *directional bias*:
        a pulled **bid** removes support => ``short``; a pulled **ask** removes
        resistance => ``long``. ``None`` when nothing pulled.
        """
        if len(self.snapshots) < 5:
            return None
        cur = self.snapshots[-1]
        prev = list(self.snapshots)[:-1]
        max_bid = max(s.bid_size(levels) for s in prev)
        max_ask = max(s.ask_size(levels) for s in prev)
        cur_bid = cur.bid_size(levels)
        cur_ask = cur.ask_size(levels)

        pulled_bid = max_bid > 0 and cur_bid < max_bid * (1 - drop_ratio)
        pulled_ask = max_ask > 0 and cur_ask < max_ask * (1 - drop_ratio)
        # report the larger pull only, to avoid double-counting two-sided thinning
        bid_drop = 1 - (cur_bid / max_bid) if max_bid > 0 else 0.0
        ask_drop = 1 - (cur_ask / max_ask) if max_ask > 0 else 0.0
        if pulled_bid and bid_drop >= ask_drop:
            return ("short", min(1.0, bid_drop))
        if pulled_ask:
            return ("long", min(1.0, ask_drop))
        return None
