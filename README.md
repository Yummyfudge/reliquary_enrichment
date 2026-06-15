# reliquary_enrichment

The claim-aware **meaning layer** over the context_reliquary corpus — a reasoning model reads the
Aflac case file and extracts structured, cross-linked, *cited* meaning so retrieval hits on meaning,
not words.

**Start here: [SCOPE.md](SCOPE.md)** — full scope, architecture, and the open decisions.

This is a *new, cleanly-separated* project under the context_reliquary umbrella. It **extends** the
proven RAG spine (`query_vector_db` MCP on mcp-hub) — it does not rebuild or touch it.

Layout:
- `mcp_server/` — the new enrichment MCP tools (get_neighbors, write_enrichment, link_events)
- `passes/` — the multi-pass workstream (segment → discover schema → extract → link → interpret)
- `schema/` — emergent schema on a fixed provenance spine
- `eval/` — needle-measurement (gold-note rank via verify_rank)
- `notes/` — working notes
