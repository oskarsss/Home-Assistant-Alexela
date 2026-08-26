"""Tests for pure Alexela analytics helpers."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest


def _load_analytics_module():
    path = Path(__file__).parents[1] / "custom_components/alexela/analytics.py"
    spec = importlib.util.spec_from_file_location("alexela_analytics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


constant_daily_average = _load_analytics_module().constant_daily_average


class ConstantDailyAverageTest(unittest.TestCase):
    def test_returns_horizontal_average_for_every_collected_day(self):
        starts = [
            datetime(2026, 8, day, tzinfo=timezone.utc) for day in (1, 2, 4)
        ]

        result = constant_daily_average(list(zip(starts, (3.0, 6.0, 12.0))))

        self.assertEqual(result, [(start, 7.0) for start in starts])

    def test_empty_history_has_no_average(self):
        self.assertEqual(constant_daily_average([]), [])


if __name__ == "__main__":
    unittest.main()
