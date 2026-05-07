# Space Frontiers MCP Server

A retrieval layer for AI agents over peer-reviewed papers, books, patents, Wikipedia, Reddit, Telegram, and YouTube. Returns full text and canonical source URIs for citation.

Hosted at **https://mcp.spacefrontiers.org/** (Streamable HTTP transport, OAuth 2.1 with PKCE or Bearer API key).

<a href="https://glama.ai/mcp/servers/@SpaceFrontiers/mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@SpaceFrontiers/mcp/badge" alt="Space Frontiers MCP" />
</a>

## Tools

All four tools are read-only, idempotent, and prefixed `spacefrontiers_` to avoid collisions in multi-server agent setups.

| Tool | When to use |
|------|-------------|
| `spacefrontiers_search_documents` | Peer-reviewed papers, books, patents, Wikipedia. Use for citations and prior art. |
| `spacefrontiers_search_social` | Reddit, Telegram channels, YouTube transcripts. Use for news and community discussion. |
| `spacefrontiers_fetch_document` | Full text + references for one canonical URI (DOI, arXiv, PMID, ISBN). |
| `spacefrontiers_search_in_document` | Passages within one document by query. Use for documents over ~20K tokens. |

Every search hit includes `source_uri`, `score`, `snippet`, `authors`, `issued_date`, and `content_size_tokens` for typed parsing and citation.

## Install

The hosted server has its own [/mcp install page](https://spacefrontiers.org/mcp) with one-click links for Cursor, VS Code, and Smithery.

### Claude Code (recommended)

```sh
claude mcp add --transport http spacefrontiers https://mcp.spacefrontiers.org
```

On first use a browser opens for OAuth login — no API key paste required.

### Cursor / VS Code / Cline / Windsurf (HTTP)

```json
{
  "mcpServers": {
    "spacefrontiers": {
      "url": "https://mcp.spacefrontiers.org",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

Get an API key at https://spacefrontiers.org/keys.

### Self-hosted (stdio)

```sh
git clone https://github.com/SpaceFrontiers/mcp.git
cd mcp
uv sync
SPACE_FRONTIERS_API_KEY=sf_live_xxx uv run fastmcp run mcp_server.py
```

## Repository layout

- `mcp_server.py` — Starlette + FastMCP entrypoint, OAuth well-known endpoints.
- `tools.py` — four tools with Pydantic output schemas.
- `prompts.py` — `deep_research_agent` prompt.
- `resources.py` — `spacefrontiers://document/{uri_b64}` URI template.
- `auth.py` — Bearer-token validation, Origin allowlist, MCP-Protocol-Version check.
- `client.py` — async HTTP client for the v2 search API.
- `server.json` — Official MCP Registry entry.
- `smithery.yaml` — Smithery deployment config.
- `registry.json` — in-house registry metadata.
- `tests/` — pytest unit tests.

## Spec compliance

- **Transport**: Streamable HTTP, stateless.
- **Auth**: OAuth 2.1 with RFC 7591 Dynamic Client Registration; long-lived API keys also accepted.
- **Annotations**: every tool declares `readOnlyHint`, `idempotentHint`, `openWorldHint`, `destructiveHint:false`.
- **Output schemas**: every tool's `outputSchema` is auto-generated from a Pydantic return model.
- **Resources**: one URI template registered for documents.
- **Spec versions accepted**: `2025-03-26`, `2025-06-18`, `2025-11-25`.

## Development

```sh
uv sync
uv run pytest
uv run ruff check .
```

mcp-name: io.github.spacefrontiers/mcp

## License

MIT
