"""HTTP client for the search API v2 endpoints."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000


class SearchV2Client:
    """Thin async HTTP wrapper around the search API v2."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip('/')
        self._session = session

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 30,
        heap_factor: float = 0.7,
        pruning: float = 0.8,
        filter_types: list[str] | None = None,
        rerank: bool = False,
    ) -> dict[str, Any]:
        """POST /v2/search — sparse search with snippet extraction."""
        body: dict[str, Any] = {
            'query': query,
            'mode': 'sparse',
            'limit': limit,
            'heap_factor': heap_factor,
            'pruning': pruning,
        }
        if filter_types:
            body['filter_types'] = filter_types
        if rerank:
            body['rerank'] = True

        async with self._session.post(
            f'{self._base_url}/v2/search/',
            json=body,
        ) as resp:
            resp.raise_for_status()
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
        ) as resp:
            resp.raise_for_status()
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
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()
