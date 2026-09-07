"""Exercise the real invoice pagination method without Home Assistant."""
import ast
from pathlib import Path
from typing import Any
import unittest
from unittest.mock import AsyncMock

# Isolate the API class method from optional aiohttp/Home Assistant imports.
source = ast.parse((Path(__file__).parents[1] / 'custom_components/alexela/api.py').read_text())
api = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'AlexelaApi')
method = next(node for node in api.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'async_get_invoices')
namespace = {'Any': Any, 'AlexelaConnectionError': RuntimeError}
exec(compile(ast.Module(body=[method], type_ignores=[]), '<invoice-api>', 'exec'), namespace)


class InvoiceApiTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, pages):
        client = type('Client', (), {})()
        client._get_json = AsyncMock(side_effect=pages)
        result = await namespace['async_get_invoices'](client, '2000-01-01', '2026-09-07')
        return result, client._get_json.call_args_list

    async def test_all_pages_with_server_limit(self):
        result, calls = await self.fetch([
            {'total': 2, 'items': [{'id': 'a', 'unpaid': 1}]},
            {'total': 2, 'items': [{'id': 'b', 'unpaid': 2}]},
        ])
        self.assertEqual([item['id'] for item in result], ['a', 'b'])
        self.assertEqual(calls[1].kwargs['params']['pageNr'], '2')
        self.assertEqual(calls[0].kwargs['params']['limit'], '50')

    async def test_empty_is_valid(self):
        self.assertEqual((await self.fetch([{'total': 0, 'items': []}]))[0], [])

    async def test_incomplete_or_repeated_page_fails(self):
        first = {'total': 2, 'items': [{'id': 'a'}]}
        for second in ({'total': 2, 'items': []}, first):
            with self.assertRaises(RuntimeError):
                await self.fetch([first, second])

    async def test_malformed_payload_never_becomes_no_debt(self):
        for payload in (None, {}, {'total': 1, 'items': [{}]},
                        {'total': '0', 'items': []}, {'total': 0, 'items': [{'id': 'a'}]}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                await self.fetch([payload])
