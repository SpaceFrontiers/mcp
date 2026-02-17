"""MCP tools: search and fetch.

search — discover documents via sparse vector search (returns snippets).
fetch  — retrieve a specific document by URI, optionally filtering content
         with a text query (returns relevant snippets or full document).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from client import MAX_CONTENT_LENGTH
from formatting import format_document, format_referenced_by, format_search_results, format_snippets

logger = logging.getLogger(__name__)

# Source → document type mapping
SOURCE_TYPE_MAP: dict[str, list[str]] = {
    'library': [
        'journal-article', 'proceedings-article', 'book-chapter',
        'book', 'edited-book', 'monograph', 'reference-book',
        'patent', 'wiki',
    ],
    'reddit': ['submission', 'comment'],
    'telegram': ['message'],
    'youtube': ['video'],
}

SourceType = Literal['library', 'reddit', 'telegram', 'youtube']


def setup_tools(mcp: FastMCP):
    @mcp.tool(annotations={'title': 'Search for documents'})
    async def search(
        ctx: Context,
        query: Annotated[str, Field(description='Free-text search query')],
        limit: Annotated[
            int,
            Field(description='Number of results to return', ge=1, le=100),
        ] = 30,
        source: Annotated[
            SourceType | None,
            Field(
                description=(
                    'Filter by source type. Options:\n'
                    '- "library" — academic papers, books, patents, Wikipedia '
                    '(use for scientific or factual queries)\n'
                    '- "reddit" — Reddit posts and comments '
                    '(use for opinions, discussions, community knowledge)\n'
                    '- "telegram" — Telegram messages '
                    '(use for real-time updates, news, community channels)\n'
                    '- "youtube" — YouTube video transcripts '
                    '(use for lectures, tutorials, talks)\n'
                    'Omit to search all sources.'
                ),
            ),
        ] = None,
    ) -> str:
        """Search across all sources and return top documents with snippets.

        Performs sparse-vector search over a large document corpus
        (academic papers, books, Wikipedia, patents, manuals, social media).
        Each result includes title, URIs (DOI, PubMed, arXiv, etc.),
        a relevance score, and the best-matching text snippet.

        This is a cheap and fast tool — use it liberally. For better
        precision, formulate 2-6 varied queries covering different aspects,
        synonyms, or phrasings of the topic. For example, instead of a
        single query "CRISPR gene editing", also try "cas9 genome
        engineering", "guide RNA targeting", etc. You are encouraged to
        send several search calls in parallel for these related queries.
        Combine results across queries for comprehensive coverage.

        Use the URIs from results with the ``fetch`` tool to read full
        documents, explore their references, or find specific passages.
        """
        client = ctx.request_context.lifespan_context.search_client
        filter_types = SOURCE_TYPE_MAP.get(source) if source else None
        data = await client.search(query, limit=limit, filter_types=filter_types, rerank=False)
        return format_search_results(data)

    @mcp.tool(annotations={'title': 'Fetch a document by URI'})
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
        text_filter: Annotated[
            str | None,
            Field(
                description=(
                    'Optional text query to find relevant passages within '
                    'the document. When provided, returns scored snippets '
                    'instead of the full content.'
                ),
            ),
        ] = None,
    ) -> str:
        """Retrieve a document by URI, optionally filtering to relevant passages.

        **Without text_filter** — loads the full document (title, authors,
        abstract, content, metadata) plus its references (with titles and
        URIs) and documents that cite this one (referenced_by). Use
        reference URIs to follow the citation graph and load related papers
        for deeper research.

        **With text_filter** — runs a sparse search scoped to this single
        document and returns the best-matching snippets. Good for finding
        specific information within a long document without reading it all.

        **When to use text_filter:** Search results include a **Size**
        field (approximate token count). If a document is large (over 20K
        tokens), consider using text_filter to extract only the relevant
        passages instead of loading the entire content. For shorter
        documents, fetching the full content is fine.

        This is a cheap tool — don't hesitate to fetch documents, follow
        references, and do additional searches to build thorough context.
        """
        client = ctx.request_context.lifespan_context.search_client

        if text_filter:
            # Fetch full doc, snippets, and referenced-by in parallel
            doc, snippets_data, referenced_by_data = await asyncio.gather(
                client.get_document_by_uri(uri),
                client.get_document_by_uri(uri, text_filter=text_filter),
                client.find_referenced_by(uri, limit=30),
            )
            if doc is None:
                return 'Document not found.'
            result = format_document(doc, max_content=0)
            snippets_section = format_snippets(snippets_data)
            if snippets_section:
                result += '\n\n' + snippets_section
        else:
            # Fetch document and referenced-by docs in parallel
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
