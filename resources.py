"""MCP resources: expose documents as readable URIs via the resources/* methods.

Registers a single URI template `spacefrontiers://document/{uri_b64}` so that
clients (Cursor file picker, Claude Desktop attach panel, IDE indexers) can
discover Space Frontiers documents alongside local files. The `{uri_b64}`
segment is the canonical document URI base64-url-encoded.

The `spacefrontiers_fetch_document` tool remains the primary read path; this
resource mirror exists for clients that pick up documents through the
resources surface rather than through tool calls.
"""

from __future__ import annotations

import base64
import json
import logging

from fastmcp import Context, FastMCP

from client import DEFAULT_CONTENT_LENGTH
from tools import _doc_to_full, _normalize_uri

logger = logging.getLogger(__name__)


def _encode_uri(uri: str) -> str:
    return base64.urlsafe_b64encode(uri.encode('utf-8')).decode('ascii').rstrip('=')


def _decode_uri(token: str) -> str:
    padding = '=' * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + padding).decode('utf-8')


def setup_resources(mcp: FastMCP):
    @mcp.resource(
        uri='spacefrontiers://document/{uri_b64}',
        name='Space Frontiers document',
        description=(
            'Bounded full text + references for one Space Frontiers document. '
            'The {uri_b64} segment is the canonical document URI '
            '(DOI URL, arXiv URL, etc.) base64-url-encoded without padding.'
        ),
        mime_type='application/json',
    )
    async def read_document(uri_b64: str, ctx: Context) -> str:
        """Resolve a base64-encoded canonical URI to a JSON FullDocument blob."""
        try:
            uri = _decode_uri(uri_b64)
        except Exception:
            logger.warning('Invalid uri_b64 token in resources/read: %s', uri_b64[:32])
            return json.dumps({'error': 'invalid_uri_token'})

        uri = _normalize_uri(uri)
        client = ctx.request_context.lifespan_context.search_client
        doc = await client.get_document_by_uri(uri)
        if doc is None:
            return json.dumps({'error': 'not_found', 'uri': uri})

        # Keep resources/read bounded and single-request just like the default
        # fetch tool. Citation backlinks remain an explicit tool opt-in.
        full = _doc_to_full(doc, [], DEFAULT_CONTENT_LENGTH)
        return full.model_dump_json()
