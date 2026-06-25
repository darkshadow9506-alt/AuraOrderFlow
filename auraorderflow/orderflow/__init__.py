"""Order-flow engine: turns a raw trade stream into structured order-flow state.

Pipeline:

    trades --> Bar (OHLC + footprint + delta) --> rolling window
                                               --> VolumeProfile (POC/VAH/VAL)
                                               --> analysers (absorption,
                                                   imbalance, divergence, ...)
"""
from .models import Bar, OrderBookSnapshot, Trade  # noqa: F401
from .engine import OrderFlowEngine  # noqa: F401
