"""Per-request auth header propagation via contextvars."""

import contextvars

from starlette.middleware.base import BaseHTTPMiddleware

# Per-request auth headers captured by middleware, read by tool handlers
auth_headers_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    'auth_headers', default=None
)

_AUTH_HEADER_NAMES = ('x-user-id', 'x-organization-id')


class AuthHeaderMiddleware(BaseHTTPMiddleware):
    """Capture nginx-injected auth headers and expose them via contextvars."""

    async def dispatch(self, request, call_next):
        auth = {}
        for key in _AUTH_HEADER_NAMES:
            if value := request.headers.get(key):
                auth[key] = value
        token = auth_headers_var.set(auth)
        try:
            return await call_next(request)
        finally:
            auth_headers_var.reset(token)
