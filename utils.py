import os
import time
from datetime import date, datetime, timedelta

from fastmcp import Context
from spacefrontiers.clients.types import (
    SearchResponse,
)


def process_authorization(ctx: Context) -> tuple[str | None, str | None]:
    api_key, user_id = None, None
    if not getattr(ctx.request_context, 'request', None):
        api_key = os.environ.get('SPACE_FRONTIERS_API_KEY')
    else:
        headers = ctx.request_context.request.headers
        if 'X-User-Id' in headers:
            user_id = headers['X-User-Id']
        elif 'Authorization' in headers:
            api_key = headers['Authorization'].removeprefix('Bearer').strip()
        elif 'X-Api-Key' in headers:
            api_key = headers['X-Api-Key']
        elif env_api_key := os.environ.get('SPACE_FRONTIERS_API_KEY'):
            api_key = env_api_key
    return api_key, user_id


def convert_issued_at(document: dict) -> None:
    """Convert issued_at timestamp to ISO format in-place.

    Args:
        document: Document dictionary to modify
    """
    if 'issued_at' in document:
        try:
            document['issued_at'] = datetime.fromtimestamp(document['issued_at']).isoformat()
        except (ValueError, OSError, OverflowError):
            pass


def format_search_response(search_response: SearchResponse) -> SearchResponse:
    """Format search response by converting timestamps to ISO format.

    Args:
        search_response: The search response to format

    Returns:
        The formatted search response with ISO-formatted timestamps
    """
    for search_document in search_response.search_documents:
        convert_issued_at(search_document.document)
    return search_response


def format_document_with_content(
    search_response: SearchResponse,
) -> dict | None:
    """Format a single document response with joined snippets as content.

    Args:
        search_response: The search response containing documents

    Returns:
        Dictionary with document fields and joined content, or None
    """
    if not search_response.search_documents:
        return None

    search_document = search_response.search_documents[0]
    document = search_document.document.copy()

    # Convert timestamp if present
    if 'issued_at' in document:
        try:
            document['issued_at'] = datetime.fromtimestamp(document['issued_at']).isoformat()
        except (ValueError, OSError, OverflowError):
            pass

    # Join snippets into content field
    if search_document.snippets:
        content = search_document.join_snippet_texts(separator=' <...> ')
        document['content'] = content

    document['source'] = search_document.source

    return document


def setup_date_filter(start_date, end_date, filters):
    if start_date or end_date:
        if not start_date:
            start_date = date.fromtimestamp(0)
        if not end_date:
            end_date = date.today() + timedelta(days=1)
        filters['issued_at'] = [
            (
                time.mktime(start_date.timetuple()),
                time.mktime(end_date.timetuple()),
            )
        ]


def setup_sources_filter(sources, filters):
    if sources:
        normalized_sources = [s.lower() for s in sources]
        if 'pubmed' in normalized_sources:
            filters['metadata.is_pubmed'] = [True]
            normalized_sources.remove('pubmed')
        if 'arxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('arXiv')
            normalized_sources.remove('arxiv')
        if 'biorxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('bioRxiv')
            normalized_sources.remove('biorxiv')
        if 'medrxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('medRxiv')
            normalized_sources.remove('medrxiv')
        # Remaining entries are treated as type filters
        # (e.g., 'wiki', 'standard')
        if normalized_sources:
            filters['type'] = normalized_sources


def get_source_from_uri(uri: str) -> str:
    """Determine the source from a document URI.

    Args:
        uri: Document URI (e.g., doi://..., telegram://..., reddit://...)

    Returns:
        Source name (library, telegram, reddit, youtube)
    """
    if not uri:
        return 'library'

    uri_lower = uri.lower()

    # Map URI schemes to sources
    if uri_lower.startswith(('telegram://', 't.me://')):
        return 'telegram'
    elif uri_lower.startswith('reddit://'):
        return 'reddit'
    elif uri_lower.startswith(('youtube://', 'yt://')):
        return 'youtube'
    else:
        # All academic/library URIs (doi, pubmed, arxiv, etc.)
        return 'library'
