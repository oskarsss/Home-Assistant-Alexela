"""Pure helpers for Alexela consumption analytics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def constant_daily_average(
    daily_totals: Sequence[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Return one constant all-history average point for every collected day."""
    if not daily_totals:
        return []

    average = sum(value for _, value in daily_totals) / len(daily_totals)
    return [(start, average) for start, _ in daily_totals]
