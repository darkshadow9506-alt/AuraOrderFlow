"""Provider interface shared by every market-data source.

A provider is an async generator of :data:`MarketEvent` tuples:

    ("trade", Trade)            - one aggressive trade
    ("book",  OrderBookSnapshot)- a refreshed top-of-book snapshot

Consumers iterate ``async for kind, payload in provider.stream(stop):`` and the
provider is responsible for connecting, parsing and (re)connecting on failure
until ``stop`` is set.
"""
from __future__ import annotations

import abc
import asyncio
from typing import AsyncIterator, Tuple, Union

from ..orderflow.models import OrderBookSnapshot, Trade

MarketEvent = Tuple[str, Union[Trade, OrderBookSnapshot]]


class MarketDataProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def stream(self, stop: asyncio.Event) -> AsyncIterator[MarketEvent]:
        """Yield market events until ``stop`` is set."""
        raise NotImplementedError


class UnsupportedMarketProvider(MarketDataProvider):
    """Placeholder for markets that require a paid order-flow feed.

    NQ/ES (CME) and most FX/stock Level-2 data are not freely available. To add
    them, implement a provider that connects to a licensed feed (e.g. Databento,
    Rithmic, CQG, dxFeed) and emits the same :data:`MarketEvent` tuples — the
    rest of the engine is feed-agnostic and will work unchanged.
    """

    def __init__(self, symbol: str, reason: str = "") -> None:
        self.symbol = symbol
        self.reason = reason or (
            "real-time order-flow data for this market requires a paid feed "
            "(e.g. Databento / Rithmic / CQG for CME futures)"
        )
        self.name = f"unsupported:{symbol}"

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[MarketEvent]:
        raise NotImplementedError(
            f"{self.symbol}: {self.reason}. See data/base.py for how to plug in "
            "a licensed adapter."
        )
        # make this an async generator for type purposes
        yield  # pragma: no cover
