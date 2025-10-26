"""HTTP client for the search API v2 endpoints."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from auth import auth_headers_var

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000


class InsufficientFundsError(Exception):
    """Raised when the user's balance is too low."""


class AuthenticationError(Exception):
    """Raised when authentication fails or API key is invalid."""


def _check_response(resp: aiohttp.ClientResponse) -> None:
    """Raise typed exceptions for billing/auth errors, or call raise_for_status."""
    if resp.status == 402:
        raise InsufficientFundsError()
    if resp.status == 401:
        raise AuthenticationError()
    resp.raise_for_status()


class SearchV2Client:
    """Thin async HTTP wrapper around the search API v2."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip('/')
        self._session = session

    def _get_headers(self) -> dict[str, str]:
        """Read auth headers from the current request's ContextVar."""
        headers: dict[str, str] = {'x-request-source': 'mcp'}
        auth = auth_headers_var.get()
        if auth:
            for key in ('x-user-id', 'x-organization-id'):
                if value := auth.get(key):
                    headers[key] = value
        return headers

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 30,
        index_names: list[str] | None = None,
        filter_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /v2/search — sparse search with snippet extraction."""
        body: dict[str, Any] = {
            'query': query,
            'mode': 'sparse',
            'limit': limit,
        }
        if index_names:
            body['index_names'] = index_names
        if filter_types:
            body['filter_types'] = filter_types

        async with self._session.post(
            f'{self._base_url}/v2/search/',
            json=body,
            headers=self._get_headers(),
        ) as resp:
            _check_response(resp)
            return await resp.json()

    # ------------------------------------------------------------------
    # Citing lookup
    # ------------------------------------------------------------------

    async def find_referenced_by(
        self,
        uri: str,
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        """POST /v2/search with referenced_by_uri — find docs that reference *uri*."""
        body: dict[str, Any] = {
            'query': '',
            'referenced_by_uri': uri,
            'limit': limit,
        }
        async with self._session.post(
            f'{self._base_url}/v2/search/',
            json=body,
            headers=self._get_headers(),
        ) as resp:
            _check_response(resp)
            return await resp.json()

    # ------------------------------------------------------------------
    # Fetch document
    # ------------------------------------------------------------------

    async def get_document_by_uri(
        self,
        uri: str,
        *,
        text_filter: str | None = None,
    ) -> dict[str, Any] | None:
        """GET /v2/search/documents/by-uri/{uri} — full document or filtered snippets."""
        params: dict[str, str] = {}
        if text_filter:
            params['text_filter'] = text_filter
        async with self._session.get(
            f'{self._base_url}/v2/search/documents/by-uri/{uri}',
            params=params,
            headers=self._get_headers(),
        ) as resp:
            if resp.status == 404:
                return None
            _check_response(resp)
            return await resp.json()
