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

from client import (
    DEFAULT_CONTENT_LENGTH,
    MAX_CONTENT_LENGTH,
    AuthenticationError,
    InsufficientFundsError,
)

logger = logging.getLogger(__name__)

# Rough token estimate exposed to agents in `content_size_tokens`. Matches the
# heuristic agents themselves use to plan whether a doc fits in context.
_CHARS_PER_TOKEN = 4
_MAX_SEARCH_ABSTRACT_LENGTH = 800
_MAX_SEARCH_SNIPPET_LENGTH = 900
_MAX_FETCH_ABSTRACT_LENGTH = 4_000
_MAX_PASSAGE_LENGTH = 2_000
_MAX_PASSAGES = 5
_MAX_AUTHORS = 16
_MAX_URIS = 12
_MAX_REFERENCES = 50
_MAX_TAGS = 25
_MAX_LANGUAGES = 12
_MAX_REFERENCED_BY = 20
_MAX_SEARCH_WINDOW = 500
_MAX_QUERY_LENGTH = 16 * 1024


# ---------------------------------------------------------------------------
# Output schemas — exposed via FastMCP-generated outputSchema/structuredContent
# ---------------------------------------------------------------------------


class DocumentResult(BaseModel):
    """One hit in a search result list. `source_uri` is the canonical URI to cite."""

    id: str = ''
    title: str
    source_uri: str = Field(
        description='Canonical URI for citation (DOI URL when available, else first http URI, else first scheme URI).',
    )
    uris: list[str] = Field(default_factory=list, description='All known URIs for this document.')
    score: float
    snippet: str | None = Field(default=None, description='Best-matching text excerpt for this query.')
    snippet_field: str | None = Field(default=None, description='Field that supplied the excerpt.')
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    issued_at: int | None = Field(default=None, description='Unix timestamp (seconds, UTC).')
    issued_date: str | None = Field(default=None, description='Human-readable date.')
    content_size_tokens: int | None = Field(default=None, description='Approximate full-text length in tokens.')
    document_type: str | None = None
    publisher: str | None = None


class SearchResults(BaseModel):
    """Top-N hits for a search query. Empty `hits` means no results in the queried index."""

    query: str
    index: Literal['documents', 'social']
    hits: list[DocumentResult]
    count: int
    total: int | None = Field(default=None, description='Total matching documents if known; null if unbounded.')
    has_more: bool
    next_offset: int | None = Field(
        default=None, description='Pass as `offset` to retrieve the next page; null if complete.'
    )


class DocumentReference(BaseModel):
    title: str | None = None
    source_uri: str | None = None
    doi: str | None = None


class FullDocument(BaseModel):
    """Full text + metadata + reference list for one document."""

    id: str = ''
    title: str
    source_uri: str
    uris: list[str] = Field(default_factory=list)
    abstract: str | None = None
    abstract_truncated: bool = False
    content: str | None = Field(
        default=None,
        description=f'Full text, capped by `max_chars` (up to {MAX_CONTENT_LENGTH:,} characters).',
    )
    content_truncated: bool = False
    full_content_length: int | None = Field(
        default=None, description='Original (untruncated) content length in characters.'
    )
    authors: list[str] = Field(default_factory=list)
    issued_at: int | None = None
    issued_date: str | None = None
    document_type: str | None = None
    publisher: str | None = None
    languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    references: list[DocumentReference] = Field(default_factory=list)
    references_truncated: bool = False
    full_reference_count: int = 0
    referenced_by: list[DocumentResult] = Field(default_factory=list)


class PassageMatch(BaseModel):
    text: str
    score: float
    field: str = Field(
        default='content',
        description='Which document field the passage came from (content, abstract, ...).',
    )
    chunk_id: int | None = Field(default=None, description='Stable chunk ordinal when available.')
    truncated: bool = False


