# reliquary_enrichment

The claim-aware **meaning layer** over the context_reliquary corpus — a reasoning model reads the
Aflac case file and extracts structured, cross-linked, *cited* meaning so retrieval hits on meaning,
not words.

**Start here: [SCOPE.md](SCOPE.md)** — full scope, architecture, and the open decisions.

This is a *new, cleanly-separated* project under the context_reliquary umbrella. It **extends** the
proven RAG spine (`query_vector_db` MCP on mcp-hub) — it does not rebuild or touch it.

It is a pip-installable package, editable-installed into the `context-reliquary` conda env;
its tools mount onto the **existing** context_reliquary FastMCP server via
`reliquary_enrichment.mcp.register_tools` (one server, one port — Decision D1).

Layout:
- `src/reliquary_enrichment/` — the package
  - `grounding/` — the shared **grounding-core** (resolve → slice → judge → tier-gate →
    attest), the `Fragment`/`FragmentReader`, the workstream-keyed `HandleMap`, and the
    `GroundingJudge` interface (+ LiteLLM `judge` impl, fail-closed parse).
  - `write_enrichment.py` / `link_events.py` — the two judge-checked write boundaries.
  - `read_tools.py` — `get_chunk` / `get_neighbors` (mint Chunk Handles).
  - `entities.py` — Entity resolve-or-create + Event-cluster materialization (union-find).
  - `models.py` / `stores.py` — domain rows + store protocols.
  - `postgres/` — Postgres bindings for the stores + Fragment reader (cert-auth, env-overridable).
  - `mcp.py` — `register_tools(mcp)`, the spine hook.
- `schema/` — additive DDL migrations (+ rollbacks) for the four enrichment tables.
- `tests/` — TDD acceptance suites (contract §9 / codex §8) + integration tests.
- `notes/` — working notes (findings, decisions, handoff).
- `passes/`, `eval/` — the multi-pass workstream + needle eval (after the tools land).

Build status: tools complete, **68 tests green** (60 unit + 8 integration). See
`notes/handoff-architect.md` for the deploy steps + open contract questions.
