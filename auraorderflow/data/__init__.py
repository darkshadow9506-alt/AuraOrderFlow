"""Market-data providers.

``binance`` delivers real, free, real-time order flow (aggressive trades + book
depth). ``UnsupportedMarketProvider`` is an honest placeholder for markets whose
genuine order-flow data is paywalled (CME futures such as NQ/ES, most FX/stock
Level-2). It documents exactly what a paid adapter would need to implement.
"""
from .base import MarketDataProvider, MarketEvent, UnsupportedMarketProvider  # noqa: F401
from .binance import BinanceProvider  # noqa: F401
