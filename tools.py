"""MCP tools for Space Frontiers full-text retrieval.

Four tools, all read-only, all idempotent, all `spacefrontiers_*` namespaced
to avoid collisions when multiple MCP servers are mounted in one agent:

- spacefrontiers_search_documents   — search papers, books, patents, Wikipedia
- spacefrontiers_search_social      — search Reddit, Telegram, YouTube
- spacefrontiers_fetch_document     — full text + references for one URI
- spacefrontiers_search_in_document — passages within one document by query

Every tool declares an `outputSchema` (via Pydantic return models) so calling
LLMs can parse results structurally and cite by `source_uri` without parsing
free-form prose.
"""

import asyncio
import functools
import logging
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from client import MAX_CONTENT_LENGTH, AuthenticationError, InsufficientFundsError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schemas — exposed via FastMCP-generated outputSchema/structuredContent
# ---------------------------------------------------------------------------


class DocumentResult(BaseModel):
    """One hit in a search result list. `source_uri` is the canonical URI to cite."""

    title: str
    source_uri: str = Field(
        description='Canonical URI for citation (DOI URL when available, else first http URI, else first scheme URI).',
    )
    uris: list[str] = Field(default_factory=list, description='All known URIs for this document.')
    score: float
    snippet: str | None = Field(default=None, description='Best-matching text excerpt for this query.')
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    issued_at: int | None = Field(default=None, description='Unix timestamp (seconds, UTC).')
    issued_date: str | None = Field(default=None, description='Human-readable date.')
    content_size_tokens: int | None = Field(
        default=None, description='Approximate full-text length in tokens.'
    )
    document_type: str | None = None


class SearchResults(BaseModel):
    """Top-N hits for a search query. Empty `hits` means no results in the queried index."""

    query: str
    index: Literal['documents', 'social']
    hits: list[DocumentResult]
    total: int | None = Field(
        default=None, description='Total matching documents if known; null if unbounded.'
    )
    next_cursor: str | None = Field(
        default=None, description='Opaque cursor for the next page; null if no more results.'
    )


class DocumentReference(BaseModel):
    title: str | None = None
    source_uri: str | None = None
    doi: str | None = None


class FullDocument(BaseModel):
    """Full text + metadata + reference list for one document."""

    title: str
    source_uri: str
    uris: list[str] = Field(default_factory=list)
    abstract: str | None = None
    content: str | None = Field(
        default=None,
        description=f'Full text, truncated to ~{MAX_CONTENT_LENGTH:,} characters when longer.',
    )
    content_truncated: bool = False
    full_content_length: int | None = Field(
        default=None, description='Original (untruncated) content length in characters.'
    )
    authors: list[str] = Field(default_factory=list)
    issued_at: int | None = None
    issued_date: str | None = None
    languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    references: list[DocumentReference] = Field(default_factory=list)
    referenced_by: list[DocumentResult] = Field(default_factory=list)


class PassageMatch(BaseModel):
    text: str
    score: float
    field: str | None = Field(
        default=None,
        description='Which document field the passage came from (content, abstract, ...).',
    )


class DocumentPassages(BaseModel):
    """Passages extracted from one document by a text query, with citation context."""

    source_uri: str
    title: str | None = None
    passages: list[PassageMatch]
    referenced_by: list[DocumentResult] = Field(default_factory=list)
    fallback_full_document: FullDocument | None = Field(
        default=None,
        description='If no passages matched, the full document is returned here as a fallback.',
    )


# ---------------------------------------------------------------------------
# Error handling — raise FastMCP's ToolError on billing/auth failures so the
# response carries `isError: true` per the MCP spec, with a single concrete
# `outputSchema` for the success path (Smithery + similar UIs render this
# cleanly; older "structured error envelope as a union arm" approach broke
# their schema rendering).
# ---------------------------------------------------------------------------


_INSUFFICIENT_FUNDS_MSG = (
    'Insufficient funds. Your Space Frontiers balance is too low for this request. '
    'Top up at https://spacefrontiers.org/payments?amount=10. '
    'Searches cost ~$0.005, fetches ~$0.005 — $10 buys ~2,000 calls.'
)

