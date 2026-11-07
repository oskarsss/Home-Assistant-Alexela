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
align_hourly_profile_to_intervals = ANALYTICS.align_hourly_profile_to_intervals
completed_month_average = ANALYTICS.completed_month_average
completed_week_average = ANALYTICS.completed_week_average
constant_daily_average = ANALYTICS.constant_daily_average
estimate_month_bill = ANALYTICS.estimate_month_bill
monthly_daily_profile = ANALYTICS.monthly_daily_profile
recorded_month_totals = ANALYTICS.recorded_month_totals
recorded_month_records = ANALYTICS.recorded_month_records
reconcile_window = ANALYTICS.reconcile_window
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
    def test_splits_time_of_day_and_day_of_week(self):
        samples = [
            (datetime(2026, 8, 3, 7, tzinfo=timezone.utc), 0.1),
            (datetime(2026, 8, 10, 7, tzinfo=timezone.utc), 0.3),
            (datetime(2026, 8, 4, 7, tzinfo=timezone.utc), 0.8),
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


class MonthlyProfilesTest(unittest.TestCase):
    def test_daily_profile_matches_calendar_month_across_years(self):
        samples = [
            (datetime(2025, 8, 1, tzinfo=timezone.utc), 2.0),
            (datetime(2026, 8, 1, tzinfo=timezone.utc), 4.0),
            (datetime(2026, 9, 1, tzinfo=timezone.utc), 9.0),
        ]
        self.assertEqual(
            monthly_daily_profile(samples, timezone.utc),
            [(samples[0][0], 3.0), (samples[1][0], 3.0), (samples[2][0], 9.0)],
        )

    def test_recorded_month_totals_group_calendar_months(self):
        samples = [
            (datetime(2026, 8, 1, tzinfo=timezone.utc), 2.0),
            (datetime(2026, 8, 2, tzinfo=timezone.utc), 4.0),
            (datetime(2026, 9, 1, tzinfo=timezone.utc), 9.0),
        ]
        self.assertEqual(
            recorded_month_totals(samples, timezone.utc),
            [(samples[0][0], 6.0), (samples[2][0], 9.0)],
        )

    def test_recorded_month_records_mark_only_full_calendar_months_complete(self):
        january = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 1.0)
            for day in range(1, 32)
        ]
        partial_february = [
            (datetime(2026, 2, day, tzinfo=timezone.utc), 2.0)
            for day in range(1, 11)
        ]

        records = recorded_month_records(
            january + partial_february,
            timezone.utc,
            today=date(2026, 3, 1),
        )

        self.assertEqual(records[0]["month"], "January 2026")
        self.assertTrue(records[0]["complete"])
        self.assertEqual(records[1]["month"], "February 2026")
        self.assertFalse(records[1]["complete"])

    def test_monthly_average_excludes_partial_months(self):
        january = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 1.0)
            for day in range(1, 32)
        ]
        partial_february = [
            (datetime(2026, 2, day, tzinfo=timezone.utc), 10.0)
            for day in range(1, 4)
        ]

        self.assertEqual(
            completed_month_average(
                january + partial_february,
                timezone.utc,
                today=date(2026, 3, 1),
            ),
            31.0,
        )

    def test_monthly_average_requires_a_completed_month(self):
        partial = [(datetime(2026, 2, 1, tzinfo=timezone.utc), 10.0)]

        self.assertIsNone(
            completed_month_average(
                partial, timezone.utc, today=date(2026, 3, 1)
            )
        )

    def test_monthly_average_always_excludes_current_month(self):
        full_current_month = [
            (datetime(2026, 2, day, tzinfo=timezone.utc), 1.0)
            for day in range(1, 29)
        ]

        self.assertIsNone(
            completed_month_average(
                full_current_month,
                timezone.utc,
                today=date(2026, 2, 28),
            )
        )


class CompletedWeekAverageTest(unittest.TestCase):
    def test_uses_only_full_monday_to_sunday_weeks(self):
        partial_leading_week = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 100.0)
            for day in range(1, 5)
        ]
        first_full_week = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 1.0)
            for day in range(5, 12)
        ]
        second_full_week = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 3.0)
            for day in range(12, 19)
        ]
        partial_trailing_week = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 100.0)
            for day in range(19, 22)
        ]

        self.assertEqual(
            completed_week_average(
                partial_leading_week
                + first_full_week
                + second_full_week
                + partial_trailing_week,
                timezone.utc,
                today=date(2026, 1, 22),
            ),
            14.0,
        )

    def test_requires_a_full_week(self):
        partial = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 1.0)
            for day in range(5, 11)
        ]

        self.assertIsNone(
            completed_week_average(
                partial, timezone.utc, today=date(2026, 1, 12)
            )
        )

    def test_excludes_the_current_week(self):
        current_week = [
            (datetime(2026, 1, day, tzinfo=timezone.utc), 1.0)
            for day in range(5, 12)
        ]

        self.assertIsNone(
            completed_week_average(
                current_week, timezone.utc, today=date(2026, 1, 11)
            )
        )


class AlignHourlyProfileTest(unittest.TestCase):
    def test_repeats_hour_value_at_every_quarter_hour(self):
        hour = datetime(2026, 8, 28, 3, tzinfo=timezone.utc)
        intervals = [hour + timedelta(minutes=minutes) for minutes in (0, 15, 30, 45)]

        self.assertEqual(
            align_hourly_profile_to_intervals(intervals, [(hour, 0.2)]),
            [(start, 0.2) for start in intervals],
        )


