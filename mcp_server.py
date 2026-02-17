import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aiohttp
from fastmcp import FastMCP

from client import SearchV2Client
from prompts import setup_prompts
from tools import setup_tools


@dataclass
class AppContext:
    search_client: SearchV2Client


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    search_api_url = os.environ.get(
        'SEARCH_API_ENDPOINT', 'http://search-api',
    )
    async with aiohttp.ClientSession() as session:
        yield AppContext(
            search_client=SearchV2Client(search_api_url, session),
        )


mcp = FastMCP(
    'Space Frontiers MCP Server',
    lifespan=app_lifespan,
    instructions=(
        'Search and retrieve documents from a large corpus of academic papers, '
        'books, Wikipedia, patents, and more. This is a cheap and fast tool — '
        'use it liberally. Send multiple parallel search queries with varied '
        'phrasings for better coverage. Fetch documents to read full content, '
        'follow reference URIs to explore the citation graph, and do additional '
        'searches to build thorough research context.'
    ),
)


if __name__ == '__main__':
    setup_tools(mcp)
    setup_prompts(mcp)
    mcp.run(transport='http', host='0.0.0.0', port=80, path='/', stateless_http=True)
