"""HTTP client for the search API v2 endpoints."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import aiohttp

from auth import auth_headers_var

logger = logging.getLogger(__name__)

DEFAULT_CONTENT_LENGTH = 40_000
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
        elif api_key := os.environ.get('SPACE_FRONTIERS_API_KEY'):
            # `fastmcp run mcp_server.py` uses stdio and therefore does not pass
            # through the HTTP auth middleware. This fallback makes the
            # documented self-hosted command authenticate upstream correctly.
            headers['x-api-key'] = api_key
        return headers

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        index_names: list[str] | None = None,
        filter_types: list[str] | None = None,
        filter_issns: list[str] | None = None,
        filter_uri_prefixes: list[str] | None = None,
        filter_issued_after: int | None = None,
        filter_issued_before: int | None = None,
        referenced_by_uri: str | None = None,
    ) -> dict[str, Any]:
        """POST /v2/search — use the API's current hybrid/reranking defaults."""
        body: dict[str, Any] = {
            'query': query,
            'limit': limit,
        }
        if offset:
            body['offset'] = offset
        if index_names:
            body['index_names'] = index_names
        if filter_types:
            body['filter_types'] = filter_types
        if filter_issns:
            body['filter_issns'] = filter_issns
        if filter_uri_prefixes:
            body['filter_uri_prefixes'] = filter_uri_prefixes
        if filter_issued_after is not None:
            body['filter_issued_after'] = filter_issued_after
        if filter_issued_before is not None:
            body['filter_issued_before'] = filter_issued_before
        if referenced_by_uri:
            body['referenced_by_uri'] = referenced_by_uri

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
        return await self.search(
            '',
            limit=limit,
            index_names=['documents'],
            referenced_by_uri=uri,
        )

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
        encoded_uri = quote(uri, safe='')
        async with self._session.get(
            f'{self._base_url}/v2/search/documents/by-uri/{encoded_uri}',
            params=params,
            headers=self._get_headers(),
        ) as resp:
            if resp.status == 404:
                return None
            _check_response(resp)
            return await resp.json()
