import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from izihawa_loglib.request_context import RequestContext
from pydantic import Field
from spacefrontiers.clients import SearchApiClient
from spacefrontiers.clients.types import (
    QueryClassifierConfig,
    SearchRequest,
    SearchResponse,
    SimpleSearchRequest,
)


@dataclass
class AppContext:
    search_api_client: SearchApiClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    async with SearchApiClient(
        base_url=os.environ.get('SPACE_FRONTIERS_API_ENDPOINT', 'https://api.spacefrontiers.org')
    ) as search_api_client:
        yield AppContext(search_api_client=search_api_client)


mcp = FastMCP(
    'Space Frontiers MCP Server',
    dependencies=['izihawa-loglib', 'spacefrontiers-clients>=0.0.98'],
    lifespan=app_lifespan,
)


def process_authorization(ctx: Context) -> tuple[str | None, str | None]:
    api_key, user_id = None, None
    if not getattr(ctx.request_context, 'request', None):
        api_key = os.environ.get('SPACE_FRONTIERS_API_KEY')
    else:
        headers = ctx.request_context.request.headers
        if 'X-User-Id' in headers:
            user_id = headers['X-User-Id']
        elif 'Authorization' in headers:
            api_key = headers['Authorization'].removeprefix('Bearer').strip()
        elif 'X-Api-Key' in headers:
            api_key = headers['X-Api-Key']
        elif env_api_key := os.environ.get('SPACE_FRONTIERS_API_KEY'):
            api_key = env_api_key
    return api_key, user_id


def format_search_response(search_response: SearchResponse) -> SearchResponse:
    for search_document in search_response.search_documents:
        if 'issued_at' in search_document.document:
            search_document.document['issued_at'] = datetime.fromtimestamp(
                search_document.document['issued_at']
            ).isoformat()
    return search_response


def setup_date_filter(start_date, end_date, filters):
    if start_date or end_date:
        if not start_date:
            start_date = date.fromtimestamp(0)
        if not end_date:
            end_date = date.today() + timedelta(days=1)
        filters['issued_at'] = [(time.mktime(start_date.timetuple()), time.mktime(end_date.timetuple()))]


def setup_sources_filter(sources, filters):
    if sources:
        normalized_sources = [s.lower() for s in sources]
        remaining_types: list[str] = []
        if 'pubmed' in normalized_sources:
            filters['metadata.is_pubmed'] = [True]
            normalized_sources.remove('pubmed')
        if 'arxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('arxiv')
            normalized_sources.remove('arxiv')
        if 'biorxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('biorxiv')
            normalized_sources.remove('biorxiv')
        if 'medrxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('medrxiv')
            normalized_sources.remove('medrxiv')
        # Any remaining entries are treated as type filters (e.g., 'wiki', 'standard')
        if normalized_sources:
            remaining_types.extend(normalized_sources)
        if remaining_types:
            filters['type'] = remaining_types


@mcp.tool(annotations={'title': 'Scholarly/General search (Wiki, PubMed, Arxiv, BioRxiv, medRxiv)'})
async def research_tool(
    ctx: Context,
    query: Annotated[str, Field(description='Free-text search query (short descriptive phrase)')],
    source: Annotated[
        Literal['wiki', 'pubmed', 'standard', 'arxiv', 'biorxiv', 'medrxiv'],
        Field(description='The dataset to search in'),
    ],
    start_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include documents on/after this date')
    ] = None,
    end_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include documents up to and including this date')
    ] = None,
    limit: Annotated[int, Field(description='Approximate number of documents to return', ge=1, le=100)] = 50,
) -> SearchResponse:
    """Query-based search across Wiki, scholarly and general sources.

    When to use:
    - Use for queries like "find papers about X" or "wiki info about Y".
    - Requires a textual `query`.
    - For "recent publications" without a query, use `get_recent_scholar_publications` instead.
    """
    api_key, user_id = process_authorization(ctx)
    filters = {}
    setup_sources_filter([source], filters)
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources_filters={'library': filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={'title': 'Recent scholarly publications'})
async def get_recent_scholar_publications(
    ctx: Context,
    source: Annotated[
        Literal['pubmed', 'arxiv', 'biorxiv', 'medrxiv'],
        Field(description='The dataset to fetch recent publications from'),
    ],
    limit: Annotated[int, Field(description='Approximate number of publications to return', ge=1, le=100)] = 50,
) -> SearchResponse:
    """Get the most recent publications from a scholarly source.

    When to use:
    - Use for requests like "recent arxiv papers" or "latest medrxiv".
    - Does NOT accept a free-text query. For query-based search, use `research_tool`.
    - Recent by default means 30 days
    """
    api_key, user_id = process_authorization(ctx)
    filters = {}
    setup_sources_filter([source], filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            source='library',
            filters=filters,
            scoring='temporal',
            limit=limit,
            mode='or',
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={'title': 'Telegram search (query-based)'})
async def telegram_search(
    ctx: Context,
    query: Annotated[str, Field(description='Free-text query to match in Telegram posts')],
    telegram_channel_usernames: Annotated[
        list[str] | None,
        Field(description='List of Telegram channel usernames to filter by (with or without leading @)'),
    ] = None,
    start_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts on/after this date')
    ] = None,
    end_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts up to and including this date')
    ] = None,
    limit: Annotated[
        int, Field(description='Approximate number of Telegram posts to return', ge=1, le=100)
    ] = 50,
) -> SearchResponse:
    """Query-based search over Telegram posts.

    When to use:
    - Use when a free-text `query` is provided (e.g., "search Telegram for X").
    - Optional filters: `telegram_channel_usernames`, `start_date`, `end_date`.
    - For "recent posts in Telegram" without a query, use `get_recent_posts_from_telegram`.
    - For "recent posts from @channel", use `get_recent_posts_from_telegram`
      with `telegram_channel_usernames=["@channel"]`.
    - Recent by default means 1-7 days
    """
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if telegram_channel_usernames:
        filters['telegram_channel_usernames'] = telegram_channel_usernames
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            refining_target=None,
            query_classifier=QueryClassifierConfig(related_queries=3),
            sources_filters={'telegram': filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={'title': 'Recent posts from Telegram'})
