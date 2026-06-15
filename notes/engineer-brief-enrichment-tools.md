# Engineer Brief — Build the Enrichment Tools (`write_enrichment` + the Codex)

_From: Architect (Opus). To: Sr. Engineer. PO: Joe — approved the design 2026-06-14._
_Status: design approved, ready to build. **Review first, flag gaps, then implement TDD.**_

## 0. TL;DR
Build the enrichment MCP tools that turn the claim corpus into **grounded, cross-linked meaning**.
Two validated write boundaries — `write_enrichment` (the facts) and `link_events` (the Codex index)
— both governed by one law: **the model points, code copies the exact tokens, a local judge checks,
the row attests.** Full specs are in `contracts/`. The contracts' test sections **are** the
acceptance criteria — write them first.

## 1. Read these first (the spec)
- **`contracts/write_enrichment.md`** — the facts boundary (THE safety-critical tool).
- **`contracts/codex.md`** — the index: Entities + Links + the `link_events` tool.
- **`SCOPE.md`** — the why, the 5-pass plan, §15 standards, the resolved decisions, §8 DB schema.
- Mission context: the **gold note** is `89503c71-5ca2-424b-9386-6698a8337dc3` — the supervisor
  reversal that the whole system exists to surface. It ranks ~30–47 under pure vector search;
  **enrichment is the lever**, not the embedder.

## 2. The invariant you are implementing (do not compromise)
> The model never transcribes an exact token that gets stored. It **points**; code **copies**; the
> judge **checks**; the row **attests**. Nothing in the index is ever ungrounded.

Born from a live failure on 2026-06-14: GLM verbalized **and** corrupted `89503c71` on both write and
read while declaring success. Every design choice flows from this. Test #2 in each contract encodes
it as a permanent regression.

## 3. Build sequence
0. **Environment** — work in a **conda** env (miniforge3 is already on mcp-hub at `~/miniforge3`);
   **never** venv / pyenv / virtualenv (hard project standard). Create a dedicated env for the build.
1. **`schema/` DDL** — `enrichment_records` (write_enrichment §7), `codex_entities` +
   `enrichment_links` (codex §3–4), `enrichment_meaning` (SCOPE §8). Migrations **+ a rollback**.
   Beside `claim_chunks` in the `context_reliquary` DB.
2. **Shared grounding-core module** — pipeline steps 1–6 (resolve → load → bounds → slice → judge →
   tier-gate) that **both** tools import (decision D). This is the heart — test it standalone first.
3. **`write_enrichment`** — TDD: contract §9 tests first (incl. the 🔴 89503 regression, date/word
   drift, span-is-code-sliced, `provenance_validation` hash integrity).
4. **`link_events`** — TDD: codex §8 tests first (incl. `same_event` materialization, entity dedupe,
   both-span hashes).
5. **Register/reload in Turnstone** — **SINGLE MCP server**: add these tools to the EXISTING
   `context_reliquary` MCP server (SCOPE decision #2). Also re-register the RAG MCP — its Turnstone
   registration was lost in the 2026-06-14 DB wipe.

## 4. Integration facts (⚠️ verify the starred ones against the live system before relying on them)
- **MCP server:** the existing `context_reliquary` MCP on **mcp-hub (192.168.1.74)**, FastMCP
  **streamable-http** (never SSE). ⚠️ confirm service name (`context_reliquary_mcp.service`) + deploy
  path (`/home/joe/context_reliquary_deploy`) — memory is ~2 weeks old. **Single server — add tools
  here, do not spin a new one.**
- **DB:** cert-auth Postgres, **llm-db 192.168.1.53:5432**, DB `context_reliquary`. Provenance
  (`page`, `document`, the Fragment text) is read from `claim_chunks`. ⚠️ confirm the exact
  `claim_chunks` column names before slicing offsets against them.
- **Grounding judge:** **Qwen2.5-14B-Q6** on the **`judge` lane (port 8082)** via LiteLLM
  (192.168.1.53:4000). Coexists with GLM-Air on the R9700s. Called from inside the shared core.
  Non-thinking → force/parse structured output defensively (that reliability is why it won the A/B).
- **Handles / current-Fragment:** read tools (`get_chunk`/`get_neighbors`/`search`) issue short
  **Chunk Handles**; the session handle-map is in-process, keyed by workstream id (decision C). In
  per-Fragment passes the orchestrator sets the current Fragment and the model passes no chunk ref.
- **Embedding (later, do not block on):** `enrichment_meaning.claim_meaning` embeds with
  `embed_qwen3_8b` into the corpus's space — but the **corpus cutover to Qwen3 is NOT yet deployed to
  the RAG MCP** (still BGE-1024 code there). Coordinate before assuming Qwen3 is live in the RAG path.

## 5. Standards (non-negotiable — SCOPE §15)
- **TDD — tests first, always.** The contract test lists are your red tests.
- **Ubiquitous Language** — the three-tier ontology *exactly*: **Fragment / Enrichment Record /
  Codex** (Entities + Links). Same names in code, schema, docs, adapters. "Codex Entry" is retired.
- **Docs on every file** — a terse header: what it is, why it exists.

## 6. Resolved decisions (don't re-litigate — raise only if reality fights them)
A both reference modes · B judge structured-output is your call · C handle-map in-process ·
D shared grounding-core module · E names = Fragment / Enrichment Record / Codex, table stays
`enrichment_records`. **Event Entities materialize from `same_event` links** (codex §9-A).

## 7. Out of scope (this brief)
- The passes themselves (0–4) + emergent-schema curation — after the tools exist.
- The embedding cutover — separate track, coordinate.
- The `verify_rank` eval on the gold note — after enrichment lands.

## 8. Definition of done
- DDL applied (migrations + rollback) on `context_reliquary`.
- Shared grounding-core + both tools — **all contract tests green**.
- Tools registered in the `context_reliquary` MCP and callable from Turnstone.
- A short note back to the Architect: **anything in the contracts that fought the implementation**, so
  we refine the spec — not just the code.

## 9. Pushback welcome
This is a design handoff, not a decree. If a contract assumption breaks against reality (judge output
shape, the handle-map, the DB schema), **flag it before grinding** — we refine the contract.
Three-party discipline: PO + Architect + Engineer aligned before any big procedure.
