"""The bot: wire data -> engine -> strategy -> Telegram.

One :class:`OrderFlowEngine` per symbol consumes the shared provider stream. On
each closed bar the :class:`StrategyEngine` is asked for a signal; qualifying
signals are de-duplicated by a per-(symbol, side) cooldown and pushed to
Telegram. A concurrent task answers Telegram commands. The whole thing stops
cleanly when ``MAX_RUNTIME_SECONDS`` elapses (for GitHub Actions' 6h cap) or on
SIGINT/SIGTERM.
"""
from __future__ import annotations

import asyncio
import signal
import time
from collections import Counter

from .config import AppConfig, SymbolConfig
from .data import BinanceProvider
from .notify import TelegramNotifier
from .orderflow import OrderFlowEngine
from .orderflow.models import OrderBookSnapshot, Trade
from .signals import StrategyEngine
from .utils.logging import get_logger

log = get_logger(__name__)


class SymbolState:
    def __init__(self, cfg: SymbolConfig, engine: OrderFlowEngine) -> None:
        self.cfg = cfg
        self.engine = engine


class Bot:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.stop = asyncio.Event()
        self.started_at = time.time()
        self.signal_count = 0
        self._last_signal: dict[tuple[str, str], int] = {}
        # strong refs to in-flight send tasks so they are not GC'd mid-flight
        self._bg_tasks: set[asyncio.Task] = set()
        # diagnostics: histogram of why bars did/didn't produce a signal
        self._diag_reasons: Counter[str] = Counter()
        self._diag_bars = 0
        self._diag_best = 0.0
        self._rx_trades = 0
        self._rx_books = 0

        self.strategy = StrategyEngine(
            min_confidence=config.strategy.min_confidence,
            min_confirmations=config.strategy.min_confirmations,
            require_level=config.strategy.require_level,
            level_tolerance_pct=config.strategy.level_tolerance_pct,
            confidence_scale=config.strategy.confidence_scale,
            risk_reward=config.strategy.risk_reward,
            imbalance_ratio=config.strategy.imbalance_ratio,
            htf_lookback_minutes=config.strategy.htf_lookback_minutes,
            require_htf_alignment=config.strategy.require_htf_alignment,
            use_vwap=config.strategy.use_vwap,
            use_prev_day_levels=config.strategy.use_prev_day_levels,
        )

        self.states: dict[str, SymbolState] = {}
        for s in config.symbols:
            engine = OrderFlowEngine(
                symbol=s.symbol,
                period_s=config.bar_period_seconds,
                price_step=s.price_step,
                window=config.history_window,
                profile_window=config.profile_window,
            )
            self.states[s.symbol] = SymbolState(s, engine)

        self.provider = BinanceProvider(list(self.states.keys()))
        self.notifier = TelegramNotifier(config.telegram_token, config.telegram_chat_ids)

    # -- lifecycle ----------------------------------------------------------
    async def run(self) -> None:
        self._install_signal_handlers()
        async with self.notifier:
            await self.notifier.send(self._startup_message())
            tasks = [
                asyncio.create_task(self._consume(), name="consume"),
                asyncio.create_task(
                    self.notifier.listen_commands(self.stop, self._handle_command),
                    name="commands",
                ),
                asyncio.create_task(self._diag_heartbeat(), name="diag"),
            ]
            if self.config.max_runtime_seconds > 0:
                tasks.append(asyncio.create_task(self._runtime_guard(), name="guard"))
            try:
                await self.stop.wait()
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.notifier.send("🛑 <b>AuraOrderFlow</b> stopped.")

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):
                pass  # not available on some platforms

    async def _diag_heartbeat(self) -> None:
        """Every 60s, log data-flow + why bars are/aren't producing signals."""
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                total_bars = sum(len(s.engine.bars) for s in self.states.values())
                sym0 = next(iter(self.states.values()))
                cur = "yes" if sym0.engine.current is not None else "no"
                lp = sym0.engine.last_price
                top = ", ".join(
                    f"{r}={n}" for r, n in self._diag_reasons.most_common(6)
                )
                log.info(
                    "diag | rx_trades=%d rx_books=%d bars=%d cur=%s px=%s | "
                    "evaluated=%d signals=%d best=%.0f | etypes=%s | %s",
                    self._rx_trades, self._rx_books, total_bars, cur,
                    f"{lp:g}" if lp else "-",
                    self._diag_bars, self.signal_count, self._diag_best,
                    dict(self.provider.etype_counts), top or "-",
                )
                self._diag_reasons.clear()
                self._diag_best = 0.0

    async def _runtime_guard(self) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), self.config.max_runtime_seconds)
        except asyncio.TimeoutError:
            log.info("max runtime reached; shutting down for clean restart")
            self.stop.set()

    # -- core loop ----------------------------------------------------------
    async def _consume(self) -> None:
        try:
            async for kind, payload in self.provider.stream(self.stop):
                if kind == "trade":
                    self._on_trade(payload)  # type: ignore[arg-type]
                elif kind == "book":
                    self._on_book(payload)  # type: ignore[arg-type]
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("consume loop crashed: %s", exc)
            self.stop.set()

    def _on_trade(self, trade: Trade) -> None:
        self._rx_trades += 1
        state = self.states.get(trade.symbol)
        if state is None:
            return
        closed = state.engine.on_trade(trade)
        if closed is not None:
            self._evaluate(state)

    def _on_book(self, book: OrderBookSnapshot) -> None:
        self._rx_books += 1
        state = self.states.get(book.symbol)
        if state is not None:
            state.engine.on_orderbook(book)

    def _evaluate(self, state: SymbolState) -> None:
        signal_obj = self.strategy.evaluate(state.engine)
        # diagnostics: record why this closed bar did / didn't fire
        self._diag_bars += 1
        self._diag_reasons[self.strategy.last_reason] += 1
        if self.strategy.last_confidence > self._diag_best:
            self._diag_best = self.strategy.last_confidence
        if signal_obj is None:
            return
        key = signal_obj.dedup_key()
        now_ms = int(time.time() * 1000)
        cooldown = self.config.strategy.signal_cooldown_seconds * 1000
        last = self._last_signal.get(key, 0)
        if now_ms - last < cooldown:
            return
        self._last_signal[key] = now_ms
        self.signal_count += 1
        # label override (e.g. PAXGUSDT -> GOLD)
        text = signal_obj.to_telegram()
        if state.cfg.alias:
            text = text.replace(signal_obj.symbol, state.cfg.label, 1)
        log.info(
            "SIGNAL %s %s @ %g (%.0f%%)",
            signal_obj.side, signal_obj.symbol, signal_obj.price, signal_obj.confidence,
        )
        task = asyncio.create_task(self.notifier.send(text))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # -- telegram commands --------------------------------------------------
    async def _handle_command(self, cmd: str, args: str) -> str | None:
        if cmd in ("start", "help"):
            return (
                "<b>AuraOrderFlow</b> — order-flow signal bot\n\n"
                "/status — uptime, signals, live prices\n"
                "/symbols — markets being watched\n"
                "/levels &lt;symbol&gt; — volume-profile levels\n"
                "/ping — health check"
            )
        if cmd == "ping":
            return "🏓 pong"
        if cmd == "status":
            return self._status_message()
        if cmd == "symbols":
            return self._symbols_message()
        if cmd == "levels":
            return self._levels_message(args.strip().upper())
        return None

    def _status_message(self) -> str:
        up = int(time.time() - self.started_at)
        h, rem = divmod(up, 3600)
        m, s = divmod(rem, 60)
        lines = [
            "📊 <b>AuraOrderFlow status</b>",
            f"⏱ uptime: {h}h {m}m {s}s",
            f"🔔 signals sent: {self.signal_count}",
            "",
        ]
        for sym, st in self.states.items():
            price = st.engine.last_price
            bars = len(st.engine.bars)
            price_txt = f"{price:g}" if price else "—"
            lines.append(f"• {st.cfg.label}: {price_txt}  ({bars} bars)")
        return "\n".join(lines)

    def _symbols_message(self) -> str:
        lines = ["✅ <b>Live order flow</b>"]
        for st in self.states.values():
            lines.append(f"• {st.cfg.label} ({st.cfg.symbol})")
        if self.config.unsupported:
            lines.append("")
            lines.append("⛔️ <b>Needs a paid feed</b>")
            for u in self.config.unsupported:
                lines.append(f"• {u.symbol} — {u.reason}")
        return "\n".join(lines)

    def _levels_message(self, symbol: str) -> str:
        if not symbol:
            example = next(iter(self.states.values())).cfg.label
            return f"usage: /levels &lt;symbol&gt; — e.g. /levels {example}"
        state = self.states.get(symbol)
        if state is None:
            for st in self.states.values():
                if st.cfg.label.upper() == symbol:
                    state = st
                    break
        if state is None:
            return f"unknown symbol '{symbol}'. Try /symbols."
        prof = state.engine.volume_profile()
        if prof.poc is None:
            return f"{state.cfg.label}: not enough data yet."
        return "\n".join(
            [
                f"📍 <b>{state.cfg.label}</b> volume profile",
                f"POC: <code>{prof.poc:g}</code>",
                f"VAH: <code>{prof.vah:g}</code>",
                f"VAL: <code>{prof.val:g}</code>",
                f"HVNs: {', '.join(f'{p:g}' for p in prof.hvns[:6]) or '—'}",
                f"LVNs: {', '.join(f'{p:g}' for p in prof.lvns[:6]) or '—'}",
            ]
        )

    def _startup_message(self) -> str:
        syms = ", ".join(st.cfg.label for st in self.states.values())
        return (
            "🚀 <b>AuraOrderFlow</b> is live\n"
            f"Watching: {syms}\n"
            f"Bar: {self.config.bar_period_seconds}s · "
            f"min confidence: {self.config.strategy.min_confidence:.0f}%\n"
            "Send /help for commands."
        )
