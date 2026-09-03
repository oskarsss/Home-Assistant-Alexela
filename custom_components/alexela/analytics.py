"""Pure helpers for Alexela consumption analytics."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date, datetime, timedelta, tzinfo
from typing import Any


def constant_daily_average(
    daily_totals: Sequence[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Return one constant all-history average point for every collected day."""
    if not daily_totals:
        return []

    average = sum(value for _, value in daily_totals) / len(daily_totals)
    return [(start, average) for start, _ in daily_totals]


def typical_hourly_profile(
    hourly_totals: Sequence[tuple[datetime, float]],
    zone: tzinfo,
) -> list[tuple[datetime, float]]:
    """Return the matching day-of-week/time-of-day average per hour."""
    if not hourly_totals:
        return []

    def bucket(start: datetime) -> tuple[int, str]:
        local = start.astimezone(zone)
        period = (
            "night"
            if local.hour < 6
            else "morning"
            if local.hour < 10
            else "daytime"
            if local.hour < 17
            else "evening"
        )
        return local.weekday(), period

    grouped: dict[tuple[int, str], list[float]] = {}
    for start, value in hourly_totals:
        grouped.setdefault(bucket(start), []).append(value)
    averages = {
        key: sum(values) / len(values) for key, values in grouped.items()
    }
    return [(start, averages[bucket(start)]) for start, _ in hourly_totals]


def monthly_daily_profile(
    daily_totals: Sequence[tuple[datetime, float]], zone: tzinfo
) -> list[tuple[datetime, float]]:
    """Return the all-history daily average for each calendar month-of-year."""
    if not daily_totals:
        return []

    grouped: dict[int, list[float]] = {}
    for start, value in daily_totals:
        grouped.setdefault(start.astimezone(zone).month, []).append(value)
    averages = {
        month: sum(values) / len(values) for month, values in grouped.items()
    }
    return [
        (start, averages[start.astimezone(zone).month])
        for start, _ in daily_totals
    ]


def recorded_month_totals(
    daily_totals: Sequence[tuple[datetime, float]], zone: tzinfo
) -> list[tuple[datetime, float]]:
    """Aggregate collected daily values into recorded calendar-month totals."""
    grouped: dict[tuple[int, int], list[tuple[datetime, float]]] = {}
    for start, value in daily_totals:
        local = start.astimezone(zone)
        grouped.setdefault((local.year, local.month), []).append((start, value))
    return [
        (min(start for start, _ in values), sum(value for _, value in values))
        for _, values in sorted(grouped.items())
    ]


def recorded_month_records(
    daily_totals: Sequence[tuple[datetime, float]],
    zone: tzinfo,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return month totals and whether each past calendar month is complete."""
    current_month = today or datetime.now(zone).date()
    records: list[dict[str, Any]] = []
    for start, value in recorded_month_totals(daily_totals, zone):
        local = start.astimezone(zone)
        days = {
            item_start.astimezone(zone).day
            for item_start, _ in daily_totals
            if (
                item_start.astimezone(zone).year,
                item_start.astimezone(zone).month,
            )
            == (local.year, local.month)
        }
        days_in_month = calendar.monthrange(local.year, local.month)[1]
        is_past_month = (local.year, local.month) < (
            current_month.year,
            current_month.month,
        )
        records.append(
            {
                "month": local.strftime("%B %Y"),
                "start": start.isoformat(),
                "kwh": value,
                "complete": len(days) == days_in_month and is_past_month,
            }
        )
    return records


def completed_month_average(
    daily_totals: Sequence[tuple[datetime, float]],
    zone: tzinfo,
    *,
    today: date | None = None,
) -> float | None:
    """Return the average total across past, fully recorded calendar months."""
    totals = [
        record["kwh"]
        for record in recorded_month_records(daily_totals, zone, today=today)
        if record["complete"]
    ]
    return sum(totals) / len(totals) if totals else None


def completed_week_average(
    daily_totals: Sequence[tuple[datetime, float]],
    zone: tzinfo,
    *,
    today: date | None = None,
) -> float | None:
    """Return the average total across past, complete Monday-Sunday weeks."""
    current_day = today or datetime.now(zone).date()
    grouped: dict[date, list[tuple[date, float]]] = {}
    for start, value in daily_totals:
        local_day = start.astimezone(zone).date()
        week_start = local_day - timedelta(days=local_day.weekday())
        grouped.setdefault(week_start, []).append((local_day, value))

    totals = [
        sum(value for _, value in values)
        for week_start, values in grouped.items()
        if week_start + timedelta(days=7) <= current_day
        and len({local_day for local_day, _ in values}) == 7
    ]
    return sum(totals) / len(totals) if totals else None


def align_hourly_profile_to_intervals(
    interval_starts: Sequence[datetime],
    hourly_profile: Sequence[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Repeat each hourly profile value at matching interval timestamps."""
    by_hour = {start: value for start, value in hourly_profile}
    aligned: list[tuple[datetime, float]] = []
    for start in interval_starts:
        hour = start.replace(minute=0, second=0, microsecond=0)
        if hour in by_hour:
            aligned.append((start, by_hour[hour]))
    return aligned


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
