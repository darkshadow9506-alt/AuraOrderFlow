"""AuraOrderFlow - a real-time order-flow analysis & alerting bot.

The package is split into focused sub-modules:

* ``data``      - market-data providers (Binance Futures websocket, ...).
* ``orderflow`` - the order-flow engine: trades -> bars -> footprint / delta /
                  volume-profile.
* ``signals``   - strategy logic that turns order-flow state into trade signals.
* ``notify``    - delivery channels (Telegram).

Nothing in here executes live trades. The bot is *signal only*: it analyses the
market and sends alerts. Risk and execution stay in human hands.
"""

__version__ = "0.1.0"
