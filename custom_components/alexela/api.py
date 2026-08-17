"""Small async client for the private Alexela customer portal API."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_HOST, PORTAL_ORIGIN, REQUEST_TIMEOUT


class AlexelaError(Exception):
    """Base Alexela API error."""


class AlexelaAuthError(AlexelaError):
    """Authentication failed."""


class AlexelaConnectionError(AlexelaError):
    """Communication with Alexela failed."""


def normalize_token(token: str) -> str:
    """Return a raw JWT regardless of whether the user pasted 'Bearer '."""
    token = token.strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


class AlexelaApi:
    """Client for the Alexela portal API used by my.alexela.lv."""

    def __init__(self, session: ClientSession, crm_id: str, token: str) -> None:
        self._session = session
        self.crm_id = str(crm_id).strip()
        self.token = normalize_token(token)

    @property
    def _base_url(self) -> str:
        # The Latvian portal currently repeats CRM ID twice in the URL.
        return f"{API_HOST}/api/{self.crm_id}/{self.crm_id}"

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/plain, */*",
        }

    async def _raise_for_status(self, response: ClientResponse) -> None:
        if response.status in (401, 403):
            raise AlexelaAuthError(f"Alexela authentication failed (HTTP {response.status})")
        if response.status < 200 or response.status >= 300:
            text = await response.text()
            raise AlexelaConnectionError(
                f"Alexela returned HTTP {response.status}: {text[:200]}"
            )

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = self._auth_headers
        if headers:
            request_headers.update(headers)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers=request_headers,
                ) as response:
                    await self._raise_for_status(response)
                    return await response.json(content_type=None)
        except AlexelaError:
            raise
        except (TimeoutError, ClientError, ValueError) as err:
            raise AlexelaConnectionError(str(err)) from err

    async def async_get_contracts(self) -> list[dict[str, Any]]:
        """Return contracts; used to validate CRM ID and JWT."""
        data = await self._get_json(
            "/contract/contracts",
            params={
                "isCached": "true",
                "includePreContracts": "true",
            },
        )
        if not isinstance(data, list):
            raise AlexelaConnectionError("Unexpected contracts response")
        return data

    async def async_refresh_jwt(self) -> bool:
        """Attempt JWT rotation.

        Alexela returns HTTP 200 even when no rotation is needed. When a new
        JWT is issued it is returned in the response header named 'Bearer'.
        """
        headers = {
            "Origin": PORTAL_ORIGIN,
            "Referer": f"{PORTAL_ORIGIN}/",
            "Accept-Language": "lv",
        }

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    f"{self._base_url}/login/refreshJwt",
                    headers={**self._auth_headers, **headers},
                ) as response:
                    await self._raise_for_status(response)

                    new_token = response.headers.get("Bearer")
                    if not new_token:
                        # A successful no-op refresh currently has a JSON body
                        # such as {"result":{},"value":null}. We don't need it.
                        await response.read()
                        return False

                    new_token = normalize_token(new_token)
                    if not new_token:
                        raise AlexelaConnectionError(
                            "Alexela returned an empty Bearer header"
                        )

                    changed = new_token != self.token
                    self.token = new_token
                    await response.read()
                    return changed
        except AlexelaError:
            raise
        except (TimeoutError, ClientError) as err:
            raise AlexelaConnectionError(str(err)) from err

    async def async_get_consumption(self, year: int) -> dict[str, Any]:
        """Return yearly electricity/gas consumption data."""
        data = await self._get_json(
            "/consumption",
            params={
                "periodStart": f"{year}-01-01 00:00:00",
                "periodType": "year",
                "crmId": self.crm_id,
            },
        )
        if not isinstance(data, dict):
            raise AlexelaConnectionError("Unexpected consumption response")
        return data