_AUTH_ERROR_MSG = (
    'Authentication failed. Your API key may be invalid or expired. '
    'Get a new key at https://spacefrontiers.org/keys and update your MCP config.'
)


def _handle_billing_errors(fn):
    """Translate billing/auth client exceptions to MCP `isError: true` results."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except InsufficientFundsError as exc:
            raise ToolError(_INSUFFICIENT_FUNDS_MSG) from exc
        except AuthenticationError as exc:
            raise ToolError(_AUTH_ERROR_MSG) from exc

    return wrapper


# ---------------------------------------------------------------------------
# Conversion helpers (raw search-api JSON → typed Pydantic models)
# ---------------------------------------------------------------------------


def _canonical_uri(uris: list[str]) -> str:
    """Pick the best URI for citation: prefer doi.org URL, then any http(s), then scheme URI."""
    for u in uris:
        if 'doi.org/' in u:
            return u
    for u in uris:
        if u.startswith(('http://', 'https://')):
            return u
    return uris[0] if uris else ''


def _format_authors(authors: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for a in authors[:25]:
        if 'name' in a:
            out.append(a['name'])
        elif 'family' in a:
            given = a.get('given', '')
            out.append(f'{a["family"]}, {given}' if given else a['family'])
    return out


def _format_date(ts: int | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d')
    except (ValueError, TypeError, OSError):
        return None


def _hit_to_result(item: dict[str, Any]) -> DocumentResult:
    doc = item.get('document') or {}
    uris = doc.get('uris') or []
    snippets = item.get('snippets') or []
    snippet = next((s.get('text', '').strip() for s in snippets if s.get('text')), None)
    content_length = doc.get('content_length') or 0
    return DocumentResult(
        title=doc.get('title') or 'Untitled',
        source_uri=_canonical_uri(uris),
        uris=uris,
        score=float(item.get('score', 0.0)),
        snippet=snippet,
        abstract=doc.get('abstract'),
        authors=_format_authors(doc.get('authors') or []),
        issued_at=doc.get('issued_at'),
        issued_date=_format_date(doc.get('issued_at')),
        content_size_tokens=(content_length // 4) if content_length else None,
        document_type=doc.get('type'),
    )


def _doc_to_full(data: dict[str, Any], referenced_by: list[DocumentResult]) -> FullDocument:
    uris = data.get('uris') or []
    doc = data.get('document') or {}
    content = doc.get('content') or ''
    truncated = len(content) > MAX_CONTENT_LENGTH
    refs = []
    for ref in (doc.get('references') or [])[:100]:
        ref_uris = ref.get('uris') or []
        doi = ref.get('doi') or None
        refs.append(DocumentReference(
            title=ref.get('title'),
            source_uri=_canonical_uri(ref_uris) or (f'https://doi.org/{doi.lower()}' if doi else None),
            doi=doi,
        ))
    return FullDocument(
        title=doc.get('title') or 'Untitled',
        source_uri=_canonical_uri(uris),
        uris=uris,
        abstract=doc.get('abstract'),
        content=content[:MAX_CONTENT_LENGTH] if content else None,
        content_truncated=truncated,
        full_content_length=len(content) if content else None,
        authors=_format_authors(doc.get('authors') or []),
        issued_at=doc.get('issued_at'),
        issued_date=_format_date(doc.get('issued_at')),
        languages=doc.get('languages') or [],
        tags=(doc.get('tags') or [])[:25],
        references=refs,
        referenced_by=referenced_by,
    )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

# Annotations applied to every tool — all four are read-only and idempotent.
_READ_ONLY_ANNOTATIONS: dict[str, Any] = {
    'readOnlyHint': True,
    'idempotentHint': True,
    'openWorldHint': True,
    'destructiveHint': False,
}


def _flatten_optional_unions(schema: Any) -> Any:
    """Rewrite `{anyOf: [X, {type: null}]}` to X recursively.

    Pydantic emits `Optional[T]` as a two-arm `anyOf` with the second arm being
    `{"type": "null"}`. JSON Schema clients should accept that, but Smithery and
    a few other directory UIs render it as "unknown". Rewrite the same shape as
    a JSON Schema multi-type array (`{"type": ["X", "null"]}`) which is the
    canonical compact form per Draft 2020-12 and keeps `null` legal — runtime
    code still returns `None` for empty optional fields, so dropping `null`
    from the schema would break output validation in spec-strict clients.
    """
    if isinstance(schema, dict):
        any_of = schema.get('anyOf')
        if isinstance(any_of, list) and len(any_of) == 2:
            non_null = [s for s in any_of if s != {'type': 'null'}]
            if (
                len(non_null) == 1
                and isinstance(non_null[0], dict)
                and isinstance(non_null[0].get('type'), str)
            ):
                merged = {k: v for k, v in schema.items() if k != 'anyOf'}
                # Merge sibling fields from the non-null arm (items, enum, etc.)
                # but rewrite `type` as a [<X>, "null"] tuple so null stays
                # a valid value at validation time.
                arm = non_null[0]
                arm_type = arm['type']
                merged.update({k: v for k, v in arm.items() if k != 'type'})
                merged['type'] = [arm_type, 'null']
                return _flatten_optional_unions(merged)
        return {k: _flatten_optional_unions(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_flatten_optional_unions(item) for item in schema]
    return schema


def _flatten_optional_unions_on(mcp: FastMCP) -> None:
    """Apply `_flatten_optional_unions` to every registered tool's input + output schema.

    FastMCP 3.x stores components on `mcp.local_provider._components`; the older
    `_tool_manager._tools` attribute was removed when the provider abstraction
    landed.
    """
    from fastmcp.tools.tool import Tool as _FastMCPTool
    for component in mcp.local_provider._components.values():
        if not isinstance(component, _FastMCPTool):
            continue
        if component.parameters:
            component.parameters = _flatten_optional_unions(component.parameters)
        if getattr(component, 'output_schema', None):
            component.output_schema = _flatten_optional_unions(component.output_schema)


def setup_tools(mcp: FastMCP):
    # ----- shared filter parameter types -----
    LimitField = Annotated[
        int,
        Field(
            description=(
                'Number of results to return. Use 20-30 for broad coverage on a single query; '
                'smaller (5-10) when running many parallel queries.'
            ),
            ge=1,
            le=100,
        ),
    ]
    QueryField = Annotated[
        str,
        Field(
            description=(
                'Free-text search query. Can be empty when filters alone are enough '
                '(e.g. browse recent papers from one journal).'
            ),
        ),
    ]
    IssuedAfter = Annotated[
        int | None,
        Field(
            description=(
                'Only return documents published after this Unix timestamp (seconds, UTC). '
                'For "last 7 days" use `now - 604800`.'
            ),
        ),
    ]
    IssuedBefore = Annotated[
        int | None,
        Field(
            description='Only return documents published before this Unix timestamp (seconds, UTC).',
        ),
    ]

    @mcp.tool(
        name='spacefrontiers_search_documents',
        annotations={'title': 'Search papers, books, patents, Wikipedia', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def search_documents(
        ctx: Context,
        query: QueryField = '',
        limit: LimitField = 30,
        filter_issns: Annotated[
            list[str] | None,
            Field(
                description=(
                    'Filter by journal ISSN. Accepts hyphenated ("0028-0836") or plain ("00280836"). '
                    'Pair with empty `query` to browse a journal.'
                ),
            ),
        ] = None,
        filter_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    'Filter by CrossRef-style document type. Examples: "journal-article", "book", '
                    '"book-chapter", "proceedings-article", "posted-content" (preprints), "patent".'
                ),
            ),
        ] = None,
        filter_issued_after: IssuedAfter = None,
        filter_issued_before: IssuedBefore = None,
    ) -> SearchResults:
        """Search peer-reviewed papers, books, patents, and Wikipedia in the Space Frontiers `documents` index.

        Use when: the user asks about scientific concepts, technical methods, prior art, citations,
        a DOI / ISBN / arXiv ID / PubMed ID, or wants peer-reviewed sources.

        Do not use when: the question is about news, current events, ongoing discussions, or social
        sentiment — call `spacefrontiers_search_social` instead. For general web pages or code,
        use a different MCP server.

        Examples: "crispr base editing efficiency", "doi:10.1038/s41586-023-06924-6",
        "isbn:9780262033848", "arxiv:2301.00001", "transformer attention scaling laws".

        Tips:
        - Run 2-6 parallel queries with varied phrasings (synonyms, narrower/broader terms).
        - Pass an empty `query` plus `filter_issns` to browse recent issues of a specific journal.
        - Use the returned `source_uri` verbatim with `spacefrontiers_fetch_document` for full text.
        """
        client = ctx.request_context.lifespan_context.search_client
        data = await client.search(
            query,
            limit=limit,
            index_names=['documents'],
            filter_types=filter_types,
            filter_issns=filter_issns,
            filter_issued_after=filter_issued_after,
            filter_issued_before=filter_issued_before,
        )
        hits = [_hit_to_result(item) for item in (data.get('hits') or [])]
        return SearchResults(
            query=query,
            index='documents',
            hits=hits,
            total=data.get('total_hits'),
            next_cursor=data.get('next_cursor'),
        )

    @mcp.tool(
        name='spacefrontiers_search_social',
        annotations={'title': 'Search Reddit, Telegram, YouTube', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def search_social(
        ctx: Context,
        query: QueryField = '',
        limit: LimitField = 30,
        filter_uri_prefixes: Annotated[
            list[str] | None,
            Field(
                description=(
                    'Restrict to one or more sources by URI prefix. Examples: '
                    '`["https://reddit.com/r/MachineLearning/"]` for one subreddit (case-sensitive), '
                    '`["@channel_username"]` for one Telegram channel (the @ prefix is resolved automatically).'
                ),
            ),
        ] = None,
        filter_issued_after: IssuedAfter = None,
        filter_issued_before: IssuedBefore = None,
    ) -> SearchResults:
        """Search Reddit, Telegram channels, and YouTube transcripts in the Space Frontiers `social` index.

        Use when: the user asks about news, recent events, announcements, ongoing discussions,
        community opinions, or anything time-sensitive that wouldn't be in peer-reviewed literature.

        Do not use when: the question is about settled scientific knowledge, citations, or prior art —
        call `spacefrontiers_search_documents` instead. For general web search, use a different
        MCP server.

        Examples: "openai gpt-5 release date", "site:reddit.com/r/LocalLLaMA quantization",
        "@telegram_channel breaking news", "kubernetes 1.33 changes discussion".

        Tips:
        - Pair an empty `query` with `filter_uri_prefixes` to browse a subreddit or Telegram channel
          chronologically (combine with `filter_issued_after` for a time window).
        - For broad topics, also call `spacefrontiers_search_documents` in parallel for grounded sources.
        """
        client = ctx.request_context.lifespan_context.search_client
        data = await client.search(
            query,
            limit=limit,
            index_names=['social'],
            filter_uri_prefixes=filter_uri_prefixes,
            filter_issued_after=filter_issued_after,
            filter_issued_before=filter_issued_before,
        )
        hits = [_hit_to_result(item) for item in (data.get('hits') or [])]
        return SearchResults(
            query=query,
            index='social',
            hits=hits,
            total=data.get('total_hits'),
            next_cursor=data.get('next_cursor'),
        )

    @mcp.tool(
        name='spacefrontiers_fetch_document',
        annotations={'title': 'Fetch full document by URI', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def fetch_document(
        ctx: Context,
        uri: Annotated[
            str,
            Field(
                description=(
                    'Canonical URI of the document to fetch. Copy verbatim from a `source_uri` field '
                    'in a previous search result, or supply a known identifier in one of these schemes: '
                    '`doi:10.…`, `https://doi.org/10.…`, `arxiv:2301.00001`, `pmid:12345678`, '
                    '`isbn:9780262033848`. Do NOT compose or guess URIs.'
                ),
                examples=[
                    'https://doi.org/10.1038/s41586-023-06924-6',
                    'arxiv:2301.00001',
                    'pmid:38019072',
                    'isbn:9780262033848',
                ],
            ),
        ],
    ) -> FullDocument:
        """Retrieve the full text, metadata, and references of one Space Frontiers document.

        Use when: you have a `source_uri` from a search hit and need the body to quote, summarize,
        or extract structured facts; or you want to walk the citation graph via `references`
        and `referenced_by`.

        Do not use when: you have not yet found the document — call a `spacefrontiers_search_*`
        tool first to obtain a real `source_uri`. Do not guess DOIs.

        Returns title, authors, abstract, content (truncated above ~100K chars), references with URIs,
        and up to 30 `referenced_by` documents you can fetch next. For documents over ~20K tokens
        prefer `spacefrontiers_search_in_document` to extract only the passages you need.

        Examples: `https://doi.org/10.1038/s41586-023-06924-6`, `arxiv:2301.00001`, `pmid:38019072`.
        """
        client = ctx.request_context.lifespan_context.search_client
        doc, referenced_by_data = await asyncio.gather(
            client.get_document_by_uri(uri),
            client.find_referenced_by(uri, limit=30),
        )
        if doc is None:
            raise ToolError(
                f'No document with URI {uri!r}. The DOI may not yet be in our corpus — '
                'crawls of newly cited DOIs are queued in the background; retry in a few minutes. '
                'For non-academic sources, try `spacefrontiers_search_social`.'
            )
        referenced_by = [_hit_to_result(item) for item in (referenced_by_data.get('hits') or [])]
        return _doc_to_full(doc, referenced_by)

    @mcp.tool(
        name='spacefrontiers_search_in_document',
        annotations={'title': 'Search passages within one document', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def search_in_document(
        ctx: Context,
        uri: Annotated[
            str,
            Field(description='Canonical URI of the document. Copy verbatim from a search hit; do NOT guess.'),
        ],
        query: Annotated[
            str,
            Field(description='Text query for the passages you want to find inside this document.'),
        ],
    ) -> DocumentPassages:
        """Find specific passages inside one Space Frontiers document without reading the whole body.

        Use when: the document is large (size > ~20K tokens shown in `content_size_tokens`)
        and you only need the parts relevant to a sub-question, e.g. "what error rates does this
        paper report?" against a 60-page review.

        Do not use when: you need the entire document to summarize or quote in full — call
        `spacefrontiers_fetch_document` instead. Do not call this without first obtaining a
        real URI via search.

        If no passage matches the query, the full document is returned in `fallback_full_document`
        so the caller never has to retry with a second tool call.
        """
        client = ctx.request_context.lifespan_context.search_client
        snippets_data, referenced_by_data = await asyncio.gather(
            client.get_document_by_uri(uri, text_filter=query),
            client.find_referenced_by(uri, limit=30),
        )
        if snippets_data is None:
            raise ToolError(
                f'No document with URI {uri!r}. Confirm the URI via search first.'
            )

        passages: list[PassageMatch] = []
        for hit in (snippets_data.get('hits') or []):
            for s in hit.get('snippets') or []:
                text = (s.get('text') or '').strip()
                if text:
                    passages.append(PassageMatch(
                        text=text,
                        score=float(s.get('score', 0.0)),
                        field=s.get('field'),
                    ))

        referenced_by = [_hit_to_result(item) for item in (referenced_by_data.get('hits') or [])]

        # Resolve title + canonical URI from the first hit's document, falling back to the input URI.
        first_doc = next(((h.get('document') or {}) for h in (snippets_data.get('hits') or [])), {})
        title = first_doc.get('title')
        canonical = _canonical_uri(snippets_data.get('uris') or first_doc.get('uris') or [uri])

        fallback: FullDocument | None = None
        if not passages:
            full = await client.get_document_by_uri(uri)
            if full is not None:
                fallback = _doc_to_full(full, referenced_by)

        return DocumentPassages(
            source_uri=canonical or uri,
            title=title,
            passages=passages,
            referenced_by=referenced_by,
            fallback_full_document=fallback,
        )

    # Pydantic emits Optional fields as `{"anyOf": [<type>, {"type": "null"}]}`.
    # That's correct JSON Schema, but Smithery's UI (and some other directories)
    # render it as "unknown" instead of the underlying type. Flatten every
    # registered tool's input schema to a single concrete type per field.
    _flatten_optional_unions_on(mcp)
