"""Tests for the bounded document resource mirror."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client, FastMCP

from client import DEFAULT_CONTENT_LENGTH
from resources import _decode_uri, _encode_uri, setup_resources


def test_resource_uri_token_round_trip():
    uri = 'https://doi.org/10.1234/example'
    assert _decode_uri(_encode_uri(uri)) == uri


@pytest.mark.asyncio
async def test_document_resource_is_bounded_and_does_not_search_backlinks():
    search_client = MagicMock()
    search_client.get_document_by_uri = AsyncMock(
        return_value={
            'uris': ['https://doi.org/10.1234/example'],
            'document': {
                'title': 'Example',
                'content': 'x' * (DEFAULT_CONTENT_LENGTH + 100),
            },
        }
    )
    search_client.find_referenced_by = AsyncMock()

    @asynccontextmanager
    async def lifespan(_):
        yield SimpleNamespace(search_client=search_client)

    mcp = FastMCP('test', lifespan=lifespan)
    setup_resources(mcp)
    token = _encode_uri('https://doi.org/10.1234/example')
    async with Client(mcp) as mcp_client:
        contents = await mcp_client.read_resource(f'spacefrontiers://document/{token}')
    result = json.loads(contents[0].text)

    assert len(result['content']) == DEFAULT_CONTENT_LENGTH
    assert result['content_truncated'] is True
    assert result['referenced_by'] == []
    search_client.get_document_by_uri.assert_awaited_once_with('doi://10.1234/example')
    search_client.find_referenced_by.assert_not_awaited()
