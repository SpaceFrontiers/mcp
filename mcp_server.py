import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from spacefrontiers.clients import SearchApiClient
from spacefrontiers.clients.types import (
    SearchRequest,
)

from izihawa_loglib.request_context import RequestContext
from mcp.server.fastmcp import Context, FastMCP


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
    "Space Frontiers MCP server",
    dependencies=["izihawa-loglib", "spacefrontiers-clients"],
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


@mcp.tool()
async def general_search(
    ctx: Context,
    query: str,
) -> str:
    """General search over various subjects"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources=["library", "reddit", "telegram"],
            limit=70,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool()
async def news_search(
    ctx: Context,
    query: str,
) -> str:
    """Search over new posts in Telegram for a given query, suitable for search of fresh news"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources=["telegram"],
            limit=70,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool()
async def telegram_search_in_channels(
    ctx: Context,
    query: str,
    telegram_channel_names: list[str],
) -> str:
    """Search for a query in specific Telegram channels"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources=["telegram"],
            filters={
                "telegram_channel_names": telegram_channel_names,
            },
            limit=70,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