class DocumentPassages(BaseModel):
    """Passages extracted from one document by a text query, with citation context."""

    source_uri: str
    title: str | None = None
    passages: list[PassageMatch]
    passage_count: int
    message: str | None = Field(
        default=None,
        description='Actionable guidance when no passage matched.',
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
    'Search costs $0.01 + $0.001 per returned result; document fetches cost $0.05.'
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


def _truncate(text: str, maximum: int) -> tuple[str, bool]:
    """Bound a string by Unicode characters and report whether it was shortened."""
    if len(text) <= maximum:
        return text, False
    return text[:maximum], True


def _format_authors(authors: list[Any]) -> list[str]:
    out: list[str] = []
    for author in authors[:_MAX_AUTHORS]:
        if isinstance(author, str):
            name = author.strip()
        elif isinstance(author, dict):
            name = str(author.get('name') or '').strip()
            if not name:
                given = str(author.get('given') or '').strip()
                family = str(author.get('family') or '').strip()
                name = ' '.join(part for part in (given, family) if part)
        else:
            name = ''
        if name:
            out.append(name)
    return out


def _format_date(ts: int | None) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone

    try:
        if abs(int(ts)) > 100_000_000_000:
            ts = int(ts) // 1_000
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d')
    except (ValueError, TypeError, OSError):
        return None


def _hit_to_result(item: dict[str, Any]) -> DocumentResult:
    doc = item.get('document') or {}
    uris = [str(uri) for uri in (doc.get('uris') or [])[:_MAX_URIS]]
    snippets = item.get('snippets') or []
    snippet_data = next((s for s in snippets if str(s.get('text') or '').strip()), None)
    snippet = None
    snippet_field = None
    if snippet_data:
        snippet = _truncate(str(snippet_data.get('text')).strip(), _MAX_SEARCH_SNIPPET_LENGTH)[0]
        snippet_field = str(snippet_data.get('field') or 'content')
    abstract = str(doc.get('abstract') or '').strip()
    abstract = _truncate(abstract, _MAX_SEARCH_ABSTRACT_LENGTH)[0] or None
    content_length = doc.get('content_length') or 0
    metadata = doc.get('metadata') if isinstance(doc.get('metadata'), dict) else {}
    return DocumentResult(
        id=str(item.get('id') or doc.get('id') or ''),
        title=doc.get('title') or 'Untitled',
        source_uri=_canonical_uri(uris),
        uris=uris,
        score=float(item.get('score', 0.0)),
        snippet=snippet,
        snippet_field=snippet_field,
        abstract=abstract,
        authors=_format_authors(doc.get('authors') or []),
        issued_at=doc.get('issued_at'),
        issued_date=_format_date(doc.get('issued_at')),
        content_size_tokens=(
            (int(content_length) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN if content_length else None
        ),
        document_type=doc.get('type'),
        publisher=metadata.get('publisher'),
    )


def _doc_to_full(
    data: dict[str, Any],
    referenced_by: list[DocumentResult],
    max_chars: int,
) -> FullDocument:
    doc = data.get('document') or {}
    uris = [str(uri) for uri in (data.get('uris') or doc.get('uris') or [])[:_MAX_URIS]]
    content = str(doc.get('content') or '')
    upstream_truncated = bool(doc.get('content_truncated'))
    bounded_content, locally_truncated = _truncate(content, max_chars)
    raw_abstract = str(doc.get('abstract') or '').strip()
    abstract, abstract_truncated = _truncate(raw_abstract, _MAX_FETCH_ABSTRACT_LENGTH)
    metadata = doc.get('metadata') if isinstance(doc.get('metadata'), dict) else {}
    raw_refs = doc.get('references') or []
    refs = []
    for ref in raw_refs[:_MAX_REFERENCES]:
        ref_uris = [str(uri) for uri in (ref.get('uris') or [])[:_MAX_URIS]]
        doi = ref.get('doi') or None
        refs.append(
            DocumentReference(
                title=ref.get('title'),
                source_uri=_canonical_uri(ref_uris) or (f'https://doi.org/{doi.lower()}' if doi else None),
                doi=doi,
            )
        )
    known_content_length = doc.get('content_length')
    if known_content_length is None and not upstream_truncated:
        known_content_length = len(content)
    return FullDocument(
        id=str(data.get('id') or doc.get('id') or ''),
        title=doc.get('title') or 'Untitled',
        source_uri=_canonical_uri(uris),
        uris=uris,
        abstract=abstract or None,
        abstract_truncated=abstract_truncated,
        content=bounded_content or None,
        content_truncated=upstream_truncated or locally_truncated,
        full_content_length=int(known_content_length) if known_content_length is not None else None,
        authors=_format_authors(doc.get('authors') or []),
        issued_at=doc.get('issued_at'),
        issued_date=_format_date(doc.get('issued_at')),
        document_type=doc.get('type'),
        publisher=metadata.get('publisher'),
        languages=(doc.get('languages') or [])[:_MAX_LANGUAGES],
        tags=(doc.get('tags') or [])[:_MAX_TAGS],
        references=refs,
        references_truncated=len(raw_refs) > _MAX_REFERENCES,
        full_reference_count=len(raw_refs),
        referenced_by=referenced_by,
    )


def _search_results(
    query: str,
    index: Literal['documents', 'social'],
    offset: int,
    data: dict[str, Any],
) -> SearchResults:
    hits = [_hit_to_result(item) for item in (data.get('hits') or [])]
    has_more = bool(data.get('has_next'))
    return SearchResults(
        query=query,
        index=index,
        hits=hits,
        count=len(hits),
        total=data.get('total_hits'),
        has_more=has_more,
        next_offset=(offset + len(hits)) if has_more and hits else None,
    )


def _validate_date_range(after: int | None, before: int | None) -> None:
    if after is not None and before is not None and after > before:
        raise ToolError('filter_issued_after must not be later than filter_issued_before')


def _normalize_uri(uri: str) -> str:
    """Normalize common identifiers accepted by the hosted Rust server."""
    value = uri.strip()
    lowered = value.lower()
    if lowered.startswith('https://doi.org/'):
        return f'doi://{value[len("https://doi.org/") :].lower()}'
    if lowered.startswith('http://doi.org/'):
        return f'doi://{value[len("http://doi.org/") :].lower()}'
    if lowered.startswith('doi://'):
        return f'doi://{value[len("doi://") :].lower()}'
    if lowered.startswith('doi:'):
        return f'doi://{value[len("doi:") :].strip().lower()}'
    if lowered.startswith('pmid:'):
        return f'pubmed://{value[len("pmid:") :].strip()}'
    if lowered.startswith('pubmed:'):
        return f'pubmed://{value[len("pubmed:") :].lstrip("/").strip()}'
    if lowered.startswith('arxiv:'):
        return f'arxiv://{value[len("arxiv:") :].lstrip("/").strip().lower()}'
    if lowered.startswith('isbn:'):
        return f'isbn://{value[len("isbn:") :].lstrip("/").strip()}'
    return value


def _is_social_uri(uri: str) -> bool:
    lowered = uri.lower()
    return lowered.startswith(
        (
            'telegram://',
            't.me://',
            'reddit://',
            'youtube://',
            'yt://',
            'discord://',
            'https://t.me/',
            'https://reddit.com/',
            'https://www.reddit.com/',
            'https://youtube.com/',
            'https://www.youtube.com/',
            'https://youtu.be/',
            'https://discord.com/channels/',
        )
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
            if len(non_null) == 1 and isinstance(non_null[0], dict) and isinstance(non_null[0].get('type'), str):
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
                'Number of results to return. Keep 10 for normal agent use; '
                'use 5 when issuing several parallel queries.'
            ),
            ge=1,
            le=30,
        ),
    ]
    OffsetField = Annotated[
        int,
        Field(
            description='Pagination offset. Use `next_offset` from a prior result.',
            ge=0,
            lt=_MAX_SEARCH_WINDOW,
        ),
    ]
    QueryField = Annotated[
        str,
        Field(
            description=(
                'Free-text search query. Can be empty when filters alone are enough '
                '(e.g. browse recent papers from one journal).'
            ),
            max_length=_MAX_QUERY_LENGTH,
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
        limit: LimitField = 10,
        offset: OffsetField = 0,
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
        query = query.strip()
        _validate_date_range(filter_issued_after, filter_issued_before)
        if not query and not any(
            (
                filter_issns,
                filter_types,
                filter_issued_after is not None,
                filter_issued_before is not None,
            )
        ):
            raise ToolError('query may be empty only when at least one document filter is supplied')
        if offset + limit > _MAX_SEARCH_WINDOW:
            raise ToolError(f'offset + limit must not exceed {_MAX_SEARCH_WINDOW}')
        client = ctx.request_context.lifespan_context.search_client
        data = await client.search(
            query,
            limit=limit,
            offset=offset,
            index_names=['documents'],
            filter_types=filter_types,
            filter_issns=filter_issns,
            filter_issued_after=filter_issued_after,
            filter_issued_before=filter_issued_before,
        )
        return _search_results(query, 'documents', offset, data)

    @mcp.tool(
        name='spacefrontiers_search_social',
        annotations={'title': 'Search Reddit, Telegram, YouTube', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def search_social(
        ctx: Context,
        query: QueryField = '',
        limit: LimitField = 10,
        offset: OffsetField = 0,
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
        query = query.strip()
        _validate_date_range(filter_issued_after, filter_issued_before)
        if not query and not any(
            (
                filter_uri_prefixes,
                filter_issued_after is not None,
                filter_issued_before is not None,
            )
        ):
            raise ToolError('query may be empty only when at least one social filter is supplied')
        if offset + limit > _MAX_SEARCH_WINDOW:
            raise ToolError(f'offset + limit must not exceed {_MAX_SEARCH_WINDOW}')
        client = ctx.request_context.lifespan_context.search_client
        data = await client.search(
            query,
            limit=limit,
            offset=offset,
            index_names=['social'],
            filter_uri_prefixes=filter_uri_prefixes,
            filter_issued_after=filter_issued_after,
            filter_issued_before=filter_issued_before,
        )
        return _search_results(query, 'social', offset, data)

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
                max_length=_MAX_QUERY_LENGTH,
            ),
        ],
        max_chars: Annotated[
            int,
            Field(
                description='Maximum full-text characters returned. Raise only for broad context.',
                ge=1_000,
                le=MAX_CONTENT_LENGTH,
            ),
        ] = DEFAULT_CONTENT_LENGTH,
        referenced_by_limit: Annotated[
            int,
            Field(
                description=(
                    'Citing documents to include. Zero avoids another billed search, its latency, and its payload.'
                ),
                ge=0,
                le=_MAX_REFERENCED_BY,
            ),
        ] = 0,
    ) -> FullDocument:
        """Retrieve the full text, metadata, and references of one Space Frontiers document.

        Use when: you have a `source_uri` from a search hit and need the body to quote, summarize,
        extract structured facts, or inspect its references.

        Do not use when: you have not yet found the document — call a `spacefrontiers_search_*`
        tool first to obtain a real `source_uri`. Do not guess DOIs.

        Returns title, authors, a bounded abstract and body, and up to 50 references with URIs.
        Full text defaults to 40K characters and can be raised to 100K. Citation backlinks are
        opt-in because they require another billed search. For documents over ~20K tokens prefer
        `spacefrontiers_search_in_document` to extract only the passages you need.

        Examples: `https://doi.org/10.1038/s41586-023-06924-6`, `arxiv:2301.00001`, `pmid:38019072`.
        """
        supplied_uri = uri
        uri = _normalize_uri(uri)
        client = ctx.request_context.lifespan_context.search_client
        referenced_by_data: dict[str, Any] = {'hits': []}
        if referenced_by_limit:
            doc, referenced_by_data = await asyncio.gather(
                client.get_document_by_uri(uri),
                client.find_referenced_by(uri, limit=referenced_by_limit),
            )
        else:
            doc = await client.get_document_by_uri(uri)
        if doc is None:
            raise ToolError(
                f'No document with URI {supplied_uri!r}. The DOI may not yet be in our corpus — '
                'crawls of newly cited DOIs are queued in the background; retry in a few minutes. '
                'For non-academic sources, try `spacefrontiers_search_social`.'
            )
        referenced_by = [_hit_to_result(item) for item in (referenced_by_data.get('hits') or [])]
        return _doc_to_full(doc, referenced_by, max_chars)

    @mcp.tool(
        name='spacefrontiers_search_in_document',
        annotations={'title': 'Search passages within one document', **_READ_ONLY_ANNOTATIONS},
    )
    @_handle_billing_errors
    async def search_in_document(
        ctx: Context,
        uri: Annotated[
            str,
            Field(
                description='Canonical URI of the document. Copy verbatim from a search hit; do NOT guess.',
                max_length=_MAX_QUERY_LENGTH,
            ),
        ],
        query: Annotated[
            str,
            Field(
                description='Specific evidence to locate inside this document.',
                min_length=1,
                max_length=_MAX_QUERY_LENGTH,
            ),
        ],
    ) -> DocumentPassages:
        """Find specific passages inside one Space Frontiers document without reading the whole body.

        Use when: the document is large (size > ~20K tokens shown in `content_size_tokens`)
        and you only need the parts relevant to a sub-question, e.g. "what error rates does this
        paper report?" against a 60-page review.

        Do not use when: you need the entire document to summarize or quote in full — call
        `spacefrontiers_fetch_document` instead. Do not call this without first obtaining a
        real URI via search.

        Returns no more than five passages of 2K characters each. If no passage
        matches, returns an empty list with guidance instead of unexpectedly
        injecting the whole document into the agent context.
        """
        supplied_uri = uri
        uri = _normalize_uri(uri)
        query = query.strip()
        if not query:
            raise ToolError('query must be a non-empty string')
        client = ctx.request_context.lifespan_context.search_client
        if _is_social_uri(uri):
            snippets_data = await client.search(
                query,
                limit=1,
                index_names=['social'],
                filter_uri_prefixes=[uri],
            )
        else:
            snippets_data = await client.get_document_by_uri(uri, text_filter=query)
        if snippets_data is None:
            raise ToolError(f'No document with URI {supplied_uri!r}. Confirm the URI via search first.')

        passages: list[PassageMatch] = []
        seen: set[str] = set()
        for hit in snippets_data.get('hits') or []:
            for s in hit.get('snippets') or []:
                raw_text = str(s.get('text') or '').strip()
                if not raw_text or raw_text in seen:
                    continue
                seen.add(raw_text)
                text, truncated = _truncate(raw_text, _MAX_PASSAGE_LENGTH)
                passages.append(
                    PassageMatch(
                        text=text,
                        score=float(s.get('score', 0.0)),
                        field=str(s.get('field') or 'content'),
                        chunk_id=s.get('chunk_id'),
                        truncated=truncated,
                    )
                )
                if len(passages) == _MAX_PASSAGES:
                    break
            if len(passages) == _MAX_PASSAGES:
                break

        # Resolve title + canonical URI from the first hit's document, falling back to the input URI.
        first_doc = next(((h.get('document') or {}) for h in (snippets_data.get('hits') or [])), {})
        title = first_doc.get('title')
        canonical = _canonical_uri(snippets_data.get('uris') or first_doc.get('uris') or [uri])

        return DocumentPassages(
            source_uri=canonical or uri,
            title=title,
            passages=passages,
            passage_count=len(passages),
            message=(
                None
                if passages
                else (
                    'No matching passages were found. Refine the query or use '
                    'spacefrontiers_fetch_document for broader context.'
                )
            ),
        )

    # Pydantic emits Optional fields as `{"anyOf": [<type>, {"type": "null"}]}`.
    # That's correct JSON Schema, but Smithery's UI (and some other directories)
    # render it as "unknown" instead of the underlying type. Flatten every
    # registered tool's input schema to a single concrete type per field.
    _flatten_optional_unions_on(mcp)
