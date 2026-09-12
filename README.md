# Machine Library MCP Server

Machine Library is the search and AI product by **Space Frontiers Company**.
Existing accounts, API keys, and `spacefrontiers_*` tool names remain compatible.
The original `https://mcp.spacefrontiers.org` endpoint is still supported.

A retrieval layer for AI agents over peer-reviewed papers, books, patents, standards, Wikipedia, Reddit, Telegram, Discord, and YouTube. Returns bounded full text and canonical source URIs for citation.

Hosted at **https://mcp.machinelibrary.ai/** (Streamable HTTP transport, OAuth 2.1 with PKCE or Bearer API key).

**Try a worked example:** [Find research, inspect supporting passages, and retain citations](examples/research-evidence.md).
Includes exact tool calls and observations from a live run, plus a small evaluation checklist for research teams.

<a href="https://glama.ai/mcp/servers/@SpaceFrontiers/mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@SpaceFrontiers/mcp/badge" alt="Machine Library MCP" />
</a>

## Tools

The four core retrieval tools below are read-only, idempotent, and prefixed `spacefrontiers_` to avoid collisions in multi-server agent setups. The hosted service may expose additional tools; inspect its current `tools/list`. In particular, the optional `spacefrontiers_top_up_balance` capability purchases prepaid credits and is not a read-only retrieval tool.

| Tool | When to use |
|------|-------------|
| `spacefrontiers_search_documents` | Papers, books, patents, standards, Wikipedia, YouTube transcripts. Use for citations and prior art. |
| `spacefrontiers_search_social` | Reddit, Telegram channels, Discord. Use for news and community discussion. |
| `spacefrontiers_fetch_document` | Bounded full text + up to 50 references for one canonical URI. Defaults to 40K characters; supports up to 100K. |
| `spacefrontiers_search_in_document` | Up to five matching passages within one document. Use for documents over ~20K tokens. |

Search defaults to 10 compact, hybrid-ranked results and is capped at 30. Every hit includes a canonical `source_uri`, one snippet (up to 900 characters), an abstract preview (up to 800 characters), score, authors, date, type, and estimated full-text size. Citation backlinks are opt-in on `spacefrontiers_fetch_document` because they add another billed search.

## Install

The hosted server has its own [/mcp install page](https://machinelibrary.ai/mcp) with one-click links for Cursor, VS Code, and Smithery.

### Claude Code (recommended)

```sh
claude mcp add --transport http --scope user spacefrontiers https://mcp.machinelibrary.ai
```

On first use a browser opens for OAuth login — no API key paste required.

### Cursor / VS Code / Cline / Windsurf (HTTP)

```json
{
  "mcpServers": {
    "spacefrontiers": {
      "type": "http",
      "url": "https://mcp.machinelibrary.ai",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

Get an API key at https://machinelibrary.ai/keys.

### Self-hosted (stdio)

```sh
git clone https://github.com/SpaceFrontiers/mcp.git
cd mcp
uv sync
SEARCH_API_ENDPOINT=https://api.machinelibrary.ai \
SPACE_FRONTIERS_API_KEY=sf_live_xxx uv run fastmcp run mcp_server.py
```

The environment variable is used as the upstream API credential in stdio mode.
The command selects the public Machine Library API with `SEARCH_API_ENDPOINT`.
The internal default remains `http://search-api` for existing deployments.
For HTTP deployments, set `SEARCH_API_ENDPOINT` to your trusted internal
search API and `USERS_API_ENDPOINT` to your internal users API; the auth
middleware forwards verified identity headers to that internal service.
OAuth retains the compatible authorization-server issuer at
`https://api.spacefrontiers.org`; browser sign-in for the new product uses
`https://machinelibrary.ai` with the same accounts.

## Pricing

- Search: $0.01 base + $0.001 per returned result (the 10-result MCP default costs $0.02).
- Full document fetch: $0.05.
- In-document passage search: $0.015.
- `referenced_by_limit > 0` on a fetch adds a separately billed search.

Add credits at https://machinelibrary.ai/payments.

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

mcp-name: io.github.SpaceFrontiers/mcp

## License

MIT
