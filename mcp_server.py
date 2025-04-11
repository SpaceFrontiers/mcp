import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from spacefrontiers.clients import SearchApiClient
from spacefrontiers.clients.types import (
    FiltersType,
    SearchRequest,
    SimpleSearchRequest,
    SourceName,
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
async def simple_search(
    ctx: Context,
    source: SourceName,
    query: str,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Keyword search over Space Frontiers databases (library, telegram or reddit)"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.simple_search(
        SimpleSearchRequest(
            query=query,
            source=source,
            limit=limit,
            offset=offset,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )


@mcp.tool()
async def search(
    ctx: Context,
    query: str,
    sources: list[SourceName] = ("library",),
    filters: FiltersType | None = None,
    limit: int = 10,
) -> str:
    """Semantic search over Space Frontiers databases (library, telegram or reddit)"""
    api_key, user_id = process_authorization(ctx)
    return await ctx.request_context.lifespan_context.search_api_client.search(
        SearchRequest(
            query=query,
            sources=sources,
            filters=filters,
            limit=limit,
        ),
        api_key=api_key,
        user_id=user_id,
        request_context=RequestContext(request_source="mcp"),
    )
