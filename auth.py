"""Auth middleware: validates Bearer tokens via users-api, returns OAuth 401."""

import contextvars
import logging

import aiohttp
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Per-request auth headers, read by SearchV2Client._get_headers()
auth_headers_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar('auth_headers', default=None)


def _unauthorized(content: str, resource_url: str) -> Response:
    return Response(
        status_code=401,
        headers={'WWW-Authenticate': f'Bearer resource_metadata="{resource_url}"'},
        media_type='text/plain',
        content=content,
    )


class AuthValidationMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token via users-api; return 401 with OAuth metadata if invalid."""

    def __init__(
        self,
        app,
        users_api_url: str = 'http://users-api',
        resource_url: str = 'https://mcp.spacefrontiers.org/.well-known/oauth-protected-resource',
    ):
        super().__init__(app)
        self._auth_url = f'{users_api_url.rstrip("/")}/v2/users/auth/'
        self._resource_url = resource_url
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def dispatch(self, request, call_next):
        auth_header = request.headers.get('authorization', '')

        if not auth_header:
            return _unauthorized('Authentication required', self._resource_url)

        # Validate token with users-api
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
