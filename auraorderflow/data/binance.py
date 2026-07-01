"""Binance USD-M Futures real-time order-flow provider.

Uses the public combined websocket stream (no API key required for market
data):

* ``<symbol>@aggTrade``         - every aggressive trade with the maker flag,
                                  which gives us the aggressor side and therefore
                                  delta / CVD / footprint.
* ``<symbol>@depth20@100ms``    - top-20 book snapshots for resting-liquidity
                                  analysis (absorption / book pressure).

The stream auto-reconnects with exponential backoff and keeps running until the
shared ``stop`` event is set.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import AsyncIterator

import websockets

from ..orderflow.models import OrderBookSnapshot, Trade
from ..utils.logging import get_logger
from .base import MarketDataProvider, MarketEvent

log = get_logger(__name__)

FUTURES_WS = "wss://fstream.binance.com/ws"


class BinanceProvider(MarketDataProvider):
    name = "binance-futures"

    def __init__(
        self,
        symbols: list[str],
        depth_levels: int = 20,
        depth_interval_ms: int = 100,
        base_url: str = FUTURES_WS,
    ) -> None:
        if not symbols:
            raise ValueError("BinanceProvider requires at least one symbol")
        self.symbols = [s.lower() for s in symbols]
        self.depth_levels = depth_levels
        self.depth_interval_ms = depth_interval_ms
        self.base_url = base_url
        # diagnostics
        self.etype_counts: Counter[str] = Counter()
        self._samples_logged = 0

    def _params(self) -> list[str]:
        """Stream names to subscribe to (aggTrade + partial depth per symbol)."""
        params: list[str] = []
        for s in self.symbols:
            # @trade (individual trades) is what actually streams on this
            # endpoint; @aggTrade returns nothing here. @trade is finer-grained
            # and carries the same maker flag, so it's ideal for footprints.
            params.append(f"{s}@trade")
            params.append(f"{s}@depth{self.depth_levels}@{self.depth_interval_ms}ms")
        return params

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[MarketEvent]:
        backoff = 1.0
        while not stop.is_set():
            try:
                log.info("connecting to %s (%d symbols)", self.name, len(self.symbols))
                async with websockets.connect(
                    self.base_url, ping_interval=20, ping_timeout=20, max_queue=2048
                ) as ws:
                    backoff = 1.0  # reset on a successful connect
                    # explicit SUBSCRIBE — the ?streams= URL silently dropped
                    # the aggTrade streams (only depth was delivered).
                    params = self._params()
                    await ws.send(json.dumps(
                        {"method": "SUBSCRIBE", "params": params, "id": 1}
                    ))
                    log.info("subscribed to %d streams; streaming order flow",
                             len(params))
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            continue
                        event = self._parse(raw)
                        if event is not None:
                            yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any ws error
                if stop.is_set():
                    break
                log.warning("stream error (%s); reconnecting in %.0fs", exc, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)
        log.info("%s stream stopped", self.name)

    # -- parsing ------------------------------------------------------------
    def _parse(self, raw: str) -> MarketEvent | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        data = msg.get("data", msg)
        etype = data.get("e")

        # diagnostics: what is Binance actually sending?
        self.etype_counts[str(etype)] += 1
        if self._samples_logged < 4:
            self._samples_logged += 1
            log.info("sample msg %d: stream=%s keys=%s",
                     self._samples_logged, msg.get("stream"), list(data.keys()))

        # both @trade (individual) and @aggTrade carry price/qty/maker-flag
        if etype in ("trade", "aggTrade"):
            try:
                return (
                    "trade",
                    Trade(
                        symbol=data["s"].upper(),
                        price=float(data["p"]),
                        qty=float(data["q"]),
                        is_buyer_maker=bool(data["m"]),
                        timestamp=int(data.get("T") or data.get("E")),
                    ),
                )
            except (KeyError, ValueError, TypeError):
                return None

        if etype == "depthUpdate" or "b" in data or "bids" in data:
            bids = data.get("b") or data.get("bids") or []
            asks = data.get("a") or data.get("asks") or []
            try:
                snap = OrderBookSnapshot(
                    symbol=str(data.get("s", "")).upper(),
                    timestamp=int(data.get("T") or data.get("E") or 0),
                    bids=[(float(p), float(q)) for p, q in bids if float(q) > 0],
                    asks=[(float(p), float(q)) for p, q in asks if float(q) > 0],
                )
            except (ValueError, TypeError):
                return None
            return ("book", snap)
        return None
