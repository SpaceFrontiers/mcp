from datetime import date
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from izihawa_loglib.request_context import RequestContext
from pydantic import Field
from spacefrontiers.clients.types import (
    QueryClassifierConfig,
    SearchRequest,
    SearchResponse,
    SimpleSearchRequest,
)

from utils import format_search_response, process_authorization, setup_date_filter, setup_sources_filter


def setup_tools(mcp: FastMCP):
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
        limit: Annotated[int, Field(description='Approximate number of Telegram posts to return', ge=1, le=100)] = 50,
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
