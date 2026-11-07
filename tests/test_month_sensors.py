"""This-month sensors must not fall back a month when Alexela drops its row."""
import ast
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path
from typing import Any
import unittest
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).parents[1] / "custom_components/alexela/sensor.py"
FUNCTIONS = {
    "_statistics_month", "_unlisted_month", "_period_block",
    "_listed_period_block", "_with_unlisted_month", "_ytd_energy",
    "_month_energy", "_month_cost", "_ytd_cost", "_period_start",
}


def total_block(data):
    return data.get("electricityConsumption", [None])[0]


def sum_rows(block, key):
    values = [row[key] for row in (block or {}).get("data", []) if row.get(key) is not None]
    return sum(values) if values else None


tree = ast.parse(SOURCE.read_text())
functions = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
assert {node.name for node in functions} == FUNCTIONS
namespace: dict[str, Any] = {
    "Any": Any, "NORD_POOL_SUMMARY_KEY": "nord_pool",
    "total_block": total_block, "sum_rows": sum_rows,
    "reference_datetime": lambda: datetime(2026, 11, 6),
    "datetime": datetime, "ZoneInfo": ZoneInfo, "PORTAL_TIME_ZONE": "Europe/Riga",
    "dt_util": SimpleNamespace(parse_datetime=datetime.fromisoformat),
}
sensor_class = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "AlexelaSensor")
last_reset = next(node for node in sensor_class.body
                  if isinstance(node, ast.FunctionDef) and node.name == "last_reset")
last_reset.decorator_list = []
functions.append(last_reset)
exec(compile(ast.Module(body=functions, type_ignores=[]), "<sensor>", "exec"), namespace)


def reset_for(key, data):
    sensor = SimpleNamespace(
        entity_description=SimpleNamespace(key=key),
        coordinator=SimpleNamespace(data=data),
    )
    return namespace["last_reset"](sensor)

OCTOBER = {"timestamp": "2026-10-01T00:00:00", "amount": 120.62, "priceWithVat": 15.077}
SUMMARY = {
    "latest_month_start": "2026-11-01T00:00:00",
    "latest_month_kwh": 17.187,
    "latest_month_cost": 2.148,
}


def payload(rows, summary=SUMMARY):
    return {
        "electricityConsumption": [{"totalAmount": 332.287, "data": rows}],
        "nord_pool": summary,
    }


class MonthSensorTests(unittest.TestCase):
    def test_statistics_month_replaces_month_missing_from_yearly_view(self):
        data = payload([OCTOBER])

        self.assertAlmostEqual(namespace["_month_energy"](data), 17.187)
        self.assertAlmostEqual(namespace["_month_cost"](data), 2.148)
        self.assertAlmostEqual(namespace["_ytd_energy"](data), 332.287 + 17.187)

    def test_listed_month_wins_when_yearly_view_has_it(self):
        november = {"timestamp": "2026-11-01T00:00:00", "amount": 18.0, "priceWithVat": 2.2}
        data = payload([OCTOBER, november])

        self.assertEqual(namespace["_month_energy"](data), 18.0)
        self.assertEqual(namespace["_ytd_energy"](data), 332.287)

    def test_older_statistics_do_not_override_yearly_view(self):
        data = payload([OCTOBER], {**SUMMARY, "latest_month_start": "2026-09-01T00:00:00"})

        self.assertEqual(namespace["_month_energy"](data), 120.62)

    def test_statistics_month_in_new_year_restarts_year_to_date(self):
        december = {"timestamp": "2026-12-01T00:00:00", "amount": 150.0, "priceWithVat": 19.0}
        january = {"latest_month_start": "2027-01-01T00:00:00",
                   "latest_month_kwh": 20.0, "latest_month_cost": 2.5}
        data = payload([december], january)
        data["electricityConsumption"][0]["totalPriceWithVat"] = 180.0
        reference = namespace["reference_datetime"]
        namespace["reference_datetime"] = lambda: datetime(2027, 1, 6)
        try:
            self.assertEqual(namespace["_month_energy"](data), 20.0)
            self.assertEqual(namespace["_ytd_energy"](data), 20.0)
            self.assertEqual(namespace["_ytd_cost"](data), 2.5)
        finally:
            namespace["reference_datetime"] = reference

    def test_cost_totals_reset_with_their_period_in_latvian_time(self):
        data = payload([OCTOBER])
        riga = ZoneInfo("Europe/Riga")

        self.assertEqual(reset_for("electricity_cost_month", data),
                         datetime(2026, 11, 1, tzinfo=riga))
        self.assertEqual(reset_for("electricity_cost_ytd", data),
                         datetime(2026, 1, 1, tzinfo=riga))
        self.assertIsNone(reset_for("electricity_month", data))

    def test_without_statistics_yearly_view_is_used(self):
        data = payload([OCTOBER], None)

        self.assertEqual(namespace["_month_energy"](data), 120.62)
        self.assertEqual(namespace["_ytd_energy"](data), 332.287)


if __name__ == "__main__":
    unittest.main()
