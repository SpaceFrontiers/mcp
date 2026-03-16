import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aiohttp
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from auth import AuthValidationMiddleware
from client import SearchV2Client
from prompts import setup_prompts
from tools import setup_tools

# Single source of truth for public URLs (overridable for staging/dev)
MCP_PUBLIC_URL = os.environ.get('MCP_PUBLIC_URL', 'https://mcp.spacefrontiers.org')
SF_PUBLIC_URL = os.environ.get('SF_PUBLIC_URL', 'https://spacefrontiers.org')


@dataclass
class AppContext:
    search_client: SearchV2Client


@asynccontextmanager
async def app_lifespan(_: FastMCP) -> AsyncIterator[AppContext]:
    search_api_url = os.environ.get(
        'SEARCH_API_ENDPOINT',
        'http://search-api',
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

# -----------------------------------------------------------------------
# OAuth 2.0 metadata endpoints (served without authentication)
# -----------------------------------------------------------------------

OAUTH_METADATA = {
    'issuer': SF_PUBLIC_URL,
    'authorization_endpoint': f'{SF_PUBLIC_URL}/oauth/authorize',
    'token_endpoint': f'{SF_PUBLIC_URL}/api/oauth/token',
    'registration_endpoint': f'{SF_PUBLIC_URL}/api/oauth/register',
    'response_types_supported': ['code'],
    'grant_types_supported': ['authorization_code'],
    'code_challenge_methods_supported': ['S256'],
    'token_endpoint_auth_methods_supported': ['none'],
    'scopes_supported': ['search'],
}

OAUTH_PROTECTED_RESOURCE = {
    'resource': MCP_PUBLIC_URL,
    'authorization_servers': [MCP_PUBLIC_URL],
}

RESOURCE_METADATA_URL = f'{MCP_PUBLIC_URL}/.well-known/oauth-protected-resource'


async def oauth_authorization_server(request):
    return JSONResponse(OAUTH_METADATA)


async def oauth_protected_resource(request):
    return JSONResponse(OAUTH_PROTECTED_RESOURCE)


def create_app() -> Starlette:
    """Build the ASGI app: OAuth well-known endpoints + MCP protocol."""
    users_api_url = os.environ.get('USERS_API_ENDPOINT', 'http://users-api')

    setup_tools(mcp)
    setup_prompts(mcp)

    mcp_app = mcp.http_app(
        path='/',
        stateless_http=True,
        middleware=[
            Middleware(
                AuthValidationMiddleware,
                users_api_url=users_api_url,
                resource_url=RESOURCE_METADATA_URL,
            )
        ],
    )

    return Starlette(
        routes=[
            Route(
                '/.well-known/oauth-authorization-server',
                oauth_authorization_server,
            ),
            Route(
                '/.well-known/oauth-protected-resource',
                oauth_protected_resource,
            ),
            Mount('/', app=mcp_app),
        ],
        lifespan=mcp_app.lifespan,
    )


app = create_app()

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=80)
