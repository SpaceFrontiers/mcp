# From a research question to inspectable evidence with MCP

Machine Library is the search and AI product by Space Frontiers Company.
This walkthrough is for researchers and engineers building agents that need
to show which source supports an answer.

The task: find research about citation attribution in retrieval-augmented
generation, then inspect what one paper actually says about planning.

## Connect

Add `https://mcp.machinelibrary.ai` as a remote HTTP MCP server in your client.
Use its browser OAuth flow, or a Machine Library Bearer API key. See the
[installation guide](https://machinelibrary.ai/mcp?utm_source=github&utm_medium=organic&utm_campaign=research-evidence-2026q3&utm_content=walkthrough).

The hosted service requires an account and retrieval calls are billed. Check
[current pricing](https://machinelibrary.ai/pricing/world). This example does
not purchase credits or download original files.

## Try this prompt

```text
Use Machine Library to find five papers about retrieval-augmented generation,
citation attribution, and evaluation. Preserve each returned source_uri.
Select a relevant paper about planning and inspect passages about how planning
affects attribution and faithfulness. Explain one supported finding and one
limitation. Cite the inspected source, and distinguish the paper's findings
from your own interpretation. Do not purchase credits or call payment tools.
```

## Inspect the two retrieval steps

These are MCP `tools/call` parameters. Your MCP client handles initialization,
authentication, and the JSON-RPC envelope. For a direct API integration, use
the separate [REST documentation](https://machinelibrary.ai/docs/api).

### 1. Discover candidates

```json
{
  "name": "spacefrontiers_search_documents",
  "arguments": {
    "query": "retrieval augmented generation attribution citation evaluation",
    "limit": 5
  }
}
```

In a live run on **September 12, 2026**, the server returned five results.
One was [Learning to Plan and Generate Text with Citations](https://doi.org/10.48550/arxiv.2404.03381)
by Constanza Fierro and coauthors. It appeared second in that run; choose by
relevance when reproducing the example, because results and order can change.

The returned `source_uri` was
`https://doi.org/10.48550/arxiv.2404.03381`. Copy identifiers from results rather
than inventing a DOI or reconstructing one from a title.

### 2. Inspect passages in the selected paper

```json
{
  "name": "spacefrontiers_search_in_document",
  "arguments": {
    "uri": "https://doi.org/10.48550/arxiv.2404.03381",
    "query": "how does planning affect citation attribution and faithfulness"
  }
}
```

This returned **three passages** in the recorded run, including the paper's
experimental comparison and discussion. The evidence supports this summary:

> In this paper's experiments, combining blueprint planning with citation
> generation improved faithfulness and attribution relative to the relevant
> baselines. Adding citations without the planning stage did not produce the
> same benefit. These are results for the authors' evaluated models and tasks;
> they do not establish that planning improves every RAG system.

Citation: [Fierro et al., Learning to Plan and Generate Text with Citations](https://doi.org/10.48550/arxiv.2404.03381).

The summary above is our paraphrase of the inspected passages, not a quotation.
The hosted server can also return a search trajectory. When your client exposes
`search_result` on the passage tool, pass the hit's `id` as `document_id` and
the trajectory unchanged to attribute the read. Do not publish trajectory
tokens in shared transcripts.

## Turn this into a small evaluation

Use a query set from your actual workflow and record:

| Check | What to record |
|---|---|
| Discovery | Exact query, date, filters, returned rank and source URI |
| Evidence | Selected source, passage query, and whether the passage supports the claim |
| Coverage | Missing expected sources and useful sources returned |
| Answer | Unsupported claims, incorrect citations, and appropriate abstentions |
| Operations | Observed request latency and account cost |

Keep retrieval relevance separate from answer correctness. A source URI makes
a citation traceable; it does not establish that the source supports the answer.
For a literature review, supplement this workflow with the databases and
screening process required by your discipline.

This is a worked example of two successful live retrieval calls, not a benchmark
or a comparison against another provider. No latency or quality improvement
for Machine Library is inferred from it. Full-text availability varies by item;
rights to returned material remain with the applicable rightsholders.

## Next step

Try the same process on a question from your own field:
[connect Machine Library](https://machinelibrary.ai/mcp?utm_source=github&utm_medium=organic&utm_campaign=research-evidence-2026q3&utm_content=walkthrough).

For research evaluation or integration discussions, contact
[contact@machinelibrary.ai](mailto:contact@machinelibrary.ai) with the task,
sources you expect to find, and the failure cases you care about. Please do not
send private research data in an initial inquiry.
