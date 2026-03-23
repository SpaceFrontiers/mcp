# Space Frontiers MCP Server

MCP server that connects LLMs to Space Frontiers search. Query 170M+ academic papers, books, Wikipedia, patents, Reddit, Telegram, and YouTube.

## Tools

| Tool | Description |
|------|-------------|
| **search** | Sparse vector search across 170M+ documents. Returns titles, URIs, scores, snippets. Filter by `"documents"` (papers, books, patents, Wikipedia) or `"social"` (Reddit, Telegram, YouTube). For news, events, and current topics, always search social. |
| **fetch** | Retrieve full document by URI — content, metadata, references, and citing documents. |
| **search_in_document** | Find relevant passages within a single document using a text query. Ideal for large documents. |

## Install

### Claude Code

```bash
claude mcp add --transport http spacefrontiers https://mcp.spacefrontiers.org \
  --header "Authorization: Bearer YOUR_API_KEY"
```

Get an API key at [spacefrontiers.org/keys](https://spacefrontiers.org/keys).

### Claude Desktop / Cursor / Windsurf

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "spacefrontiers": {
      "url": "https://mcp.spacefrontiers.org",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### AI Agent Install

Tell your AI agent: *"Install the Space Frontiers MCP from https://spacefrontiers.org/install.md"*

## OAuth 2.0

The server supports OAuth 2.0 with PKCE for automatic authentication. Discovery endpoints:

- `GET /.well-known/oauth-protected-resource` — resource metadata
- `GET /.well-known/oauth-authorization-server` — authorization server metadata

The authorization, token, and registration endpoints are on `spacefrontiers.org/api/oauth/`.

## Billing

When your balance is too low, tools return a message with a link to add credits at [spacefrontiers.org/payments](https://spacefrontiers.org/payments). Searches cost ~$0.005, fetches ~$0.01.

## Links

- **Documentation:** [spacefrontiers.org/mcp](https://spacefrontiers.org/mcp)
- **API Keys:** [spacefrontiers.org/keys](https://spacefrontiers.org/keys)
- **Add Credits:** [spacefrontiers.org/payments](https://spacefrontiers.org/payments)
