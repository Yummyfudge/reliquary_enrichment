# Handoff — Enrichment Tools Built (Engineer → Architect + PO)

_2026-06-14. Definition-of-done §8: the build is complete and green; here is **what fought
the contracts** (so we refine the spec, not just the code) and the steps that are yours._

## What shipped (all TDD, all green)
**68 tests pass** — 60 unit (offline, fake judge), 8 integration (3 live `judge` alias, 5
against a scratch Postgres). One MCP server, code in this repo.

- **schema/** — additive migrations + rollbacks for `enrichment_records`, `codex_entities`,
  `enrichment_links`, `enrichment_meaning` (+ optional FK 005). Validated end-to-end on a
  pgvector scratch DB: up applies, every constraint + the write-once triggers fire, rollback
  tears down to zero, re-apply works.
- **grounding-core** (`grounding/`) — the factored heart both tools import: resolve → load →
  bounds → slice → judge → tier-gate + the hashed Provenance Validation attestation. Judge
  behind an interface; real impl = LiteLLM `judge` (Qwen2.5-14B), defensive JSON parse that
  **fails closed**.
- **write_enrichment** + **link_events** — the two judge-checked write boundaries (contract
  §9 / codex §8 acceptance tests are the red tests).
- **get_chunk** / **get_neighbors** — read-only, mint Chunk Handles.
- **register_tools(mcp)** — the 3-line hook; applied to the spine's `mcp_server.py`. Verified
  all 5 tools mount on the single FastMCP instance (no DB connection at import).

## What fought the contracts (refinements — please confirm)
1. **`re-point the record's entity_refs` vs write-once (codex §5.7 / §6).** Records are
   write-once (trigger + grants), so we **cannot** mutate a record's `entity_refs` to attach a
   materialized Event. Instead event membership lives on the **Event Entity**
   (`metadata.member_records`, code-maintained union-find with transitive merge) **+**
   `enrichment_links.event_entity`. This *strengthens* the invariant (no record mutation). The
   record→event association is queryable via the Event Entity / the Link. **← most load-bearing
   divergence; please bless.**
2. **Tier gate, step 6 wording.** The contract reads slightly two ways for `partial`. We
   implemented **strict-core / soft-rest** (SCOPE §6): `fact` + partial → REJECT; `interpretation`
   + partial → accept-flagged; `ungrounded` → REJECT either tier. Confirm this is the intent.
3. **Judge names failing _values_, not field names.** Contract test #3 expects
   `failing_values=[event_date]` (the field); the live judge returns the failing **value**
   (`"2025-02-19"`) + a reason. Both pinpoint the drift; tests are tolerant of either. If you
   want field names, we tune the prompt.
4. **`codex_entities.first_seen_record` FK dropped** (kept as a plain column). The FK forced
   entity-after-record ordering that conflicts with "compute entity_refs → insert the
   write-once record → entities point back," and added no real integrity (code always sets it
   to the record being written). Caught by the DB integration test.
5. **`enrichment_meaning.embedding` index deferred.** Column is `vector(4096)` per your ref,
   but pgvector HNSW/IVFFlat cap at 2000 dims (4000 for halfvec). The ANN index must mirror
   whatever `claim_chunks.embedding_qwen3` uses — resolve with the embedding track.
6. **Link record refs are record_ids, not handles.** Codex §5 says "`<id or handle>`" but
   there is no record-handle minting (handles are for Fragments). The 89503 discipline holds
   via existence-check + judge. Record-handle aliasing is a later add if you want it.
7. **`get_neighbors` adjacency key** assumed `segment_index` (intra-document). Confirm vs
   `char_start_offset` before a real Pass 3 relies on neighbor windows.
8. **Relation vocabulary is open.** `link_events` accepts any non-empty relation (emergent /
   curated like record_types), not just the seed set. Enforce a curated allowlist once Pass 1
   settles it, if desired.
9. **`workstream_id`** is an explicit tool param (default `"default"`) keying the in-process
   HandleMap. Binding it to the Turnstone session is an integration detail to confirm
   (Decision C: "revisit if multi-node").

## Your steps (I do not touch prod / Turnstone)
1. **Apply DDL as `joe_dba`** — `schema/001..005.up.sql`, then **`schema/grants.runtime.sql`**
   (the runtime app role has no access to the new tables until granted — tools will fail at
   call-time without it).
2. **Commit the spine hook** — `context_reliquary/src/context_reliquary/mcp_server.py` now has
   the `register_tools(mcp)` hook (separate repo). Commit/deploy it there.
3. **Restart `context_reliquary_mcp.service`** — AFTER (1), so the new tools work on first
   call. Registration itself opens no connections; existing `query_vector_db` is unaffected.
4. **Turnstone** — register the extended `context_reliquary` MCP and **re-register the RAG MCP**
   (its registration was lost in the 2026-06-14 DB wipe — brief §3.5). Turnstone access is yours.

## Repo pointers
- `notes/findings-build-readiness.md` — the pre-build review (B1/B2 column mapping etc.).
- `notes/decisions-log.md` — the four resolved decisions (D1-D4), D3 corrected to "engineer
  writes, Architect applies."
- `tests/scratch_db.md` — how to stand up the scratch Postgres + run integration tests.
