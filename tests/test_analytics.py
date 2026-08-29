"""Tests for pure Alexela analytics helpers."""

from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest


def _load_analytics_module():
    path = Path(__file__).parents[1] / "custom_components/alexela/analytics.py"
    spec = importlib.util.spec_from_file_location("alexela_analytics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANALYTICS = _load_analytics_module()
constant_daily_average = ANALYTICS.constant_daily_average
rolling_import_days = ANALYTICS.rolling_import_days
typical_hourly_profile = ANALYTICS.typical_hourly_profile


class ConstantDailyAverageTest(unittest.TestCase):
    def test_returns_horizontal_average_for_every_collected_day(self):
        starts = [
            datetime(2026, 8, day, tzinfo=timezone.utc) for day in (1, 2, 4)
        ]

        result = constant_daily_average(list(zip(starts, (3.0, 6.0, 12.0))))

        self.assertEqual(result, [(start, 7.0) for start in starts])

    def test_empty_history_has_no_average(self):
        self.assertEqual(constant_daily_average([]), [])


class TypicalHourlyProfileTest(unittest.TestCase):
    def test_splits_time_of_day_and_weekends(self):
        samples = [
            (datetime(2026, 8, 3, 7, tzinfo=timezone.utc), 0.1),
            (datetime(2026, 8, 4, 7, tzinfo=timezone.utc), 0.3),
            (datetime(2026, 8, 8, 7, tzinfo=timezone.utc), 0.8),
            (datetime(2026, 8, 3, 18, tzinfo=timezone.utc), 0.4),
        ]

        result = typical_hourly_profile(samples, timezone.utc)

        self.assertEqual(result, [
            (samples[0][0], 0.2),
            (samples[1][0], 0.2),
            (samples[2][0], 0.8),
            (samples[3][0], 0.4),
        ])

    def test_empty_history_has_no_average(self):
        self.assertEqual(typical_hourly_profile([], timezone.utc), [])


class RollingImportDaysTest(unittest.TestCase):
    def test_caught_up_scan_is_the_latest_ten_calendar_days(self):
        published = [date(2026, 8, day) for day in range(1, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            date(2026, 8, 26),
            reconcile_days=10,
        )

        self.assertEqual(result, [date(2026, 8, day) for day in range(17, 27)])

    def test_same_scan_includes_newly_published_days(self):
        published = [date(2026, 8, day) for day in range(1, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            date(2026, 8, 24),
            reconcile_days=10,
        )

        self.assertEqual(result, [date(2026, 8, day) for day in range(17, 27)])

    def test_initial_backfill_is_unlimited(self):
        published = [
            date(2026, 1, 1) + timedelta(days=offset) for offset in range(100)
        ]

        result = rolling_import_days(
            published,
            published[-1],
            None,
            reconcile_days=10,
        )

        self.assertEqual(result, published)

    def test_initial_backfill_starts_at_first_published_day(self):
        published = [date(2026, 8, day) for day in range(10, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            None,
            reconcile_days=10,
        )

        self.assertEqual(result[0], date(2026, 8, 10))
        self.assertEqual(result, published)


if __name__ == "__main__":
    unittest.main()
