"""Entry point: ``python -m auraorderflow``."""
from __future__ import annotations

import asyncio

from .bot import Bot
from .config import load_config
from .utils.logging import get_logger, setup_logging


def main() -> None:
    setup_logging()
    log = get_logger("auraorderflow")
    config = load_config()
    if not config.symbols:
        log.error("no symbols configured; edit config.yaml")
        return
    log.info(
        "starting AuraOrderFlow | symbols=%s | telegram=%s",
        config.symbol_names,
        "on" if config.telegram_token else "dry-run",
    )
    bot = Bot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("interrupted")


if __name__ == "__main__":
    main()
