"""Logging helpers.

A single ``setup_logging`` call configures a compact, timestamped formatter that
reads nicely both in a terminal and in GitHub Actions / container logs.
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """Configure root logging once.

    Level is taken from the ``LOG_LEVEL`` env var (default ``INFO``) unless an
    explicit ``level`` is passed.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    lvl_name = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(lvl)

    # websockets is very chatty at DEBUG; keep it one notch quieter.
    logging.getLogger("websockets").setLevel(max(lvl, logging.INFO))
    logging.getLogger("asyncio").setLevel(max(lvl, logging.INFO))

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
