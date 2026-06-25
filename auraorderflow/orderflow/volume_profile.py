"""Volume profile: POC, value area (VAH/VAL) and HVN/LVN detection.

Built by aggregating the footprints of a rolling window of bars into a single
price -> volume histogram. These structural levels are *where* order flow is
allowed to fire signals (rule #1: don't trade the middle of the range).
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Bar


@dataclass(slots=True)
class VolumeProfile:
    price_step: float
    histogram: dict[float, float]          # price level -> total volume
    poc: float | None = None               # point of control
    vah: float | None = None               # value area high
    val: float | None = None               # value area low
    hvns: tuple[float, ...] = ()            # high-volume nodes
    lvns: tuple[float, ...] = ()            # low-volume nodes (auction gaps)

    @property
    def total_volume(self) -> float:
        return sum(self.histogram.values())


def build_profile(
    bars: list[Bar],
    price_step: float,
    value_area_pct: float = 0.70,
) -> VolumeProfile:
    """Aggregate ``bars`` into a :class:`VolumeProfile`.

    The value area is the contiguous band around the POC that holds
    ``value_area_pct`` of total traded volume, expanded one level at a time
    toward whichever neighbour holds more volume (standard TPO/volume method).
    """
    hist: dict[float, float] = {}
    for bar in bars:
        for price, (buy, sell) in bar.footprint.items():
            hist[price] = hist.get(price, 0.0) + buy + sell

    profile = VolumeProfile(price_step=price_step, histogram=hist)
    if not hist:
        return profile

    levels = sorted(hist)
    poc = max(hist, key=lambda p: hist[p])
    profile.poc = poc

    # --- value area expansion around the POC -------------------------------
    target = profile.total_volume * value_area_pct
    poc_idx = levels.index(poc)
    lo = hi = poc_idx
    acc = hist[poc]
    while acc < target and (lo > 0 or hi < len(levels) - 1):
        below = hist[levels[lo - 1]] if lo > 0 else -1.0
        above = hist[levels[hi + 1]] if hi < len(levels) - 1 else -1.0
        if above >= below and hi < len(levels) - 1:
            hi += 1
            acc += hist[levels[hi]]
        elif lo > 0:
            lo -= 1
            acc += hist[levels[lo]]
        else:
            hi += 1
            acc += hist[levels[hi]]
    profile.val = levels[lo]
    profile.vah = levels[hi]

    # --- HVN / LVN classification ------------------------------------------
    vols = list(hist.values())
    mean_v = sum(vols) / len(vols)
    hvns = tuple(sorted(p for p, v in hist.items() if v >= mean_v * 1.5))
    lvns = tuple(sorted(p for p, v in hist.items() if v <= mean_v * 0.35))
    profile.hvns = hvns
    profile.lvns = lvns
    return profile
