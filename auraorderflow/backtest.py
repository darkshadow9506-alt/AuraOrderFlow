"""Backtester for the order-flow strategy.

It replays historical trades through the *same* `OrderFlowEngine` and
`StrategyEngine` used live, collects the signals, then simulates each one
forward bar-by-bar against its own stop/target to measure win rate, expectancy
(average R) and profit factor.

Honesty notes baked into the method:
* One position per symbol+side at a time (no pyramiding / overlapping trades).
* If a single bar's range touches *both* stop and target, it is counted as a
  **loss** (pessimistic — we cannot know intрабar order from bars alone).
* Book-based analysers are inactive (no free historical depth), so this measures
  the trade/footprint/delta core of the strategy.
* No leverage; results are in R multiples (1R = the trade's own stop distance).
  Optional per-side fee is charged in R.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from .config import load_config
from .orderflow.engine import OrderFlowEngine
from .orderflow.models import Bar, Trade
from .signals.models import Signal
from .signals.strategy import StrategyEngine
from .utils.logging import get_logger, setup_logging

log = get_logger(__name__)


@dataclass(slots=True)
class TradeResult:
    signal: Signal
    exit_price: float
    outcome: str  # win | loss | timeout
    r_multiple: float
    bars_held: int


def simulate_trade(
    signal: Signal,
    bars: list[Bar],
    start_idx: int,
    max_hold: int,
    fee_r: float = 0.0,
) -> TradeResult | None:
    """Walk forward from ``start_idx+1`` and resolve the trade to stop/target."""
    if signal.stop is None or signal.target is None:
        return None
    entry = signal.price
    risk = abs(entry - signal.stop)
    if risk <= 0:
        return None
    long = signal.side == "LONG"
    direction = 1 if long else -1

    end = min(len(bars), start_idx + 1 + max_hold)
    for j in range(start_idx + 1, end):
        b = bars[j]
        if long:
            hit_stop, hit_tgt = b.low <= signal.stop, b.high >= signal.target
        else:
            hit_stop, hit_tgt = b.high >= signal.stop, b.low <= signal.target
        if hit_stop and hit_tgt:
            exit_price, outcome = signal.stop, "loss"  # pessimistic
        elif hit_tgt:
            exit_price, outcome = signal.target, "win"
        elif hit_stop:
            exit_price, outcome = signal.stop, "loss"
        else:
            continue
        r = direction * (exit_price - entry) / risk - fee_r
        return TradeResult(signal, exit_price, outcome, r, j - start_idx)

    # no resolution within max_hold -> mark to last available close
    if end - 1 <= start_idx:
        return None
    last = bars[end - 1]
    r = direction * (last.close - entry) / risk - fee_r
    return TradeResult(signal, last.close, "timeout", r, end - 1 - start_idx)


@dataclass(slots=True)
class BacktestReport:
    symbol: str
    bars_built: int
    span: str
    results: list[TradeResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    def _subset(self, side: str | None) -> list[TradeResult]:
        if side is None:
            return self.results
        return [r for r in self.results if r.signal.side == side]

    def win_rate(self, side: str | None = None) -> float:
        rs = self._subset(side)
        if not rs:
            return 0.0
        return sum(1 for r in rs if r.r_multiple > 0) / len(rs)

    def expectancy(self, side: str | None = None) -> float:
        rs = self._subset(side)
        return sum(r.r_multiple for r in rs) / len(rs) if rs else 0.0

    def total_r(self, side: str | None = None) -> float:
        return sum(r.r_multiple for r in self._subset(side))

    def profit_factor(self, side: str | None = None) -> float:
        rs = self._subset(side)
        gains = sum(r.r_multiple for r in rs if r.r_multiple > 0)
        losses = -sum(r.r_multiple for r in rs if r.r_multiple < 0)
        if losses <= 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    def format(self) -> str:
        def block(label: str, side: str | None) -> str:
            rs = self._subset(side)
            if not rs:
                return f"  {label:<6} n=0"
            pf = self.profit_factor(side)
            pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
            return (
                f"  {label:<6} n={len(rs):<4} "
                f"win={self.win_rate(side)*100:5.1f}%  "
                f"avgR={self.expectancy(side):+.3f}  "
                f"totR={self.total_r(side):+7.2f}  PF={pf_txt}"
            )

        lines = [
            f"━━ {self.symbol} ━━ {self.span}",
            f"  bars={self.bars_built}  signals/trades={self.n}",
            block("ALL", None),
            block("LONG", "LONG"),
            block("SHORT", "SHORT"),
        ]
        return "\n".join(lines)


class Backtester:
    def __init__(
        self,
        symbol: str,
        price_step: float,
        *,
        bar_period_s: int = 60,
        profile_window: int = 240,
        max_hold: int = 60,
        fee_r: float = 0.0,
        strategy: StrategyEngine | None = None,
    ) -> None:
        self.symbol = symbol
        self.price_step = price_step
        self.bar_period_s = bar_period_s
        self.profile_window = profile_window
        self.max_hold = max_hold
        self.fee_r = fee_r
        self.strategy = strategy or StrategyEngine()

    def run(self, trades: Iterable[Trade], span: str = "") -> BacktestReport:
        engine = OrderFlowEngine(
            symbol=self.symbol,
            period_s=self.bar_period_s,
            price_step=self.price_step,
            window=max(self.profile_window, 320),
            profile_window=self.profile_window,
        )
        all_bars: list[Bar] = []
        pending: list[tuple[int, Signal]] = []

        for trade in trades:
            closed = engine.on_trade(trade)
            if closed is None:
                continue
            all_bars.append(closed)
            sig = self.strategy.evaluate(engine)
            if sig is not None:
                pending.append((len(all_bars) - 1, sig))

        report = BacktestReport(self.symbol, len(all_bars), span)
        busy_until = -1
        for idx, sig in pending:
            if idx <= busy_until:
                continue  # one position at a time
            res = simulate_trade(sig, all_bars, idx, self.max_hold, self.fee_r)
            if res is None:
                continue
            report.results.append(res)
            busy_until = idx + res.bars_held
        return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _price_step_for(symbol: str, override: float | None) -> float:
    if override is not None:
        return override
    for s in load_config().symbols:
        if s.symbol == symbol.upper():
            return s.price_step
    return 1.0


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description="Backtest the AuraOrderFlow strategy")
    p.add_argument("--symbols", default="BTCUSDT",
                   help="comma-separated, e.g. BTCUSDT,ETHUSDT")
    p.add_argument("--days", type=int, default=3, help="number of days to test")
    p.add_argument("--end", default="", help="last day YYYY-MM-DD (default: yesterday)")
    p.add_argument("--price-step", type=float, default=None)
    p.add_argument("--bar-period", type=int, default=60)
    p.add_argument("--max-hold", type=int, default=60, help="max bars to hold a trade")
    p.add_argument("--fee-r", type=float, default=0.0, help="round-trip fee in R")
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--rr", type=float, default=None, help="risk:reward override")
    p.add_argument("--cache", default=".cache")
    args = p.parse_args()

    # local import so unit tests need no network module loaded
    from . import history

    end = (
        date.fromisoformat(args.end)
        if args.end
        else date.today() - timedelta(days=1)
    )
    start = end - timedelta(days=args.days - 1)
    span = f"{start.isoformat()} → {end.isoformat()}"

    strat_kwargs: dict = {}
    if args.min_confidence is not None:
        strat_kwargs["min_confidence"] = args.min_confidence
    if args.rr is not None:
        strat_kwargs["risk_reward"] = args.rr

    reports: list[BacktestReport] = []
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        bt = Backtester(
            symbol=symbol,
            price_step=_price_step_for(symbol, args.price_step),
            bar_period_s=args.bar_period,
            max_hold=args.max_hold,
            fee_r=args.fee_r,
            strategy=StrategyEngine(**strat_kwargs) if strat_kwargs else None,
        )
        trades = history.iter_range(symbol, start, args.days, cache_dir=args.cache)
        report = bt.run(trades, span=span)
        reports.append(report)
        print(report.format())
        print()

    # portfolio aggregate
    if len(reports) > 1:
        all_res = [r for rep in reports for r in rep.results]
        agg = BacktestReport("PORTFOLIO", sum(r.bars_built for r in reports), span)
        agg.results = all_res
        print(agg.format())


if __name__ == "__main__":
    main()
