"""Invoice summaries independent of Home Assistant and consumption totals."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

INVOICE_SUMMARY_KEY = "invoice_summary"
# Include old overdue bills, not just the current billing quarter.
INVOICE_PERIOD_START = "2000-01-01"


def summarize_invoices(items: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Use the remaining balance, including partial payments and credit notes.

    Invalid balances fail the refresh instead of falsely reporting no debt.
    Missing deadlines remain unknown, never inferred from the invoice date.
    """
    unpaid = []
    total = Decimal(0)
    for item in items:
        try:
            amount = Decimal(str(item["unpaid"]))
        except (KeyError, InvalidOperation, ValueError) as err:
            raise ValueError("Invalid invoice unpaid balance") from err
        if not amount.is_finite():
            raise ValueError("Invalid invoice unpaid balance")
        if amount <= 0:
            continue
        try:
            due = date.fromisoformat(str(item.get("deadline", ""))[:10])
        except ValueError:
            due = None
        total += amount
        unpaid.append({
            "id": str(item.get("id") or item.get("number") or "Unknown"),
            "number": str(item.get("number") or "Unknown"),
            "status": str(item.get("status") or "Unknown"),
            "unpaid": float(amount),
            "due_date": due.isoformat() if due else None,
            "overdue": due < today if due else False,
            "period_start": str(item.get("periodStart") or "")[:10],
            "period_end": str(item.get("periodEnd") or "")[:10],
        })
    unpaid.sort(key=lambda item: (item["due_date"] or "9999-12-31", item["number"]))
    deadlines = [item["due_date"] for item in unpaid if item["due_date"]]
    if unpaid:
        lines = (
            [f"{len(unpaid)} unpaid bills: **EUR {total:.2f}** outstanding."]
            if len(unpaid) > 1 else []
        )
        for item in unpaid:
            deadline = item["due_date"] or "unknown"
            label = "OVERDUE" if item["overdue"] else "due"
            lines.append(f"Bill {item['number']}: **EUR {item['unpaid']:.2f}**, {label} **{deadline}**.")
        message = "\n\n".join(lines)
    else:
        message = "No unpaid electricity bills."
    return {
        "unpaid_count": len(unpaid),
        "unpaid_amount": float(total),
        "next_due_date": min(deadlines) if deadlines else None,
        "overdue_count": sum(item["overdue"] for item in unpaid),
        "invoices": unpaid,
        "message": message,
        "period_start": INVOICE_PERIOD_START,
        "period_end": today.isoformat(),
    }


def plan_reminders(
    summary: dict[str, Any], history: dict[str, Any], today: date
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Plan per-invoice reminders, retaining scheduling state across restarts.

    If HA missed the five-day boundary, remind once on the next successful
    poll before the deadline. First overdue reminder is the following day,
    then at most once per seven days. A newly discovered overdue bill starts
    its weekly clock on discovery to avoid two notifications together.
    """
    actions = []
    updated = {}
    for bill in summary["invoices"]:
        key = bill["id"]
        old = history.get(key)
        record = dict(old or {})
        due = date.fromisoformat(bill["due_date"]) if bill["due_date"] else None
        days = (due - today).days if due else None
        reason = None
        if old is None:
            reason = "New unpaid bill"
        elif days is not None and 0 <= days <= 5 and record.get("reminded_due_date") != bill["due_date"]:
            reason = "Payment due soon"
        elif days is not None and days < 0:
            last = record.get("overdue_sent_date")
            if last is None or (today - date.fromisoformat(last)).days >= 7:
                reason = "Overdue bill reminder"
        if reason:
            if days is not None and 0 <= days <= 5:
                record["reminded_due_date"] = bill["due_date"]
            if days is not None and days < 0:
                record["overdue_sent_date"] = today.isoformat()
            deadline = bill["due_date"] or "unknown"
            label = "OVERDUE since" if bill["overdue"] else "Payment due"
            actions.append({"action": "create", "id": key, "title": f"Alexela: {reason}",
                            "message": f"Bill {bill['number']}: EUR {bill['unpaid']:.2f} unpaid.\n{label}: {deadline}."})
        updated[key] = record
    for key in history.keys() - updated.keys():
        actions.append({"action": "dismiss", "id": key})
    return actions, updated
