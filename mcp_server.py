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
from resources import setup_resources
from tools import setup_tools

# Single source of truth for public URLs (overridable for staging/dev).
# OAuth runs on api.spacefrontiers.org (no Cloudflare JS challenge for
# programmatic clients); the consent UI runs on spacefrontiers.org (browser).
MCP_PUBLIC_URL = os.environ.get('MCP_PUBLIC_URL', 'https://mcp.spacefrontiers.org')
SF_PUBLIC_URL = os.environ.get('SF_PUBLIC_URL', 'https://spacefrontiers.org')
SF_API_PUBLIC_URL = os.environ.get('SF_API_PUBLIC_URL', 'https://api.spacefrontiers.org')


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
        'Space Frontiers is a full-text retrieval layer over two corpora:\n'
        '  - documents — peer-reviewed papers, books, patents, and Wikipedia\n'
        '  - social    — Reddit, Telegram channels, YouTube transcripts\n\n'
        'Tool map:\n'
        '  - spacefrontiers_search_documents — papers/books/patents/Wikipedia\n'
        '  - spacefrontiers_search_social    — Reddit/Telegram/YouTube\n'
        '  - spacefrontiers_fetch_document   — full text + references for one URI\n'
        '  - spacefrontiers_search_in_document — passages within one document\n\n'
        'Default workflow: search first (cheap, fast, batch 2-6 parallel queries '
        'with varied phrasings), then fetch by `source_uri` for full text. For '
        'broad topics that mix research and discussion, call both search_documents '
        'and search_social in parallel. Search is cheap — use liberally; fetch is '
        'heavier — batch URIs when possible.\n\n'
        'Citation contract: every result includes a `source_uri`. Cite that URI '
        'verbatim when quoting; do NOT invent URLs or guess DOIs.\n\n'
        'Supported URI schemes for fetch_document and search_in_document:\n'
        '  - https://doi.org/10.…   - doi:10.…\n'
        '  - arxiv:2301.00001       - pmid:12345678\n'
        '  - isbn:9780262033848     - any URI returned by a search hit\n\n'
        'Failure modes: an empty result for a known DOI usually means the document '
        'is queued for crawl in the background — retry in a few minutes, or fall '
        'back to search_social for community discussion of the same paper.\n\n'
        'What this server is NOT for: general web search, code search, or '
        'paywalled content not in our corpus. Use a different MCP server for those.'
    ),
)

# -----------------------------------------------------------------------
# OAuth 2.0 metadata endpoints (served without authentication)
# -----------------------------------------------------------------------

OAUTH_METADATA = {
    'issuer': SF_API_PUBLIC_URL,
    'authorization_endpoint': f'{SF_PUBLIC_URL}/oauth/authorize',
    'token_endpoint': f'{SF_API_PUBLIC_URL}/v2/oauth/token',
    'registration_endpoint': f'{SF_API_PUBLIC_URL}/v2/oauth/register',
    'revocation_endpoint': f'{SF_API_PUBLIC_URL}/v2/oauth/revoke',
    'response_types_supported': ['code'],
    'grant_types_supported': ['authorization_code', 'refresh_token'],
    'code_challenge_methods_supported': ['S256'],
    'token_endpoint_auth_methods_supported': ['none'],
    'revocation_endpoint_auth_methods_supported': ['none'],
    'scopes_supported': ['search'],
}

OAUTH_PROTECTED_RESOURCE = {
    'resource': MCP_PUBLIC_URL,
    'authorization_servers': [SF_API_PUBLIC_URL],
    'bearer_methods_supported': ['header'],
    'scopes_supported': ['search'],
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
    setup_resources(mcp)

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
