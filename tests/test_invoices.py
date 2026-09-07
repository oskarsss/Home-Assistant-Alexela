"""Regression tests for invoice balance and due-date semantics."""
from datetime import date
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "alexela_invoices", Path(__file__).parents[1] / "custom_components/alexela/invoices.py"
)
invoices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(invoices)
TODAY = date(2026, 9, 7)


class InvoiceTests(unittest.TestCase):
    def test_supplied_example(self):
        result = invoices.summarize_invoices([{
            "number": "example", "status": "Unpaid", "unpaid": 21.42,
            "deadline": "2026-09-20T00:00:00", "sum": 21.42,
        }], TODAY)
        self.assertEqual(result["unpaid_count"], 1)
        self.assertEqual(result["unpaid_amount"], 21.42)
        self.assertEqual(result["next_due_date"], "2026-09-20")
        self.assertEqual(result["overdue_count"], 0)
        self.assertIn("due **2026-09-20**", result["message"])

    def test_partial_paid_credit_and_due_today(self):
        result = invoices.summarize_invoices([
            {"unpaid": "3.12", "sum": 100, "deadline": "2026-09-06"},
            {"unpaid": "0.10", "deadline": "2026-09-07"},
            {"unpaid": 0, "status": "Unpaid"},
            {"unpaid": -20},
        ], TODAY)
        self.assertEqual(result["unpaid_count"], 2)
        self.assertEqual(result["unpaid_amount"], 3.22)
        self.assertEqual(result["overdue_count"], 1)
        self.assertEqual(result["next_due_date"], "2026-09-06")

    def test_empty_is_paid_but_missing_or_invalid_balance_is_not(self):
        result = invoices.summarize_invoices([], TODAY)
        self.assertEqual(result["unpaid_count"], 0)
        self.assertIsNone(result["next_due_date"])
        for value in ({}, {"unpaid": None}, {"unpaid": "NaN"}, {"unpaid": "Infinity"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                invoices.summarize_invoices([value], TODAY)

    def test_unknown_deadline_does_not_hide_debt(self):
        result = invoices.summarize_invoices([
            {"unpaid": 2, "deadline": "invalid"},
            {"unpaid": 4, "deadline": "2026-09-10T00:00:00"},
        ], TODAY)
        self.assertEqual(result["unpaid_count"], 2)
        self.assertEqual(result["next_due_date"], "2026-09-10")
        self.assertIn("due **unknown**", result["message"])


class ReminderTests(unittest.TestCase):
    def summary(self, day, unpaid=21.42):
        return invoices.summarize_invoices([{
            "id": "bill1", "number": "example", "unpaid": unpaid,
            "deadline": "2026-09-20T00:00:00",
        }], day)

    def test_discovery_five_days_and_weekly_with_persisted_history(self):
        history = {}
        for day, expected in [(7, 1), (7, 0), (14, 0), (15, 1), (16, 0),
                              (20, 0), (21, 1), (22, 0), (27, 0), (28, 1)]:
            today = date(2026, 9, day)
            actions, history = invoices.plan_reminders(self.summary(today), history, today)
            self.assertEqual(len(actions), expected, f"September {day}")
            # Round-trip through JSON simulates storage and restart.
            import json
            history = json.loads(json.dumps(history))

    def test_paid_dismisses_once(self):
        _, history = invoices.plan_reminders(self.summary(TODAY), {}, TODAY)
        actions, history = invoices.plan_reminders(self.summary(TODAY, 0), history, TODAY)
        self.assertEqual(actions, [{"action": "dismiss", "id": "bill1"}])
        self.assertEqual(history, {})
        self.assertEqual(invoices.plan_reminders(self.summary(TODAY, 0), history, TODAY)[0], [])

    def test_missed_boundary_catches_up_once(self):
        _, history = invoices.plan_reminders(self.summary(TODAY), {}, TODAY)
        late = date(2026, 9, 18)
        actions, history = invoices.plan_reminders(self.summary(late), history, late)
        self.assertEqual(len(actions), 1)
        self.assertEqual(invoices.plan_reminders(self.summary(late), history, late)[0], [])

    def test_discovery_overdue_starts_weekly_clock(self):
        late = date(2026, 9, 22)
        actions, history = invoices.plan_reminders(self.summary(late), {}, late)
        self.assertEqual(len(actions), 1)
        next_day = date(2026, 9, 23)
        self.assertEqual(invoices.plan_reminders(self.summary(next_day), history, next_day)[0], [])

    def test_missing_deadline_only_notifies_discovery(self):
        summary = invoices.summarize_invoices([{"id": "x", "unpaid": 1}], TODAY)
        actions, history = invoices.plan_reminders(summary, {}, TODAY)
        self.assertEqual(len(actions), 1)
        self.assertIn("unknown", actions[0]["message"])
        self.assertEqual(invoices.plan_reminders(summary, history, date(2026, 10, 1))[0], [])
