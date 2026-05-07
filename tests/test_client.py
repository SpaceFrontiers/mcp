"""Tests for SearchV2Client — verify filter parameters are passed correctly."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from client import SearchV2Client


class FakeResponse:
    """Minimal aiohttp response stub for testing."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None):
        self.status = status
        self._body = body or {'hits': []}

    async def json(self):
        return self._body

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f'HTTP {self.status}')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.post = MagicMock(return_value=FakeResponse())
    return session


@pytest.fixture
def client(mock_session):
    return SearchV2Client('http://search-api', mock_session)


def _posted_body(mock_session) -> dict[str, Any]:
    """Extract the JSON body from the most recent session.post() call."""
    call_kwargs = mock_session.post.call_args
    return call_kwargs.kwargs.get('json') or call_kwargs[1].get('json')


# ---------------------------------------------------------------------------
# Basic search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_search(client, mock_session):
    await client.search('quantum computing')
    body = _posted_body(mock_session)
    assert body['query'] == 'quantum computing'
    assert body['mode'] == 'sparse'
    assert body['limit'] == 30
    assert 'filter_issns' not in body
    assert 'filter_uri_prefixes' not in body
    assert 'filter_issued_after' not in body
    assert 'filter_issued_before' not in body
    assert 'filter_types' not in body


@pytest.mark.asyncio
async def test_empty_query_allowed(client, mock_session):
    await client.search('')
    body = _posted_body(mock_session)
    assert body['query'] == ''


# ---------------------------------------------------------------------------
# Individual filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_issns(client, mock_session):
    await client.search('', filter_issns=['0028-0836', '0036-8075'])
    body = _posted_body(mock_session)
    assert body['filter_issns'] == ['0028-0836', '0036-8075']


@pytest.mark.asyncio
async def test_filter_uri_prefixes(client, mock_session):
    await client.search('', filter_uri_prefixes=['https://reddit.com/r/machinelearning/'])
    body = _posted_body(mock_session)
    assert body['filter_uri_prefixes'] == ['https://reddit.com/r/machinelearning/']


@pytest.mark.asyncio
async def test_filter_issued_after(client, mock_session):
    ts = 1712000000
    await client.search('', filter_issued_after=ts)
    body = _posted_body(mock_session)
    assert body['filter_issued_after'] == ts


@pytest.mark.asyncio
async def test_filter_issued_before(client, mock_session):
    ts = 1712999999
    await client.search('', filter_issued_before=ts)
    body = _posted_body(mock_session)
    assert body['filter_issued_before'] == ts


@pytest.mark.asyncio
async def test_filter_types(client, mock_session):
    await client.search('', filter_types=['journal-article', 'posted-content'])
    body = _posted_body(mock_session)
    assert body['filter_types'] == ['journal-article', 'posted-content']


@pytest.mark.asyncio
async def test_index_names(client, mock_session):
    await client.search('test', index_names=['social'])
    body = _posted_body(mock_session)
    assert body['index_names'] == ['social']


# ---------------------------------------------------------------------------
# None/empty filters are omitted from the request body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_filters_omitted(client, mock_session):
    await client.search(
        'test',
        filter_issns=None,
        filter_uri_prefixes=None,
        filter_issued_after=None,
        filter_issued_before=None,
        filter_types=None,
    )
    body = _posted_body(mock_session)
    assert 'filter_issns' not in body
    assert 'filter_uri_prefixes' not in body
    assert 'filter_issued_after' not in body
    assert 'filter_issued_before' not in body
    assert 'filter_types' not in body


@pytest.mark.asyncio
async def test_empty_list_filters_omitted(client, mock_session):
    """Empty lists are falsy and should be omitted."""
    await client.search('test', filter_issns=[], filter_uri_prefixes=[], filter_types=[])
    body = _posted_body(mock_session)
    assert 'filter_issns' not in body
    assert 'filter_uri_prefixes' not in body
    assert 'filter_types' not in body


# ---------------------------------------------------------------------------
# Combined filters (real use cases)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_recent_journal_papers(client, mock_session):
    """Use case: recent papers from Nature (no query, ISSN + date filter)."""
    await client.search(
        '',
        filter_issns=['0028-0836'],
        filter_issued_after=1711929600,
    )
    body = _posted_body(mock_session)
    assert body['query'] == ''
    assert body['filter_issns'] == ['0028-0836']
    assert body['filter_issued_after'] == 1711929600


@pytest.mark.asyncio
async def test_browse_subreddit(client, mock_session):
    """Use case: recent posts from r/science."""
    await client.search(
        '',
        index_names=['social'],
        filter_uri_prefixes=['https://reddit.com/r/science/'],
        filter_issued_after=1711929600,
    )
    body = _posted_body(mock_session)
    assert body['query'] == ''
    assert body['index_names'] == ['social']
    assert body['filter_uri_prefixes'] == ['https://reddit.com/r/science/']
    assert body['filter_issued_after'] == 1711929600


@pytest.mark.asyncio
async def test_browse_telegram_channel(client, mock_session):
    """Use case: recent messages from a Telegram channel."""
    await client.search(
        '',
        index_names=['social'],
        filter_uri_prefixes=['@channel_name'],
        filter_issued_after=1711929600,
    )
    body = _posted_body(mock_session)
    assert body['filter_uri_prefixes'] == ['@channel_name']


@pytest.mark.asyncio
async def test_search_within_journal(client, mock_session):
    """Use case: search for 'CRISPR' within Nature."""
    await client.search('CRISPR', filter_issns=['0028-0836'])
    body = _posted_body(mock_session)
    assert body['query'] == 'CRISPR'
    assert body['filter_issns'] == ['0028-0836']


@pytest.mark.asyncio
async def test_search_within_subreddit(client, mock_session):
    """Use case: search for 'transformer' within r/machinelearning."""
    await client.search(
        'transformer',
        index_names=['social'],
        filter_uri_prefixes=['https://reddit.com/r/machinelearning/'],
    )
    body = _posted_body(mock_session)
    assert body['query'] == 'transformer'
    assert body['filter_uri_prefixes'] == ['https://reddit.com/r/machinelearning/']


@pytest.mark.asyncio
async def test_search_within_telegram(client, mock_session):
    """Use case: search for 'launch' within a Telegram channel."""
    await client.search(
        'launch',
        index_names=['social'],
        filter_uri_prefixes=['@tech_news'],
    )
    body = _posted_body(mock_session)
    assert body['query'] == 'launch'
    assert body['filter_uri_prefixes'] == ['@tech_news']


# ---------------------------------------------------------------------------
# filter_issued_after=0 should be included (it's a valid timestamp)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_timestamp_included(client, mock_session):
    """Timestamp 0 (epoch start) is a valid value and must not be treated as falsy."""
    await client.search('', filter_issued_after=0)
    body = _posted_body(mock_session)
    assert body['filter_issued_after'] == 0