class ReconcileWindowTest(unittest.TestCase):
    NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

    def window(self, last):
        return reconcile_window(
            last, self.NOW, full_days=30, quick_days=2,
            full_interval=timedelta(hours=6),
        )

    def test_first_update_after_start_reconciles_fully(self):
        self.assertEqual(self.window(None), 30)

    def test_polls_between_full_runs_read_only_the_latest_days(self):
        self.assertEqual(self.window(self.NOW - timedelta(hours=5)), 2)

    def test_full_run_repeats_once_the_interval_has_passed(self):
        self.assertEqual(self.window(self.NOW - timedelta(hours=6)), 30)


class RollingImportDaysTest(unittest.TestCase):
    def test_caught_up_scan_is_the_latest_thirty_calendar_days(self):
        published = [date(2026, 8, day) for day in range(1, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            date(2026, 8, 26),
            reconcile_days=30,
        )

        self.assertEqual(result, published)

    def test_same_scan_includes_newly_published_days(self):
        published = [date(2026, 8, day) for day in range(1, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            date(2026, 8, 24),
            reconcile_days=30,
        )

        self.assertEqual(result, published)

    def test_thirty_day_scan_catches_a_gap_older_than_ten_days(self):
        published = [date(2026, 9, day) for day in range(1, 19)]

        result = rolling_import_days(
            published,
            date(2026, 9, 18),
            date(2026, 9, 18),
            reconcile_days=30,
        )

        self.assertIn(date(2026, 9, 4), result)
        self.assertEqual(result, published)

    def test_initial_backfill_is_unlimited(self):
        published = [
            date(2026, 1, 1) + timedelta(days=offset) for offset in range(100)
        ]

        result = rolling_import_days(
            published,
            published[-1],
            None,
            reconcile_days=30,
        )

        self.assertEqual(result, published)

    def test_initial_backfill_starts_at_first_published_day(self):
        published = [date(2026, 8, day) for day in range(10, 27)]

        result = rolling_import_days(
            published,
            date(2026, 8, 26),
            None,
            reconcile_days=30,
        )

        self.assertEqual(result[0], date(2026, 8, 10))
        self.assertEqual(result, published)


class EstimateMonthBillTest(unittest.TestCase):
    TARIFF = {
        "monthly_fee": 1.24,
        "capacity_fee": 0.34 * 20,
        "network_eur_per_kwh": 0.03962 + 0.00201,
        "vat_multiplier": 1.21,
    }

    def test_full_month_matches_october_2026_invoice(self):
        kwh = [120.62 / 31] * 31
        cost = [value * 0.12499 for value in kwh]

        result = estimate_month_bill(date(2026, 10, 1), kwh, cost, **self.TARIFF)

        self.assertAlmostEqual(result["projected_bill"], 30.88, places=2)
        self.assertAlmostEqual(result["projected_kwh"], 120.62)
        self.assertEqual(result["recorded_days"], 31)

    def test_partial_month_scales_usage_but_not_fixed_fees(self):
        result = estimate_month_bill(
            date(2026, 11, 1), [4.0] * 6, [0.5] * 6, **self.TARIFF
        )

        self.assertAlmostEqual(result["projected_kwh"], 120.0)
        self.assertAlmostEqual(result["projected_energy_cost"], 15.0)
        self.assertAlmostEqual(
            result["projected_bill"],
            15.0 + (1.24 + 6.8 + 120.0 * 0.04163) * 1.21,
        )
        self.assertLess(result["recorded_bill"], result["projected_bill"])

    def test_range_brackets_estimate_and_uses_recent_average(self):
        recent = [3.0, 5.0] * 15

        result = estimate_month_bill(
            date(2026, 11, 1), [3.4] * 5, [0.425] * 5,
            recent_daily_energy=recent, **self.TARIFF,
        )

        self.assertLess(result["projected_bill_low"], result["projected_bill"])
        self.assertGreater(result["projected_bill_high"], result["projected_bill"])
        # High end: 25 days at the recent 4.0 kWh/day plus 1.0 kWh x sqrt(25).
        kwh = 17.0 + 25 * 4.0 + 5.0
        self.assertAlmostEqual(
            result["projected_bill_high"],
            0.125 * kwh + (1.24 + 6.8 + kwh * 0.04163) * 1.21,
        )

    def test_complete_month_has_no_range(self):
        result = estimate_month_bill(
            date(2026, 10, 1), [4.0] * 31, [0.5] * 31,
            recent_daily_energy=[1.0, 9.0], **self.TARIFF,
        )

        self.assertAlmostEqual(result["projected_bill_low"], result["projected_bill"])
        self.assertAlmostEqual(result["projected_bill_high"], result["projected_bill"])

    def test_month_without_recorded_kwh_has_no_range(self):
        result = estimate_month_bill(
            date(2026, 11, 1), [0.0], [0.0],
            recent_daily_energy=[4.0] * 30, **self.TARIFF,
        )

        self.assertNotIn("projected_bill_low", result)
        self.assertNotIn("projected_bill_high", result)

    def test_no_recorded_days_has_no_estimate(self):
        self.assertIsNone(
            estimate_month_bill(date(2026, 11, 1), [], [], **self.TARIFF)
        )


if __name__ == "__main__":
    unittest.main()
