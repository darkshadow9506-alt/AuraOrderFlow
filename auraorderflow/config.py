"""Configuration loading.

Settings come from two places, merged at startup:

* ``config.yaml`` - what to trade and how the strategy behaves (committed).
* environment / ``.env`` - secrets and deployment knobs (never committed):
  ``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_CHAT_ID`` (comma-separated for several
  chats), ``LOG_LEVEL``, ``MAX_RUNTIME_SECONDS``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

try:  # optional in production; handy locally
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass


@dataclass(slots=True)
class SymbolConfig:
    symbol: str
    price_step: float = 1.0
    alias: str | None = None

    @property
    def label(self) -> str:
        return self.alias or self.symbol


@dataclass(slots=True)
class StrategyConfig:
    min_confidence: float = 60.0
    min_confirmations: int = 2
    require_level: bool = True
    level_tolerance_pct: float = 0.0015
    confidence_scale: float = 2.6
    risk_reward: float = 2.0
    imbalance_ratio: float = 3.0
    signal_cooldown_seconds: int = 900


@dataclass(slots=True)
class UnsupportedMarket:
    symbol: str
    reason: str = ""


@dataclass(slots=True)
class AppConfig:
    bar_period_seconds: int = 60
    profile_window: int = 240
    history_window: int = 300
    symbols: list[SymbolConfig] = field(default_factory=list)
    unsupported: list[UnsupportedMarket] = field(default_factory=list)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)

    # runtime / secrets (from env)
    telegram_token: str | None = None
    telegram_chat_ids: list[str] = field(default_factory=list)
    max_runtime_seconds: int = 0  # 0 == run forever

    @property
    def symbol_names(self) -> list[str]:
        return [s.symbol for s in self.symbols]


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    cfg_path = Path(path or os.getenv("AURA_CONFIG") or "config.yaml")
    raw: dict = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text()) or {}

    symbols = [
        SymbolConfig(
            symbol=str(s["symbol"]).upper(),
            price_step=float(s.get("price_step", 1.0)),
            alias=s.get("alias"),
        )
        for s in raw.get("symbols", [])
    ]
    unsupported = [
        UnsupportedMarket(symbol=str(u["symbol"]).upper(), reason=u.get("reason", ""))
        for u in raw.get("unsupported", [])
    ]
    s_raw = raw.get("strategy", {}) or {}
    strategy = StrategyConfig(
        min_confidence=float(s_raw.get("min_confidence", 60.0)),
        min_confirmations=int(s_raw.get("min_confirmations", 2)),
        require_level=bool(s_raw.get("require_level", True)),
        level_tolerance_pct=float(s_raw.get("level_tolerance_pct", 0.0015)),
        confidence_scale=float(s_raw.get("confidence_scale", 2.6)),
        risk_reward=float(s_raw.get("risk_reward", 2.0)),
        imbalance_ratio=float(s_raw.get("imbalance_ratio", 3.0)),
        signal_cooldown_seconds=int(s_raw.get("signal_cooldown_seconds", 900)),
    )

    chat_ids = [
        c.strip()
        for c in (os.getenv("TELEGRAM_CHAT_ID", "")).split(",")
        if c.strip()
    ]

    return AppConfig(
        bar_period_seconds=int(raw.get("bar_period_seconds", 60)),
        profile_window=int(raw.get("profile_window", 240)),
        history_window=int(raw.get("history_window", 300)),
        symbols=symbols,
        unsupported=unsupported,
        strategy=strategy,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_ids=chat_ids,
        max_runtime_seconds=_env_int("MAX_RUNTIME_SECONDS", 0),
    )
