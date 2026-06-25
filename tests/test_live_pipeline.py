"""End-to-end test of the live signal path: trades -> engine -> strategy ->
Signal -> formatted Telegram message, driven through the real Bot object with a
fake notifier (no network).
"""
import asyncio

from auraorderflow.bot import Bot
from auraorderflow.config import AppConfig, StrategyConfig, SymbolConfig
from tests.helpers import raw_bar


def _bullish_responsive_bars():
    # quiet bars build support/POC at 100, then a responsive LONG bar
    # (heavy selling absorbed at the low + bullish CVD divergence)
    bars = [
        raw_bar(open=100, high=100, low=100, close=100, buy=5, sell=5, cvd=float(i))
        for i in range(29)
    ]
    bars.append(
        raw_bar(open=100, high=101, low=99, close=100, buy=5, sell=45, cvd=80.0,
                footprint={100.0: [5.0, 45.0]})
    )
    return bars


def _bot_with_bars(bars):
    cfg = AppConfig(
        symbols=[SymbolConfig(symbol="BTCUSDT", price_step=1.0)],
        strategy=StrategyConfig(min_confidence=60, min_confirmations=2),
    )
    bot = Bot(cfg)
    st = bot.states["BTCUSDT"]
    for b in bars:
        st.engine.bars.append(b)
    st.engine.cvd = st.engine.bars[-1].cvd
    return bot, st


async def test_live_pipeline_emits_and_formats_signal():
    bot, st = _bot_with_bars(_bullish_responsive_bars())
    sent: list[str] = []

    async def fake_send(text, **kwargs):
        sent.append(text)

    bot.notifier.send = fake_send

    bot._evaluate(st)                          # the live per-closed-bar call
    await asyncio.gather(*list(bot._bg_tasks))  # let the fire-and-forget send run

    assert len(sent) == 1
    msg = sent[0]
    for token in ("LONG", "BTCUSDT", "Confidence", "Stop", "Target", "support"):
        assert token in msg, f"missing {token!r} in signal message"
    assert bot.signal_count == 1


async def test_live_pipeline_respects_cooldown():
    bot, st = _bot_with_bars(_bullish_responsive_bars())
    sent: list[str] = []

    async def fake_send(text, **kwargs):
        sent.append(text)

    bot.notifier.send = fake_send

    bot._evaluate(st)
    await asyncio.gather(*list(bot._bg_tasks))
    bot._evaluate(st)                          # immediate repeat within cooldown
    await asyncio.gather(*list(bot._bg_tasks))
    assert len(sent) == 1                       # second signal suppressed
