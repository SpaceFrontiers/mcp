import os
import typing
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastmcp import FastMCP, Context
from spacefrontiers.clients import SearchApiClient
from spacefrontiers.clients.types import (
    SearchRequest,
    SimpleSearchRequest,
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
    dependencies=["izihawa-loglib", "spacefrontiers-clients>=0.0.92"],
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


@mcp.tool
async def general_search(
    ctx: Context,
    query: str,
) -> str:
    """General search over various subjects"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources_filters={"library": {}, "reddit": {}, "telegram": {}},
            limit=70,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool
async def telegram_search(
    ctx: Context,
    query: str,
    telegram_channel_names: list[str] | None = None,
) -> str:
    """Search over new posts in Telegram for a given query with possibility to filter search over particular channels,
    suitable for search of fresh news"""
    api_key, user_id = process_authorization(ctx)
    filters = {}
    if telegram_channel_names:
        filters["telegram_channel_names"] = telegram_channel_names
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources_filters={"telegram": filters},
            limit=70,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool
async def get_telegram_posts(
    ctx: Context,
    telegram_channel_names: list[str],
    query: str | None = None,
    scoring: typing.Literal["default", "temporal"] = "default",
) -> str:
    """Retrieve posts from Telegram channels with the possibility to order by recency and filter by text query"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            query=query,
            source="telegram",
            filters={
                "telegram_channel_names": telegram_channel_names,
            },
            scoring=scoring,
            limit=50,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=80, path="/")