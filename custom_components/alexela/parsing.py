"""Helpers for reading Alexela consumption payloads."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DATA_LAG


def reference_datetime() -> datetime:
    """Return the most recent local time Alexela is expected to have data for.

    The portal publishes consumption with about a day of delay, so anchoring on
    today would ask for a period that does not exist yet on the first day of a
    month or year.
    """
    return dt_util.now() - DATA_LAG


def unwrap_payload(payload: Any) -> dict[str, Any]:
    """Return the object that carries the consumption blocks.

    Some Alexela endpoints answer with an envelope such as
    {"result": {...}, "value": null}, so the consumption blocks are not always
    at the top level of the response.
    """
    if not isinstance(payload, dict):
        return {}
    if "electricityConsumption" in payload:
        return payload
    for key in ("result", "value", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict) and "electricityConsumption" in inner:
            return inner
    return payload


def total_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return Alexela's aggregate electricity block.

    Accounts with a single consumption location do not always get an aggregate
    row flagged with isTotal, so fall back to the only block that is present.
    """
    blocks = [
        item
        for item in data.get("electricityConsumption", [])
        if isinstance(item, dict)
    ]
    for item in blocks:
        if item.get("isTotal") is True:
            return item
    return blocks[0] if len(blocks) == 1 else None


def block_rows(block: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the periods of a block that actually carry a reading."""
    if not block:
        return []
    return [
        row
        for row in block.get("data", [])
        if isinstance(row, dict) and row.get("amount") is not None
    ]


def sum_rows(block: dict[str, Any] | None, key: str) -> float | None:
    """Sum one field across every period of a block."""
    values = [
        float(row[key]) for row in block_rows(block) if row.get(key) is not None
    ]
    return sum(values) if values else None


def has_consumption_data(data: dict[str, Any] | None) -> bool:
    """Return True when the payload carries at least one usable period."""
    if not data:
        return False
    return any(
        row.get("amount") is not None
        for block in data.get("electricityConsumption", [])
        if isinstance(block, dict)
        for row in block.get("data", [])
        if isinstance(row, dict)
    )


def cost_scale(block: dict[str, Any] | None) -> float:
    """Return the factor that converts a row's priceWithVat into euro.

    The yearly view reports each period in euro, but the daily view reports
    cents while still giving totalPriceWithVat in euro. Compare the periods
    against that total instead of trusting the priceFormat string.
    """
    if not block:
        return 1.0

    total = block.get("totalPriceWithVat")
    rows = sum(
        float(row["priceWithVat"])
        for row in block.get("data", [])
        if isinstance(row, dict) and row.get("priceWithVat") is not None
    )
    if total and rows and rows / float(total) > 10:
        return 0.01

    return 0.01 if "€" not in str(block.get("priceFormat", "€")) else 1.0


def parse_timestamp(value: Any, zone: tzinfo) -> datetime | None:
    """Parse an Alexela timestamp, which is local time without an offset."""
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed
