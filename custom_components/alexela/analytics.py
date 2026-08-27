"""Pure helpers for Alexela consumption analytics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta


def constant_daily_average(
    daily_totals: Sequence[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Return one constant all-history average point for every collected day."""
    if not daily_totals:
        return []

    average = sum(value for _, value in daily_totals) / len(daily_totals)
    return [(start, average) for start, _ in daily_totals]


def rolling_import_days(
    published: list[date],
    newest: date,
    imported_through: date | None,
    *,
    reconcile_days: int,
) -> list[date]:
    """Choose the unlimited contiguous backfill and rolling import window.

    The rolling window is the normal ingestion path: it includes newly
    published dates as well as corrections to dates already imported. Every
    older pending date is returned in order; the caller stops at the first
    daily payload it cannot parse and retries that boundary later.
    """
    available = sorted({day for day in published if day <= newest})
    pending = [
        day
        for day in available
        if imported_through is None or day > imported_through
    ]
    reconcile_start = newest - timedelta(days=reconcile_days - 1)
    recent = [day for day in available if day >= reconcile_start]
    return sorted(set(pending) | set(recent))
