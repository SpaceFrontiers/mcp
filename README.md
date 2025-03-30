# Space Frontiers MCP Server

## General Overview

This project implements a Model Context Protocol (MCP) server that acts as an interface to the Space Frontiers API. It allows language models to interact with Space Frontiers data sources through MCP tools. The server is built using the FastMCP library.

At a high level, the server provides LLM-accessible search and discovery across Space Frontiers sources such as scholarly literature, Telegram, and Reddit, including both query-based search and recent-item retrieval. Tools are self-describing via MCP schemas and annotations; your MCP client can list and introspect them at runtime.

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