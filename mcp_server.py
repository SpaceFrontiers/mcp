import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta, datetime
from typing import Annotated, Literal

from fastmcp import FastMCP, Context
from pydantic import Field
from spacefrontiers.clients import SearchApiClient
from spacefrontiers.clients.types import (
    SearchRequest,
    SimpleSearchRequest,
    SearchResponse, QueryClassifierConfig,
)

from izihawa_loglib.request_context import RequestContext


@dataclass
class AppContext:
    search_api_client: SearchApiClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    async with SearchApiClient(
        base_url=os.environ.get(
            "SPACE_FRONTIERS_API_ENDPOINT", "https://api.spacefrontiers.org"
        )
    ) as search_api_client:
        yield AppContext(search_api_client=search_api_client)


mcp = FastMCP(
    "Space Frontiers MCP Server",
    dependencies=["izihawa-loglib", "spacefrontiers-clients>=0.0.95"],
    lifespan=app_lifespan,
)


def process_authorization(ctx: Context) -> tuple[str | None, str | None]:
    api_key, user_id = None, None
    if not getattr(ctx.request_context, "request", None):
        api_key = os.environ.get("SPACE_FRONTIERS_API_KEY")
    else:
        headers = ctx.request_context.request.headers
        if "X-User-Id" in headers:
            user_id = headers["X-User-Id"]
        elif "Authorization" in headers:
            api_key = headers["Authorization"].removeprefix("Bearer").strip()
        elif "X-Api-Key" in headers:
            api_key = headers["X-Api-Key"]
        elif env_api_key := os.environ.get("SPACE_FRONTIERS_API_KEY"):
            api_key = env_api_key
    return api_key, user_id


def format_search_response(search_response: SearchResponse) -> SearchResponse:
    for search_document in search_response.search_documents:
        if "issued_at" in search_document.document:
            search_document.document["issued_at"] = datetime.fromtimestamp(search_document.document["issued_at"]).isoformat()
    return search_response


def setup_date_filter(start_date, end_date, filters):
    if start_date or end_date:
        if not start_date:
            start_date = date.fromtimestamp(0)
        if not end_date:
            end_date = date.today() + timedelta(days=1)
        filters["issued_at"] = [(time.mktime(start_date.timetuple()), time.mktime(end_date.timetuple()))]


@mcp.tool
async def research_tool(
    ctx: Context,
    query: Annotated[str, Field(description="The search query")],
    sources: Annotated[list[Literal["wiki", "pubmed", "standard"]], Field(description="The datasets to search query in")],
    start_date: Annotated[date | None, Field(description="Search documents starting from the date")] = None,
    end_date: Annotated[date | None, Field(description="Search documents before the date")] = None,
    limit: Annotated[int, Field(description="The approximate amount of Telegram posts to search", ge=1, le=100)] = 50,
) -> SearchResponse:
    """Tool for retrieving documents on scholar, standard or general topics in different datasets"""
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if sources:
        if "pubmed" in sources:
            sources.remove("pubmed")
            filters["metadata.is_pubmed"] = [True]
        filters["type"] = sources
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources_filters={"library": filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={"title": "Telegram search"})
async def telegram_search(
    ctx: Context,
    query: Annotated[str, Field(description="The search query")],
    telegram_channel_usernames: Annotated[list[str] | None, Field(description="The list of Telegram channel usernames for searching messages")] = None,
    start_date: Annotated[date | None, Field(description="Search messages starting from the date")] = None,
    end_date: Annotated[date | None, Field(description="Search messages before the date")] = None,
    limit: Annotated[int, Field(description="The approximate amount of Telegram posts to search", ge=1, le=100)] = 50,
) -> SearchResponse:
    """Search over new posts in Telegram for a given query with the possibility to filter search over particular channels and dates"""
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if telegram_channel_usernames:
        filters["telegram_channel_usernames"] = telegram_channel_usernames
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            refining_target=None,
            query_classifier=QueryClassifierConfig(related_queries=3),
            sources_filters={"telegram": filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={"title": "Recent posts from Telegram channels"})
async def get_recent_posts_from_telegram_channels(
    ctx: Context,
    telegram_channel_usernames: Annotated[list[str], Field(description="The list of Telegram channel usernames for loading messages")],
    limit: Annotated[int, Field(description="The total amount of Telegram posts to load", ge=1, le=100)] = 50,
) -> SearchResponse:
    """Retrieve the latest posts from Telegram channels ordered by recency"""
    api_key, user_id = process_authorization(ctx)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            source="telegram",
            filters={
                "telegram_channel_usernames": telegram_channel_usernames,
            },
            scoring="temporal",
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={"title": "Reddit search"})
async def reddit_search(
    ctx: Context,
    query: Annotated[str, Field(description="The search query")],
    subreddits: Annotated[list[str] | None, Field(description="The list of subreddits for searching submissions")] = None,
    start_date: Annotated[date | None, Field(description="Search messages starting from the date")] = None,
    end_date: Annotated[date | None, Field(description="Search messages before the date")] = None,
    limit: Annotated[int, Field(description="The approximate amount of Reddit submissions to search", ge=1, le=100)] = 50,
) -> SearchResponse:
    """Search over new posts in Reddit for a given query with the possibility to filter search over particular subreddits and dates"""
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if subreddits:
        filters["metadata.subreddit"] = [subreddit.removeprefix('r/') for subreddit in subreddits]
    setup_date_filter(start_date, end_date, filters)
    search_response = await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            refining_target=None,
            query_classifier=QueryClassifierConfig(related_queries=3),
            sources_filters={"telegram": filters},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
    return format_search_response(search_response)


@mcp.tool(annotations={"title": "Recent posts from Reddit"})
async def get_recent_posts_from_reddit(
    ctx: Context,
    subreddits: Annotated[list[str], Field(description="The list of subbreddits for loading messages")],
    limit: Annotated[int, Field(description="The total amount of Reddit posts to load", ge=1, le=100)] = 50,
    with_comments: Annotated[bool, Field(description="Whether to include comments in the search results")] = False,
) -> SearchResponse:
    """Retrieve the latest posts from Reddit subreddits ordered by recency"""
    api_key, user_id = process_authorization(ctx)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            source="reddit",
            filters={
                "metadata.subreddit": subreddits,
            },
            scoring="temporal",
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
    return format_search_response(search_response)



if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=80, path="/")