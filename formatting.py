"""Response formatting for MCP tool output.

Converts raw v2 search API JSON into well-structured markdown.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def format_search_results(data: dict[str, Any]) -> str:
    """Format a v2 search response into markdown with snippets."""
    docs = data.get('hits') or []
    if not docs:
        return 'No results found.'

    parts = [f'# Search Results ({len(docs)} found)\n']

    for i, item in enumerate(docs, 1):
        doc = item.get('document') or {}
        score = item.get('score', 0)
        title = doc.get('title', 'Untitled')
        uris = doc.get('uris') or []
        abstract = doc.get('abstract', '')

        content_length = doc.get('content_length', 0) or 0
        display_uris = _format_uris(uris)
        parts.append(f'## {i}. {title}')
        parts.append(f'- **Score:** {score:.4f}')
        issued_at = doc.get('issued_at')
        if issued_at:
            parts.append(f'- **Issued:** {_format_timestamp(issued_at)}')
        if display_uris:
            parts.append(f'- **URIs:** {", ".join(display_uris[:3])}')
        if content_length > 0:
            parts.append(f'- **Size:** {_format_size(content_length)}')

        snippets = item.get('snippets') or []
        if snippets:
            for s in snippets:
                field = s.get('field', '')
                text = (s.get('text') or '').strip()
                s_score = s.get('score', 0)
                if text:
                    parts.append(f'\n**Snippet** ({field}, score {s_score:.4f}):\n')
                    parts.append(f'> {text}')
        elif abstract:
            parts.append(f'\n> {_truncate(abstract, 500)}')

        parts.append('')

    return '\n'.join(parts)


def format_snippets(data: dict[str, Any]) -> str:
    """Format snippet results from a text_filter search."""
    docs = data.get('hits') or []
    if not docs:
        return ''

    parts = ['## Matching Passages\n']
    for item in docs:
        for s in item.get('snippets') or []:
            field = s.get('field', '')
            text = (s.get('text') or '').strip()
            score = s.get('score', 0)
            if text:
                parts.append(f'**Snippet** ({field}, score {score:.4f}):\n')
                parts.append(f'> {text}\n')
    return '\n'.join(parts)


def format_referenced_by(data: dict[str, Any]) -> str:
    """Format citing documents as markdown list."""
    docs = data.get('hits') or []
    if not docs:
        return ''

    total = data.get('total_hits') or len(docs)
    parts = [f'## Referenced By ({total} document(s))\n']

    for item in docs:
        doc = item.get('document') or {}
        title = doc.get('title', 'Untitled')
        uris = doc.get('uris') or []

        display_uris = _format_uris(uris)
        uri_str = f' ({display_uris[0]})' if display_uris else ''
        parts.append(f'- **{title}**{uri_str}')

    return '\n'.join(parts)


def format_document(data: dict[str, Any], max_content: int = 100_000) -> str:
    """Format a full document response as structured markdown."""
    uris = data.get('uris') or []
    doc = data.get('document') or {}

    title = doc.get('title', 'Untitled')
    abstract = doc.get('abstract', '')
    content = doc.get('content', '')
    authors = doc.get('authors') or []
    issued_at = doc.get('issued_at')
    references = doc.get('references') or []
    languages = doc.get('languages') or []
    tags = doc.get('tags') or []

    parts = [f'# {title}\n']

    # Metadata block
    display_uris = _format_uris(uris)
    meta_lines = []
    if display_uris:
        meta_lines.append(f'- **URIs:** {", ".join(display_uris[:5])}')
    if authors:
        meta_lines.append(f'- **Authors:** {_format_authors(authors)}')
    if issued_at is not None:
        meta_lines.append(f'- **Issued:** {_format_timestamp(issued_at)}')
    if languages:
        meta_lines.append(f'- **Languages:** {", ".join(languages)}')
    if tags:
        meta_lines.append(f'- **Tags:** {", ".join(tags[:10])}')
    if meta_lines:
        parts.extend(meta_lines)
        parts.append('')

    if abstract:
        parts.append(f'## Abstract\n\n{abstract}\n')

    if content and max_content > 0:
        if len(content) > max_content:
            parts.append(
                f'## Content (trimmed to {max_content:,} of {len(content):,} chars)\n\n'
                f'{content[:max_content]}\n'
            )
        else:
            parts.append(f'## Content\n\n{content}\n')

    if references:
        parts.append(f'## References ({len(references)} total)\n')
        for ref in references[:30]:
            ref_title = ref.get('title', '')
            ref_uris = _format_uris(ref.get('uris') or [])
            doi = ref.get('doi', '')
            if not ref_uris and doi:
                ref_uris = [f'https://doi.org/{doi.lower()}']
            uri_str = ', '.join(ref_uris[:2])
            if uri_str and ref_title:
                parts.append(f'- **{ref_title}** ({uri_str})')
            elif ref_title:
                parts.append(f'- **{ref_title}**')
            elif uri_str:
                parts.append(f'- {uri_str}')
        parts.append('')

    return '\n'.join(parts)


def _format_uris(uris: list[str]) -> list[str]:
    """Return deduplicated URIs. Prefer HTTP doi.org URLs, fall back to scheme URIs."""
    deduped = list(dict.fromkeys(uris))
    http = [u for u in deduped if u.startswith(('http://', 'https://'))]
    doi_urls = [u for u in http if 'doi.org/' in u]
    return doi_urls if doi_urls else (http if http else deduped)


def _format_authors(authors: list[dict[str, Any]]) -> str:
    names = []
    for a in authors[:10]:
        if 'name' in a:
            names.append(a['name'])
        elif 'family' in a:
            given = a.get('given', '')
            names.append(f'{a["family"]}, {given}' if given else a['family'])
    suffix = f' (+{len(authors) - 10} more)' if len(authors) > 10 else ''
    return '; '.join(names) + suffix


def _format_size(chars: int) -> str:
    """Format content size as approximate token count (1 token ~ 4 chars)."""
    tokens = chars // 4
    if tokens < 1000:
        return f'~{tokens} tokens'
    return f'~{tokens // 1000}K tokens'


def _format_timestamp(value) -> str:
    try:
        dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
        return dt.strftime('%B %d, %Y')
    except (ValueError, TypeError, OSError):
        return str(value)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + '...'
