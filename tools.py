"""MCP tools: search, fetch, and search_in_document.

search              — discover documents via sparse vector search (returns snippets).
fetch               — retrieve a specific document by URI (full content + references).
search_in_document  — find relevant passages within a single document.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from client import MAX_CONTENT_LENGTH, AuthenticationError, InsufficientFundsError
from formatting import (
    format_document,
    format_referenced_by,
    format_search_results,
    format_snippets,
)

logger = logging.getLogger(__name__)

Source = Literal['documents', 'social']

INSUFFICIENT_FUNDS_MSG = (
    'Insufficient funds. Your Space Frontiers balance is too low for this request.\n\n'
    'Add credits: https://spacefrontiers.org/payments?amount=10\n\n'
    'Pricing: searches cost ~$0.005, document fetches ~$0.01.\n'
    '$10 gives you approximately 2,000 searches.'
)

AUTH_ERROR_MSG = (
    'Authentication required. Your API key may be invalid or expired.\n\n'
    'Get a new API key: https://spacefrontiers.org/keys\n\n'
    'Then update your MCP configuration with the new key.'
)


def _handle_billing_errors(fn):
    """Decorator: catch billing/auth errors and return guidance text instead."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except InsufficientFundsError:
            return INSUFFICIENT_FUNDS_MSG
        except AuthenticationError:
            return AUTH_ERROR_MSG

    return wrapper


def setup_tools(mcp: FastMCP):
    @mcp.tool(annotations={'title': 'Search for documents'})
    @_handle_billing_errors
    async def search(
        ctx: Context,
        query: Annotated[str, Field(description='Free-text search query')],
        limit: Annotated[
            int,
            Field(
                description='Number of results to return. Use 20-30 for good coverage.',
                ge=1,
                le=100,
            ),
        ] = 30,
        source: Annotated[
            Source | None,
            Field(
                description=(
                    'Which index to search:\n'
                    '- "documents" — scholarly papers, books, patents, Wikipedia, '
                    'standards, manuals (use for scientific, factual, or technical queries)\n'
                    '- "social" — Reddit, Telegram, YouTube '
                    '(use for opinions, discussions, news, community knowledge)\n'
                    'Omit to search all sources.'
                ),
            ),
        ] = None,
    ) -> str:
        """Search across a corpus of 120M+ documents and return top results with snippets.

        The corpus includes two indexes:
        - **documents**: academic papers (CrossRef, PubMed, arXiv), books, patents,
          Wikipedia, technical standards, and manuals.
        - **social**: Reddit posts/comments, Telegram channel messages, YouTube transcripts.

        Each result includes title, URIs (DOI, ISBN, arXiv, PubMed, etc.),
        a relevance score, and the best-matching text snippet.

        **Tips for effective searching:**
        - Use a limit of **20-30** to get good coverage of the corpus.
        - Use 2-6 varied queries covering different aspects, synonyms, or phrasings.
          For example, instead of just "CRISPR gene editing", also try "cas9 genome
          engineering", "guide RNA targeting", etc.
        - Send several search calls in parallel for related queries and combine results.
        - Use URIs from results with ``fetch`` to read full documents and follow citations.
        - Use ``search_in_document`` to find specific passages within large documents.
        """
        client = ctx.request_context.lifespan_context.search_client
        index_names = [source] if source else None
        data = await client.search(query, limit=limit, index_names=index_names)
        return format_search_results(data)

    @mcp.tool(annotations={'title': 'Fetch a document by URI'})
    @_handle_billing_errors
    async def fetch(
        ctx: Context,
        uri: Annotated[
            str,
            Field(
                description=(
                    'Exact URI taken from search results or document references. '
                    'Must be copied verbatim — do NOT compose or guess URIs.'
                ),
            ),
        ],
    ) -> str:
        """Retrieve a full document by its URI.

        Returns the document's title, authors, abstract, content, metadata,
        references (with titles and URIs), and documents that cite this one.

        Use reference URIs to follow the citation graph and discover related work.

        **For large documents** (over ~20K tokens as shown in search result Size field),
        consider using ``search_in_document`` instead to extract only relevant passages.

        This is a cheap tool — don't hesitate to fetch documents and follow references.
        """
        client = ctx.request_context.lifespan_context.search_client

        doc, referenced_by_data = await asyncio.gather(
            client.get_document_by_uri(uri),
            client.find_referenced_by(uri, limit=30),
        )
        if doc is None:
            return 'Document not found.'
        result = format_document(doc, max_content=MAX_CONTENT_LENGTH)

        referenced_by_section = format_referenced_by(referenced_by_data)
        if referenced_by_section:
            result += '\n\n' + referenced_by_section
        return result

    @mcp.tool(annotations={'title': 'Search within a document'})
    @_handle_billing_errors
    async def search_in_document(
        ctx: Context,
        uri: Annotated[
            str,
            Field(
                description=(
                    'Exact URI of the document to search within. '
                    'Must be copied verbatim from search results or references.'
                ),
            ),
        ],
        query: Annotated[
            str,
            Field(
                description='Text query to find relevant passages within the document.',
            ),
        ],
    ) -> str:
        """Find relevant passages within a specific document.

        Runs a sparse search scoped to one document and returns the best-matching
        snippets along with document metadata and references.

        Use this instead of ``fetch`` when:
        - The document is large (over ~20K tokens) and you need specific information.
        - You want to find particular passages without reading the entire content.
        """
        client = ctx.request_context.lifespan_context.search_client

        snippets_data, referenced_by_data = await asyncio.gather(
            client.get_document_by_uri(uri, text_filter=query),
            client.find_referenced_by(uri, limit=30),
        )
        if snippets_data is None:
            return 'Document not found.'

        result = format_snippets(snippets_data)
        if not result:
            # Sparse search found no matching passages — fall back to full document
            doc = await client.get_document_by_uri(uri)
            if doc is not None:
                result = format_document(doc, max_content=MAX_CONTENT_LENGTH)
            else:
                result = 'No matching passages found.'

        referenced_by_section = format_referenced_by(referenced_by_data)
        if referenced_by_section:
            result += '\n\n' + referenced_by_section
        return result