async def get_recent_posts_from_telegram(
    ctx: Context,
    telegram_channel_usernames: Annotated[
        list[str] | None,
        Field(description='Optional list of Telegram channel usernames to filter by (with or without leading @)'),
    ] = None,
    start_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts on/after this date')
    ] = None,
    end_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts up to and including this date')
    ] = None,
    limit: Annotated[int, Field(description='Total number of Telegram posts to return', ge=1, le=100)] = 50,
) -> SearchResponse:
    """Retrieve recent Telegram posts ordered by recency (no free-text query).

    When to use:
    - Use for requests like "recent posts in Telegram".
    - Optionally filter by `telegram_channel_usernames` and/or a date range.
    - For query-based Telegram search, use `telegram_search`.
    """
    api_key, user_id = process_authorization(ctx)
    filters: dict[str, object] = {}
    if telegram_channel_usernames:
        filters['telegram_channel_usernames'] = telegram_channel_usernames
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            source='telegram',
            filters=filters,
            scoring='temporal',
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={'title': 'Reddit search (query-based)'})
async def reddit_search(
    ctx: Context,
    query: Annotated[str, Field(description='Free-text query to match in Reddit posts')],
    subreddits: Annotated[
        list[str] | None, Field(description='List of subreddit names (with or without leading r/)')
    ] = None,
    start_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts on/after this date')
    ] = None,
    end_date: Annotated[
        date | None, Field(description='ISO date (YYYY-MM-DD). Include posts up to and including this date')
    ] = None,
    limit: Annotated[
        int, Field(description='Approximate number of Reddit submissions to return', ge=1, le=100)
    ] = 50,
) -> SearchResponse:
    """Query-based search over Reddit posts.

    When to use:
    - Use when a free-text `query` is provided (e.g., "search Reddit for X").
    - Optional filters: `subreddits` (accepts names with or without leading r/), `start_date`, `end_date`.
    - For "recent posts from Reddit" without a query, use `get_recent_posts_from_reddit`.
    """
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if subreddits:
        filters['metadata.subreddit'] = [subreddit.removeprefix('r/') for subreddit in subreddits]
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            refining_target=None,
            query_classifier=QueryClassifierConfig(related_queries=3),
            sources_filters={'reddit': filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={'title': 'Recent posts from Reddit'})
async def get_recent_posts_from_reddit(
    ctx: Context,
    subreddits: Annotated[
        list[str], Field(description='List of subreddit names to load posts from (with or without leading r/)')
    ],
    limit: Annotated[int, Field(description='Total number of Reddit posts to return', ge=1, le=100)] = 50,
    with_comments: Annotated[
        bool,
        Field(description='Best-effort: include comments if available in backend (may be ignored)'),
    ] = False,
) -> SearchResponse:
    """Retrieve the latest posts from specific Reddit subreddits ordered by recency.

    When to use:
    - Use for requests like "latest on r/sub1, r/sub2".
    - Does not accept a free-text query. For query-based search on Reddit, use `reddit_search`.
    """
    api_key, user_id = process_authorization(ctx)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            source='reddit',
            filters={
                'metadata.subreddit': subreddits,
            },
            scoring='temporal',
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source='mcp'),
    )
    return format_search_response(search_response)


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=80, path='/')
