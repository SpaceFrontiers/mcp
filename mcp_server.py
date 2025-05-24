import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP
from spacefrontiers.clients import SearchApiClient

from tools import setup_tools
from prompts import setup_prompts


@dataclass
class AppContext:
    search_api_client: SearchApiClient


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    async with SearchApiClient(
        base_url=os.environ.get('SPACE_FRONTIERS_API_ENDPOINT', 'https://api.spacefrontiers.org')
    ) as search_api_client:
        yield AppContext(search_api_client=search_api_client)


mcp = FastMCP(
    'Space Frontiers MCP Server',
    dependencies=['izihawa-loglib', 'spacefrontiers-clients>=0.0.98'],
    lifespan=app_lifespan,
    instructions="""
    Do searches over datasets and helps with the analysis of these documents and returns search documents
    """,
)


if __name__ == '__main__':
    setup_tools(mcp)
    setup_prompts(mcp)
    mcp.run(transport='http', host='0.0.0.0', port=80, path='/')
