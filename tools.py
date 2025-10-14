from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from izihawa_loglib.request_context import RequestContext
from pydantic import Field
from spacefrontiers.clients.types import SearchRequest, SearchResponse

from utils import (
    convert_issued_at,
    format_document_with_content,
    format_search_response,
    get_source_from_uri,
    process_authorization,
    setup_sources_filter,
)


def setup_tools(mcp: FastMCP):
    @mcp.tool(annotations={'title': 'Search for documents'})
    async def search(
        ctx: Context,
        query: Annotated[str, Field(description='Free-text search query')],
        source: Annotated[
            Literal[
                'wiki',
                'pubmed',
                'arxiv',
                'biorxiv',
                'medrxiv',
                'standard',
                'telegram',
                'reddit',
                'youtube',
            ] | None,
            Field(
                description=(
                    'Source to search in (wiki, pubmed, arxiv, biorxiv, '
                    'medrxiv, standard, telegram, reddit, youtube). '
                    'If not specified, searches in default sources.'
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(description='Number of results to return', ge=1, le=100),
        ] = 20,
    ) -> SearchResponse:
        """
        Search across multiple sources and return top N documents.

        This is the primary search tool that performs semantic search
        across various data sources including academic papers, Wikipedia,
        social media, and more. Each result includes:
        - Document ID and metadata (title, authors, abstract, etc.)
        - Relevant snippets from the document
        - Relevance scores

        Supported sources:
        - wiki: Wikipedia articles
        - pubmed: PubMed medical literature
        - arxiv: ArXiv preprints
        - biorxiv: BioRxiv preprints
        - medrxiv: MedRxiv preprints
        - standard: Other academic papers and documents
        - telegram: Telegram posts and messages
        - reddit: Reddit posts and discussions
        - youtube: YouTube videos and transcripts

        Args:
            query: Free-text search query
            sources: List of sources to search, or None to search all
            limit: Maximum number of results to return (default: 20)

        Returns:
            SearchResponse containing:
            - search_documents: List of documents with snippets, IDs
            - count: Total number of matching documents
            - has_next: Whether there are more results available
        """
        api_key, user_id = process_authorization(ctx)

        # Build sources filters using utility function
        sources_filters = {}
        if source:
            library_filters = {}
            setup_sources_filter([source], library_filters)
            if library_filters:
                sources_filters['library'] = library_filters
            if 'telegram' == source:
                sources_filters['telegram'] = {}
            if 'reddit' == source:
                sources_filters['reddit'] = {}
            if 'youtube' == source:
                sources_filters['youtube'] = {}

        search_response = await (
            ctx.request_context.lifespan_context.search_api_client.search(
                SearchRequest(
                    query=query,
                    sources_filters=sources_filters,
                    limit=limit,
                    mode="or",
                ),
                api_key=api_key,
                user_id=user_id,
                request_context=RequestContext(request_source='mcp'),
            )
        )

        return format_search_response(search_response)

    @mcp.tool(annotations={'title': 'Resolve document identifiers to URIs'})
    async def resolve_id(
        ctx: Context,
        text: Annotated[
            str,
            Field(
                description=(
                    'Text containing identifiers to resolve '
                    '(DOIs, ISBNs, PubMed IDs, URLs, etc.)'
                )
            ),
        ],
        find_all: Annotated[
            bool,
            Field(
                description='Find all possible matches or just the best one'
            ),
        ] = False,
    ) -> dict:
        """
        Resolve textual identifiers into document URIs and sources.

        This tool takes text that may contain various types of document
        identifiers and converts them into standardized URIs with their
        corresponding source names. Use the returned source in get_document.

        Supported identifier types:
        - DOI (Digital Object Identifier): e.g.,
          "10.1000/xyz123" -> "doi://10.1000/xyz123" (source: library)
        - ISBN (International Standard Book Number) (source: library)
        - PubMed IDs: e.g.,
          "PMID:12345678" -> "pubmed://12345678" (source: library)
        - ArXiv IDs: e.g.,
          "arXiv:2301.00001" -> "arxiv://2301.00001" (source: library)
        - Telegram usernames and links (source: telegram)
        - Reddit subreddits (source: reddit)
        - YouTube links (source: youtube)
        - GOST standards, URLs, and more...

        Args:
            text: Text containing one or more identifiers to resolve
            find_all: If True, return all matches found

        Returns:
            Dictionary containing:
            - success: Whether any matches were found
            - matches: List of resolved identifiers with:
                - id_type: Type of identifier (e.g., "doi", "pubmed")
                - original_text: The input text
                - resolved_uri: The standardized URI
                - source: Source name (library, telegram, reddit, youtube)
                - value: The extracted identifier value
                - confidence: Confidence score (0-1)
                - metadata: Additional information about the match
        """
        api_key, user_id = process_authorization(ctx)

        response = await (
            ctx.request_context.lifespan_context.search_api_client.resolve_id(
                {
                    'text': text,
                    'find_all': find_all,
                },
                api_key=api_key,
                user_id=user_id,
                request_context=RequestContext(request_source='mcp'),
            )
        )

        # Add source information to each match
        if response.get('matches'):
            for match in response['matches']:
                match['source'] = get_source_from_uri(
                    match.get('resolved_uri', '')
                )

        return response

    @mcp.tool(annotations={'title': 'Get a document by URI'})
    async def get_document(
        ctx: Context,
        document_uri: Annotated[
            str,
            Field(
                description=(
                    'Document URI (e.g., doi://10.1000/123, '
                    'pubmed://12345) to retrieve'
                )
            ),
        ],
        query: Annotated[
            str,
            Field(
                description=(
                    'Query to filter content within the document. '
                    'This determines which parts of the document are '
                    'returned as snippets.'
                )
            ),
        ],
        source: Annotated[
            Literal['library', 'telegram', 'reddit', 'youtube'] | None,
            Field(
                description=(
                    'Source to retrieve from (obtained from resolve_id). '
                    'If not provided, auto-detected from URI.'
                )
            ),
        ] = None,
    ) -> dict:
        """
        Retrieve a single document by its URI with content filtering.

        This tool retrieves a specific document by its URI (obtained from
        resolve_id tool) and filters its content based on the query.
        The returned document includes all metadata fields and a 'content'
        field with joined snippets matching the query.

        The query is required and determines which parts of the
        document are returned. This is useful for:
        - Large documents: Get only relevant sections
        - Focused information: Extract specific topics or concepts
        - Efficient retrieval: Avoid returning entire lengthy documents

        Args:
            document_uri: Document URI to retrieve (required).
                Obtain from resolve_id tool.
            query: Query to filter content within the document
                (required). Returns only snippets matching this query.
            source: Source name (library, telegram, reddit, youtube).
                Use the source returned by resolve_id. If not provided,
                it will be auto-detected from the URI.

        Returns:
            Dictionary containing:
            - id: Document ID
            - title: Document title
            - authors: List of authors
            - abstract: Document abstract
            - content: Joined snippets matching the query
            - metadata: Additional document metadata
            - issued_at: Publication date (ISO format)
            - type: Document type
            - tags: Document tags
            - languages: Document languages
            - references: Document references
            - source: Source of the document
        """
        api_key, user_id = process_authorization(ctx)

        # Auto-detect source from URI if not provided
        if not source:
            source = get_source_from_uri(document_uri)

        client = ctx.request_context.lifespan_context.search_api_client

        # Always use regular search to filter content within the document
        sources_filters = {source: {'uris': [document_uri]}}

        search_response = await client.search(
            SearchRequest(
                query=query,
                sources_filters=sources_filters,
                limit=1,
            ),
            api_key=api_key,
            user_id=user_id,
            request_context=RequestContext(request_source='mcp'),
        )

        # Format the document with joined snippets as content
        document = format_document_with_content(search_response)

        if not document:
            return {'error': 'Document not found'}

        return document

    @mcp.tool(annotations={'title': 'Get document metadata only'})
    async def get_document_metadata(
        ctx: Context,
        document_uri: Annotated[
            str,
            Field(
                description=(
                    'Document URI (e.g., doi://10.1000/123, '
                    'pubmed://12345) to retrieve'
                )
            ),
        ],
    ) -> dict:
        """
        Quickly retrieve only metadata for a document (no content).

        This is a fast tool for retrieving basic document information
        without performing content search. Use this when you only need
        metadata like title, authors, abstract, and references, and
        don't need the actual document content.

        This tool is much faster than get_document because it:
        - Does not perform semantic search
        - Does not retrieve or process snippets
        - Returns only essential metadata fields

        Args:
            document_uri: Document URI to retrieve (required).
                Obtain from resolve_id tool.

        Returns:
            Dictionary containing:
            - id: Document ID
            - title: Document title
            - authors: List of authors
            - abstract: Document abstract
            - references: Document references
            - metadata: Additional document metadata
            - issued_at: Publication date (ISO format)
            - type: Document type
            - source: Source of the document
        """
        api_key, user_id = process_authorization(ctx)

        source = get_source_from_uri(document_uri)

        # Metadata fields only (no content, no snippets)
        fields = [
            'id',
            'title',
            'authors',
            'abstract',
            'references',
            'metadata',
            'issued_at',
            'type',
        ]

        client = ctx.request_context.lifespan_context.search_api_client

        # Direct retrieval without search - fast metadata-only fetch
        search_response = await client.documents_search(
            {
                'query': None,
                'source': source,
                'filters': {'uris': [document_uri]},
                'fields': fields,
                'limit': 1,
            },
            api_key=api_key,
            user_id=user_id,
            request_context=RequestContext(request_source='mcp'),
        )

        if not search_response.search_documents:
            return {'error': 'Document not found'}

        search_document = search_response.search_documents[0]
        document = search_document.document.copy()

        # Convert timestamp if present using shared utility
        convert_issued_at(document)

        document['source'] = search_document.source

        return document
