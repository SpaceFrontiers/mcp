"""Tests for the four spacefrontiers_* MCP tools.

Verifies tool registration, parameter pass-through to SearchV2Client, the
Pydantic output schemas, and billing/auth error envelopes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from client import AuthenticationError, InsufficientFundsError
from tools import (
    DocumentPassages,
    FullDocument,
    SearchResults,
    setup_tools,
)

EMPTY_RESULTS: dict[str, Any] = {'hits': []}


def _build_mcp_with_mocks(
    *,
    search_return: dict[str, Any] | None = None,
    fetch_return: dict[str, Any] | None = None,
    referenced_by_return: dict[str, Any] | None = None,
    search_side_effect: Exception | None = None,
    fetch_side_effect: Exception | None = None,
):
    """Wire up a FastMCP instance with a mocked SearchV2Client so we can drive each tool."""
    mcp = FastMCP('test')
    setup_tools(mcp)

    client = MagicMock()
    client.search = AsyncMock(
        return_value=search_return if search_return is not None else EMPTY_RESULTS,
        side_effect=search_side_effect,
    )
    client.find_referenced_by = AsyncMock(
        return_value=referenced_by_return if referenced_by_return is not None else EMPTY_RESULTS,
    )
    client.get_document_by_uri = AsyncMock(
        return_value=fetch_return,
        side_effect=fetch_side_effect,
    )

    ctx = MagicMock()
    ctx.request_context.lifespan_context.search_client = client
    return mcp, client, ctx


def _tool_fn(mcp: FastMCP, name: str):
    tool = mcp._tool_manager._tools.get(name)
    assert tool is not None, f'tool {name} not registered (have {list(mcp._tool_manager._tools.keys())})'
    return tool.fn


# ---------------------------------------------------------------------------
# Registration: every tool is namespaced and read-only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'tool_name',
    [
        'spacefrontiers_search_documents',
        'spacefrontiers_search_social',
        'spacefrontiers_fetch_document',
        'spacefrontiers_search_in_document',
    ],
)
def test_tools_registered_with_namespace(tool_name):
    mcp = FastMCP('test')
    setup_tools(mcp)
    assert tool_name in mcp._tool_manager._tools


def test_tools_have_read_only_annotations():
    mcp = FastMCP('test')
    setup_tools(mcp)
    for name in (
        'spacefrontiers_search_documents',
        'spacefrontiers_search_social',
        'spacefrontiers_fetch_document',
        'spacefrontiers_search_in_document',
    ):
        annotations = mcp._tool_manager._tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.idempotentHint is True
        assert annotations.destructiveHint is False


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_documents_pins_index_to_documents():
    mcp, client, ctx = _build_mcp_with_mocks()
    fn = _tool_fn(mcp, 'spacefrontiers_search_documents')
    await fn(ctx=ctx, query='quantum computing')
    kwargs = client.search.call_args.kwargs
    assert kwargs['index_names'] == ['documents']
    assert client.search.call_args.args == ('quantum computing',)


@pytest.mark.asyncio
async def test_search_documents_passes_filters():
    mcp, client, ctx = _build_mcp_with_mocks()
    fn = _tool_fn(mcp, 'spacefrontiers_search_documents')
    await fn(
        ctx=ctx,
        query='crispr',
        filter_issns=['0028-0836'],
        filter_types=['journal-article'],
        filter_issued_after=1711929600,
    )
    kwargs = client.search.call_args.kwargs
    assert kwargs['filter_issns'] == ['0028-0836']
    assert kwargs['filter_types'] == ['journal-article']
    assert kwargs['filter_issued_after'] == 1711929600


@pytest.mark.asyncio
async def test_search_documents_returns_typed_results():
    raw = {
        'hits': [
            {
                'score': 0.95,
                'document': {
                    'title': 'Test Paper',
                    'uris': ['https://doi.org/10.1234/test', 'doi://10.1234/test'],
                    'abstract': 'An abstract.',
                    'content_length': 80_000,
                    'authors': [{'name': 'Alice Smith'}, {'family': 'Jones', 'given': 'Bob'}],
                },
                'snippets': [{'text': 'matching passage', 'field': 'content', 'score': 0.9}],
            }
        ],
        'total_hits': 1,
    }
    mcp, _, ctx = _build_mcp_with_mocks(search_return=raw)
    fn = _tool_fn(mcp, 'spacefrontiers_search_documents')
    result = await fn(ctx=ctx, query='test')
    assert isinstance(result, SearchResults)
    assert result.index == 'documents'
    assert result.total == 1
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.title == 'Test Paper'
    # Canonical URI prefers doi.org form
    assert hit.source_uri == 'https://doi.org/10.1234/test'
    assert hit.snippet == 'matching passage'
    assert hit.authors == ['Alice Smith', 'Jones, Bob']
    assert hit.content_size_tokens == 20_000


# ---------------------------------------------------------------------------
# search_social
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_social_pins_index_to_social():
    mcp, client, ctx = _build_mcp_with_mocks()
    fn = _tool_fn(mcp, 'spacefrontiers_search_social')
    await fn(ctx=ctx, query='breaking news')
    kwargs = client.search.call_args.kwargs
    assert kwargs['index_names'] == ['social']


@pytest.mark.asyncio
async def test_search_social_passes_uri_prefix_filter():
    mcp, client, ctx = _build_mcp_with_mocks()
    fn = _tool_fn(mcp, 'spacefrontiers_search_social')
    await fn(
        ctx=ctx,
        query='launch',
        filter_uri_prefixes=['@tech_news'],
        filter_issued_after=1711929600,
    )
    kwargs = client.search.call_args.kwargs
    assert kwargs['filter_uri_prefixes'] == ['@tech_news']
    assert kwargs['filter_issued_after'] == 1711929600


@pytest.mark.asyncio
async def test_search_social_browse_subreddit_with_empty_query():
    mcp, client, ctx = _build_mcp_with_mocks()
    fn = _tool_fn(mcp, 'spacefrontiers_search_social')
    await fn(
        ctx=ctx,
        filter_uri_prefixes=['https://reddit.com/r/MachineLearning/'],
        filter_issued_after=1711929600,
    )
    args = client.search.call_args.args
    kwargs = client.search.call_args.kwargs
    assert args == ('',)
    assert kwargs['index_names'] == ['social']


# ---------------------------------------------------------------------------
# fetch_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_document_returns_typed_full_document():
    raw_doc = {
        'uris': ['https://doi.org/10.1234/test'],
        'document': {
            'title': 'A Paper',
            'abstract': 'An abstract.',
            'content': 'x' * 50_000,
            'authors': [{'name': 'Alice'}],
            'references': [{'title': 'Ref1', 'doi': '10.5555/ref1'}],
        },
    }
    mcp, _, ctx = _build_mcp_with_mocks(fetch_return=raw_doc)
    fn = _tool_fn(mcp, 'spacefrontiers_fetch_document')
    result = await fn(ctx=ctx, uri='https://doi.org/10.1234/test')
    assert isinstance(result, FullDocument)
    assert result.title == 'A Paper'
    assert result.source_uri == 'https://doi.org/10.1234/test'
    assert result.content_truncated is False
    assert result.full_content_length == 50_000
    assert len(result.references) == 1
    assert result.references[0].source_uri == 'https://doi.org/10.5555/ref1'


@pytest.mark.asyncio
async def test_fetch_document_truncates_long_content():
    from tools import MAX_CONTENT_LENGTH
    raw_doc = {
        'uris': ['https://doi.org/10.1234/test'],
        'document': {
            'title': 'Big Doc',
            'content': 'x' * (MAX_CONTENT_LENGTH + 5_000),
        },
    }
    mcp, _, ctx = _build_mcp_with_mocks(fetch_return=raw_doc)
    fn = _tool_fn(mcp, 'spacefrontiers_fetch_document')
    result = await fn(ctx=ctx, uri='https://doi.org/10.1234/test')
    assert isinstance(result, FullDocument)
    assert result.content_truncated is True
    assert len(result.content) == MAX_CONTENT_LENGTH
    assert result.full_content_length == MAX_CONTENT_LENGTH + 5_000


@pytest.mark.asyncio
async def test_fetch_document_missing_raises_tool_error():
    mcp, _, ctx = _build_mcp_with_mocks(fetch_return=None)
    fn = _tool_fn(mcp, 'spacefrontiers_fetch_document')
    with pytest.raises(ToolError) as exc:
        await fn(ctx=ctx, uri='https://doi.org/10.1234/missing')
    assert 'No document with URI' in str(exc.value)


# ---------------------------------------------------------------------------
# search_in_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_in_document_returns_passages():
    snippets_data = {
        'uris': ['https://doi.org/10.1234/test'],
        'hits': [
            {
                'document': {'title': 'Big Paper', 'uris': ['https://doi.org/10.1234/test']},
                'snippets': [
                    {'text': 'first match', 'field': 'content', 'score': 0.95},
                    {'text': 'second match', 'field': 'content', 'score': 0.80},
                ],
            }
        ],
    }
    mcp, _, ctx = _build_mcp_with_mocks(fetch_return=snippets_data)
    fn = _tool_fn(mcp, 'spacefrontiers_search_in_document')
    result = await fn(ctx=ctx, uri='https://doi.org/10.1234/test', query='match')
    assert isinstance(result, DocumentPassages)
    assert result.title == 'Big Paper'
    assert len(result.passages) == 2
    assert result.passages[0].text == 'first match'
    assert result.fallback_full_document is None


@pytest.mark.asyncio
async def test_search_in_document_falls_back_to_full_when_no_passages():
    # First call (text_filter) returns empty hits, second call (no text_filter) returns the doc.
    full_doc = {
        'uris': ['https://doi.org/10.1234/test'],
        'document': {'title': 'Big Paper', 'content': 'irrelevant body'},
    }

    call_count = {'n': 0}

    async def get_doc_side_effect(uri, *, text_filter=None):
        call_count['n'] += 1
        if text_filter is not None:
            return {'hits': [], 'uris': [uri]}
        return full_doc

    mcp, client, ctx = _build_mcp_with_mocks()
    client.get_document_by_uri = AsyncMock(side_effect=get_doc_side_effect)
    fn = _tool_fn(mcp, 'spacefrontiers_search_in_document')
    result = await fn(ctx=ctx, uri='https://doi.org/10.1234/test', query='nothing-matches')
    assert isinstance(result, DocumentPassages)
    assert result.passages == []
    assert isinstance(result.fallback_full_document, FullDocument)
    assert result.fallback_full_document.title == 'Big Paper'
    assert call_count['n'] == 2


# ---------------------------------------------------------------------------
# Billing / auth error envelopes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insufficient_funds_raises_tool_error():
    mcp, _, ctx = _build_mcp_with_mocks(search_side_effect=InsufficientFundsError())
    fn = _tool_fn(mcp, 'spacefrontiers_search_documents')
    with pytest.raises(ToolError) as exc:
        await fn(ctx=ctx, query='anything')
    assert 'Insufficient funds' in str(exc.value)
    assert 'spacefrontiers.org/payments' in str(exc.value)


@pytest.mark.asyncio
async def test_authentication_error_raises_tool_error():
    mcp, _, ctx = _build_mcp_with_mocks(search_side_effect=AuthenticationError())
    fn = _tool_fn(mcp, 'spacefrontiers_search_social')
    with pytest.raises(ToolError) as exc:
        await fn(ctx=ctx, query='anything')
    assert 'Authentication failed' in str(exc.value)
    assert 'spacefrontiers.org/keys' in str(exc.value)


# ---------------------------------------------------------------------------
# DocumentResult canonical-URI selection
# ---------------------------------------------------------------------------


def test_document_result_prefers_doi_url():
    from tools import _canonical_uri
    assert _canonical_uri(['arxiv:2301.00001', 'https://doi.org/10.1/abc', 'doi://10.1/abc']) == 'https://doi.org/10.1/abc'


def test_document_result_falls_back_to_http():
    from tools import _canonical_uri
    assert _canonical_uri(['arxiv:2301.00001', 'https://arxiv.org/abs/2301.00001']) == 'https://arxiv.org/abs/2301.00001'


def test_document_result_falls_back_to_scheme_uri():
    from tools import _canonical_uri
    assert _canonical_uri(['arxiv:2301.00001']) == 'arxiv:2301.00001'


def test_document_result_empty_uris_returns_empty_string():
    from tools import _canonical_uri
    assert _canonical_uri([]) == ''
