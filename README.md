# Space Frontiers MCP Server

## General Overview

This project implements a Model Context Protocol (MCP) server that acts as an interface to the Space Frontiers API. It allows language models to interact with Space Frontiers data sources through defined tools. The server is built using FastAPI and the FastMCP library.

**Note:** Space Frontiers provides a publicly hosted MCP server at `https://mcp.spacefrontiers.org`. To use it, obtain an API key from [https://spacefrontiers.org/developers/keys](https://spacefrontiers.org/developers/keys) and include it in your requests using the `Authorization: Bearer <your_api_key>` header.

## Tools

The server exposes the following tools for interaction:

### `simple_search`

Performs a keyword search over specified Space Frontiers databases (library, telegram, or reddit).

**Parameters:**

*   `source` (SourceName): The data source to search (e.g., "library", "telegram", "reddit").
*   `query` (str): The keyword search query.
*   `limit` (int): The maximum number of results to return.
*   `offset` (int): The starting offset for the results.

**Returns:** (str) Search results.

### `search`

Performs a semantic search over specified Space Frontiers databases (library, telegram, or reddit).

**Parameters:**

*   `query` (str): The semantic search query.
*   `sources_filters` (dict[SourceName, dict], optional): A dict of data sources to search with filters. Defaults to `{"library": {}}`.
*   `limit` (int, optional): The maximum number of results to return. Defaults to `10`.

**Returns:** (str) Search results.

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

To run the server for use with the Claude App or STDIO communication, execute the following command in your terminal:

```bash
uv run fashmcp run mcp_server.py
```

Make sure to set the `SPACE_FRONTIERS_API_KEY` environment variable before running the server.

### Example Claude Desktop App Configuration (`claude_desktop_config.json`)

Here's an example configuration for integrating the Space Frontiers MCP server with the Claude Desktop app:

```json
{
  "mcpServers": {
    "Space Frontiers MCP server": {
      "command": "/path/to/your/uv", // Replace with the actual path to your uv installation
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
        "/path/to/your/spacefrontiers-mcp/mcp_server.py" // Replace with the actual path to mcp_server.py
      ],
      "env": {
        "SPACE_FRONTIERS_API_KEY": "YOUR_API_KEY_HERE" // Replace with your actual API key
      }
    }
  }
}
```
**Note:** Replace the placeholder paths and API key with your actual values.

_(Instructions on how to run the server, e.g., using Docker or `uvicorn`, can be added here)_ 