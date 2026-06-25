"""Historical trade data for backtesting.

Source: Binance's official public data dumps at ``data.binance.vision`` — one zip
per symbol per day of USD-M futures aggregated trades. This is *real* historical
order flow (every aggressive trade with its maker flag), and one download covers
a whole day, so it is far cheaper than paginating the REST API.

Trades are yielded as a stream (generator) so a multi-day backtest never holds
more than a few bars in memory.

Note: historical *order-book depth* is not freely available, so book-based
analysers (iceberg / book pressure / liquidity pull) are inactive in backtests.
The trade/footprint/delta core of the strategy is fully exercised.
"""
from __future__ import annotations

import io
import os
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from typing import Iterator

from .orderflow.models import Trade
from .utils.logging import get_logger

log = get_logger(__name__)

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"


def daily_url(symbol: str, day: date) -> str:
    s = symbol.upper()
    return f"{BASE}/{s}/{s}-aggTrades-{day.isoformat()}.zip"


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "AuraOrderFlow/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)


def ensure_daily_zip(symbol: str, day: date, cache_dir: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{symbol.upper()}-aggTrades-{day.isoformat()}.zip")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    url = daily_url(symbol, day)
    log.info("downloading %s", url)
    try:
        _download(url, path)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(url) from exc
        raise
    return path


def iter_daily_aggtrades(
    symbol: str, day: date, cache_dir: str = ".cache"
) -> Iterator[Trade]:
    path = ensure_daily_zip(symbol, day, cache_dir)
    sym = symbol.upper()
    with zipfile.ZipFile(path) as zf:
        member = zf.namelist()[0]
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            for i, line in enumerate(text):
                line = line.strip()
                if not line:
                    continue
                cols = line.split(",")
                # newer dumps ship a header row; skip it
                if i == 0 and not cols[0].lstrip("-").isdigit():
                    continue
                try:
                    price = float(cols[1])
                    qty = float(cols[2])
                    ts = int(cols[5])
                    maker = cols[6].strip().lower() in ("true", "1")
                except (IndexError, ValueError):
                    continue
                yield Trade(
                    symbol=sym, price=price, qty=qty, is_buyer_maker=maker, timestamp=ts
                )


def iter_range(
    symbol: str, start: date, days: int, cache_dir: str = ".cache"
) -> Iterator[Trade]:
    """Yield trades across ``days`` consecutive days starting at ``start``.

    Missing days (no dump published yet) are skipped with a warning rather than
    aborting the whole backtest.
    """
    for offset in range(days):
        day = start + timedelta(days=offset)
        try:
            yield from iter_daily_aggtrades(symbol, day, cache_dir)
        except FileNotFoundError:
            log.warning("no data dump for %s %s — skipped", symbol, day.isoformat())
