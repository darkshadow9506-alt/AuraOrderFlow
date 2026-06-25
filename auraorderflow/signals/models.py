"""The :class:`Signal` value object plus formatting helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Signal:
    symbol: str
    side: str  # LONG / SHORT
    price: float
    timestamp: int  # epoch ms
    confidence: float  # 0..100
    reasons: list[str] = field(default_factory=list)
    level: str = ""  # the structural level that qualified the trade
    stop: float | None = None
    target: float | None = None

    @property
    def rr(self) -> float | None:
        if self.stop is None or self.target is None:
            return None
        risk = abs(self.price - self.stop)
        if risk <= 0:
            return None
        return abs(self.target - self.price) / risk

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)

    def dedup_key(self) -> tuple[str, str]:
        return (self.symbol, self.side)

    def to_telegram(self) -> str:
        arrow = "🟢 LONG" if self.side == "LONG" else "🔴 SHORT"
        lines = [
            f"{arrow}  <b>{self.symbol}</b>",
            f"💰 Price: <code>{self.price:g}</code>",
            f"🎯 Confidence: <b>{self.confidence:.0f}%</b>",
        ]
        if self.level:
            lines.append(f"📍 Level: {self.level}")
        if self.stop is not None:
            lines.append(f"🛑 Stop: <code>{self.stop:g}</code>")
        if self.target is not None:
            rr = self.rr
            rr_txt = f" (R:R ≈ {rr:.1f})" if rr else ""
            lines.append(f"✅ Target: <code>{self.target:g}</code>{rr_txt}")
        if self.reasons:
            lines.append("")
            lines.append("<b>Order-flow confluence:</b>")
            lines.extend(f"• {r}" for r in self.reasons)
        lines.append("")
        lines.append(
            f"🕒 {self.dt:%Y-%m-%d %H:%M} UTC"
        )
        lines.append(
            "<i>Signal only — not financial advice. "
            "Manage your own risk.</i>"
        )
        return "\n".join(lines)
