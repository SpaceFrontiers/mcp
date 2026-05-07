"""Auth + transport-hardening middleware for the MCP server.

Validates Bearer tokens via users-api, enforces an Origin allowlist (DNS-rebinding
defense per the MCP spec security warning) and an MCP-Protocol-Version allowlist.
"""

import contextvars
import logging

import aiohttp
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Per-request auth headers, read by SearchV2Client._get_headers()
auth_headers_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar('auth_headers', default=None)

# MCP spec revisions this server speaks. Clients send `MCP-Protocol-Version`
# on every HTTP request; per spec we 400 unknown versions and assume the
# 2025-03-26 default when the header is absent.
SUPPORTED_PROTOCOL_VERSIONS = frozenset({'2025-03-26', '2025-06-18', '2025-11-25'})

# Origin allowlist for browser-mounted MCP clients. Non-browser clients (Claude
# Code, fastmcp CLI, raw curl) do not send Origin and are allowed through.
DEFAULT_ALLOWED_ORIGINS = frozenset({
    'https://claude.ai',
    'https://claude.com',
    'https://chatgpt.com',
    'https://cursor.com',
    'https://spacefrontiers.org',
    'null',
})


def _unauthorized(content: str, resource_url: str) -> Response:
    return Response(
        status_code=401,
        headers={'WWW-Authenticate': f'Bearer resource_metadata="{resource_url}"'},
        media_type='text/plain',
        content=content,
    )


class AuthValidationMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token, Origin and MCP-Protocol-Version on every request."""

    def __init__(
        self,
        app,
        users_api_url: str = 'http://users-api',
        resource_url: str = 'https://mcp.spacefrontiers.org/.well-known/oauth-protected-resource',
        allowed_origins: frozenset[str] = DEFAULT_ALLOWED_ORIGINS,
    ):
        super().__init__(app)
        self._auth_url = f'{users_api_url.rstrip("/")}/v2/users/auth/'
        self._resource_url = resource_url
        self._allowed_origins = allowed_origins
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def dispatch(self, request, call_next):
        # CORS preflight: short-circuit before any auth/version check.
        if request.method == 'OPTIONS':
            return Response(status_code=204)

        # Origin allowlist (DNS-rebinding defense per MCP spec security note).
        # Per the 2025-11-25 changelog, reject with 403 (not 400).
        origin = request.headers.get('origin')
        if origin and origin not in self._allowed_origins:
            return Response(
                status_code=403,
                media_type='text/plain',
                content='Origin not allowed',
            )

        # MCP-Protocol-Version validation. Spec: 400 on unknown values; treat
        # absence as the 2025-03-26 default for backward compatibility.
        protocol_version = request.headers.get('mcp-protocol-version')
        if protocol_version and protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            return Response(
                status_code=400,
                media_type='text/plain',
                content=f'Unsupported MCP-Protocol-Version: {protocol_version}',
            )

        auth_header = request.headers.get('authorization', '')
        if not auth_header:
            return _unauthorized('Authentication required', self._resource_url)

        try:
            session = await self._get_session()
            async with session.get(self._auth_url, headers={'Authorization': auth_header}) as resp:
                if resp.status != 200:
                    return _unauthorized('Invalid or expired credentials', self._resource_url)
                user_id = resp.headers.get('x-user-id')
                org_id = resp.headers.get('x-organization-id')
        except Exception:
            logger.warning('Auth validation failed', exc_info=True)
            return Response(
                status_code=503,
                media_type='text/plain',
                content='Auth service unavailable',
            )

        auth: dict[str, str] = {}
        if user_id:
            auth['x-user-id'] = user_id
        if org_id:
            auth['x-organization-id'] = org_id

        token = auth_headers_var.set(auth)
        try:
            return await call_next(request)
        finally:
            auth_headers_var.reset(token)
