import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta, datetime

from fastmcp import FastMCP, Context
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
    dependencies=["izihawa-loglib", "spacefrontiers-clients>=0.0.93"],
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


@mcp.tool
async def general_search(
    ctx: Context,
    query: str,
    limit: int = 50,
) -> SearchResponse:
    """General search over various subjects"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources_filters={"library": {}, "reddit": {}, "telegram": {}},
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool
async def telegram_search(
    ctx: Context,
    query: str,
    telegram_channel_usernames: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 50
) -> SearchResponse:
    """Search over new posts in Telegram for a given query with the possibility to filter search over particular channels,
    suitable for search"""
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if telegram_channel_usernames:
        filters["telegram_channel_usernames"] = telegram_channel_usernames
    if start_date or end_date:
        if not start_date:
            start_date = date.fromtimestamp(0)
        if not end_date:
            end_date = date.today() + timedelta(days=1)
        filters["issued_at"] = [(time.mktime(start_date.timetuple()), time.mktime(end_date.timetuple()))]
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


@mcp.tool
async def get_lastest_posts_for_channels(
    ctx: Context,
    telegram_channel_usernames: list[str],
    query: str | None = None,
    limit: int = 10,
) -> SearchResponse:
    """Retrieve the latest posts from Telegram channels with the possibility to order by recency, filter by text query and limit the amount"""
    api_key, user_id = process_authorization(ctx)
    search_response = await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            query=query,
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


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=80, path="/")