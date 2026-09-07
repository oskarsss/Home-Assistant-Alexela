"""Verify startup discovery waits until forwarding automations can listen."""
import ast
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo
from typing import Any
import unittest

from test_invoices import invoices

source = ast.parse((Path(__file__).parents[1] / 'custom_components/alexela/coordinator.py').read_text())
coordinator = next(node for node in source.body if isinstance(node, ast.ClassDef))
method = next(node for node in coordinator.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_async_invoice_reminders')
notifications = SimpleNamespace(async_create=Mock(), async_dismiss=Mock())
namespace = {'Any': Any, 'date': date, 'datetime': datetime, 'ZoneInfo': ZoneInfo,
             'INVOICE_SUMMARY_KEY': invoices.INVOICE_SUMMARY_KEY,
             'PORTAL_TIME_ZONE': 'Europe/Riga', 'plan_reminders': invoices.plan_reminders,
             'EVENT_HOMEASSISTANT_STARTED': 'homeassistant_started',
             'persistent_notification': notifications}
exec(compile(ast.Module(body=[method], type_ignores=[]), '<invoice-startup>', 'exec'), namespace)


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_delivery_or_storage_before_started_and_no_restart_duplicate(self):
        notifications.async_create.reset_mock()
        summary = invoices.summarize_invoices([{
            'id': 'x', 'number': 'example', 'unpaid': 21.42,
            'deadline': '2099-09-20',
        }], date.today())
        client = type('Client', (), {'_async_invoice_reminders': namespace['_async_invoice_reminders']})()
        client.hass = SimpleNamespace(is_running=False, bus=SimpleNamespace(async_listen_once=Mock()))
        client.entry = SimpleNamespace(async_on_unload=Mock())
        client.api = SimpleNamespace(crm_id='example')
        client.data = {invoices.INVOICE_SUMMARY_KEY: summary}
        client._invoice_startup_pending = False
        client._invoice_history = None
        client._invoice_store = SimpleNamespace(async_load=AsyncMock(return_value={}), async_save=AsyncMock())
        await client._async_invoice_reminders(summary, date.today())
        await client._async_invoice_reminders(summary, date.today())
        client.hass.bus.async_listen_once.assert_called_once()
        notifications.async_create.assert_not_called()
        client._invoice_store.async_save.assert_not_called()
        callback = client.hass.bus.async_listen_once.call_args.args[1]
        client.hass.is_running = True
        await callback(None)
        notifications.async_create.assert_called_once()
        client._invoice_store.async_save.assert_awaited_once()
        saved = client._invoice_store.async_save.call_args.args[0]
        client._invoice_history = None
        client._invoice_store.async_load.return_value = saved
        await client._async_invoice_reminders(summary, date.today())
        notifications.async_create.assert_called_once()
