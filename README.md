# Space Frontiers MCP Server

## General Overview

This project implements a Model Context Protocol (MCP) server that acts as an interface to the Space Frontiers API. It allows language models to interact with Space Frontiers data sources through MCP tools. The server is built using the FastMCP library.

The server provides 4 core tools for LLM-accessible search and discovery across Space Frontiers sources:

1. **search** - Perform semantic search across multiple sources (scholarly literature, Wikipedia, Telegram, Reddit, YouTube, etc.)
2. **resolve_id** - Convert document identifiers (DOIs, ISBNs, PubMed IDs, URLs, etc.) into standardized URIs with source information
3. **get_document** - Retrieve a single document by URI with content filtering via search query (always returns filtered snippets)
4. **get_document_metadata** - Fast retrieval of document metadata only (title, authors, abstract, references) without content search

## Recommended Usage Pattern

The typical workflow for using these tools follows this pattern:

1. **search** - Find relevant documents using a search query. This returns document IDs and snippets.
2. **resolve_id** - If you have a document identifier (DOI, ISBN, URL, etc.), convert it to a URI and source name.
3. **get_document_metadata** - Quickly get basic metadata (title, authors, abstract, references) without searching content. Fast and efficient.
4. **get_document** - Retrieve filtered content from a specific document using its URI and a search query. Always returns only relevant snippets matching the query.

Example workflow:
```
User: "Find papers about CRISPR gene editing"
→ Use search("CRISPR gene editing") to get relevant papers

→ If a specific DOI is mentioned (e.g., "10.1038/nature12345"):
  resolve_id("10.1038/nature12345")
  Returns: {
    "success": true,
    "matches": [{
      "resolved_uri": "doi://10.1038/nature12345",
      "source": "library",
      ...
    }]
  }

→ Get metadata only (fast, no content search):
  get_document_metadata(
    document_uri="doi://10.1038/nature12345",
    source="library"
  )
  Returns: title, authors, abstract, references

→ Get filtered content from the document (query is required):
  get_document(
    document_uri="doi://10.1038/nature12345",
    source="library",
    query="off-target effects"
  )
  Returns only the snippets relevant to "off-target effects"

→ For broader content, use a more general query:
  get_document(
    document_uri="doi://10.1038/nature12345",
    source="library",
    query="CRISPR methods results"
  )
  Returns snippets about methods and results
```

Tools are self-describing via MCP schemas and annotations; your MCP client can list and introspect them at runtime.

**Hosted option:** Space Frontiers provides a publicly hosted MCP server at `https://mcp.spacefrontiers.org`. Obtain an API key from `https://spacefrontiers.org/developers/keys` and include it via the `Authorization: Bearer <your_api_key>` header.

## Environment Variables

The server utilizes the following environment variables:

*   `SPACE_FRONTIERS_API_ENDPOINT`: The base URL for the Space Frontiers API.
    *   **Default:** `https://api.spacefrontiers.org`
*   `SPACE_FRONTIERS_API_KEY`: An optional API key for authenticating requests to the Space Frontiers API.
    *   **Note:** Authentication can also be provided via request headers:
        *   `Authorization: Bearer <your_api_key>`
        *   `X-Api-Key: <your_api_key>`
        *   Alternatively, a user ID can be provided via the `X-User-Id` header. If none of these are provided, the server will attempt to use the `SPACE_FRONTIERS_API_KEY` environment variable if set.
        *   **Note on `X-User-Id`:** This header is intended for Space Frontiers internal usage only and cannot be exploited for external authentication.

## Running the Server

```bash
uv run fastmcp run mcp_server.py
```

Ensure `SPACE_FRONTIERS_API_KEY` is set in the environment if your client does not pass authentication headers.

### Example Claude Desktop App Configuration (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "Space Frontiers MCP server": {
      "command": "/path/to/your/uv",
      "args": [
        "run",
        "fastmcp",
        "run",
        "--with",
        "izihawa-loglib",
        "--with",
        "mcp[cli]",
        "--with",
        "spacefrontiers-clients",
        "/path/to/your/spacefrontiers-mcp/mcp_server.py"
      ],
      "env": {
        "SPACE_FRONTIERS_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

Note: replace placeholder paths and the API key with your actual values.