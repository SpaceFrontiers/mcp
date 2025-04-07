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


def format_search_response(search_response: SearchResponse) -> SearchResponse:
    for search_document in search_response.search_documents:
        if 'issued_at' in search_document.document:
            search_document.document['issued_at'] = datetime.fromtimestamp(
                search_document.document['issued_at']
            ).isoformat()
    return search_response


def setup_date_filter(start_date, end_date, filters):
    if start_date or end_date:
        if not start_date:
            start_date = date.fromtimestamp(0)
        if not end_date:
            end_date = date.today() + timedelta(days=1)
        filters['issued_at'] = [(time.mktime(start_date.timetuple()), time.mktime(end_date.timetuple()))]


def setup_sources_filter(sources, filters):
    if sources:
        normalized_sources = [s.lower() for s in sources]
        remaining_types: list[str] = []
        if 'pubmed' in normalized_sources:
            filters['metadata.is_pubmed'] = [True]
            normalized_sources.remove('pubmed')
        if 'arxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('arxiv')
            normalized_sources.remove('arxiv')
        if 'biorxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('biorxiv')
            normalized_sources.remove('biorxiv')
        if 'medrxiv' in normalized_sources:
            filters.setdefault('metadata.publisher', []).append('medrxiv')
            normalized_sources.remove('medrxiv')
        # Any remaining entries are treated as type filters (e.g., 'wiki', 'standard')
        if normalized_sources:
            remaining_types.extend(normalized_sources)
        if remaining_types:
            filters['type'] = remaining_types
