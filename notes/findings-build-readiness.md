# Findings — Build-Readiness Review (Sr. Engineer → Architect + PO)

_Date: 2026-06-14. Before writing code, per brief §9 ("flag anything that fights the
implementation — we refine the spec, not just the code") and the three-party discipline._

I reviewed the contracts + brief against the **live** system on mcp-hub. The design is sound
and buildable. Below: what's confirmed, what fights the contract (refinements), and the few
load-bearing decisions I need PO/Architect sign-off on before I build.

---

## A. Confirmed against reality (starred facts in brief §4 — verified)
- **Host / env:** on `mcp-hub`. `~/miniforge3` conda present; env `context-reliquary` exists
  (brief step 0). conda 26.3.2.
- **MCP server:** `context_reliquary_mcp.service` is **active**, port **9666**, FastMCP **3.3.1**,
  `transport="streamable-http"`. Single tool today: `query_vector_db`
  ([mcp_server.py](../../context_reliquary/src/context_reliquary/mcp_server.py)).
- **Live code path ≠ the paths in the brief.** The service's `WorkingDirectory=/opt/context_reliquary`,
  but the running package is an **editable install** resolving to
  `/home/joe/context_reliquary/src/context_reliquary` (`__editable__` .pth → `/home/joe/context_reliquary/src`).
  `/opt/context_reliquary` and `/home/joe/context_reliquary_deploy` are **stale copies** — do not edit those.
  The brief's `/home/joe/context_reliquary_deploy` is wrong for live edits.
- **DB:** cert-auth Postgres `192.168.1.53:5432`, db `context_reliquary`, `sslmode=verify-full`.
  Connection pattern reused from `PostgresFragmentStore` / `VectorSearchTool`. **Cert paths:** the
  config defaults point at `/mnt/auth_share/...` (fails — perms), but the **service drop-in**
  (`.../context_reliquary_mcp.service.d/certs.conf`) uses `/home/joe/.postgresql/{root.crt,postgresql.crt,postgresql.key}`.
  Build/test must use the drop-in paths.
- **LiteLLM:** up at `192.168.1.53:4000`, OpenAI-compatible. `embed_qwen3_8b` alias **already
  registered** (the Qwen3 embed cutover exists at the proxy even though RAG code still defaults to
  `embed_bge_large`).
- **Deps:** psycopg 3.3.4, pytest 9.0.3, requests 2.34.2, pydantic 2.13.4. No ORM in the write path
  (raw psycopg, per house style). **No SQL migration framework** — schema is applied manually; I'll
  ship plain `schema/*.sql` up + `*_rollback.sql` down.

## B. Fights the contract — refinements needed (not blockers; I'll proceed on the mapping unless told otherwise)

### B1. `claim_chunks` column names ≠ the contract's Provenance shape  ⚠️ load-bearing
The contracts assume Fragment = `claim_chunks` keyed by `chunk_id` with a `fragment_text` column and
top-level `page` / `document`. **Reality** (from `vector_search.py`, authoritative — it queries the live table):

| Contract term | Real column in `claim_chunks` |
|---|---|
| `chunk_id` (Fragment key) | **`claim_chunk_id`** (uuid) |
| `fragment_text` (the text code slices) | **`payload->>'chunk_text'`** (jsonb field, *not* a column) |
| `document` | **`document_name`** |
| `page` | **`page_number`** |
| (chunk classification) | `chunk_type` |
| (also present) | `payload->>'context_wrapper'`, `embedding` (vector) |

**Refinement:** the grounding-core's "load Fragment / slice span / derive provenance" maps to the
real columns above; the **Evidence Span is sliced from `payload->>'chunk_text'`**. I'll encode this
mapping in one place (a `Fragment` accessor over `claim_chunks`) so the contract's vocabulary stays
intact while the storage detail lives in one adapter.

### B2. "Offsets into WHICH text?" must be pinned  ⚠️ invariant-critical
`char_start/char_end` are sliced from `chunk_text`. For the invariant to hold, the **read tool the
model points with must surface that exact same `chunk_text`** (not `context_wrapper`, not a
re-wrapped string) — otherwise the model's offsets and code's slice disagree and grounding is
meaningless. Decision recorded: **Fragment text ≡ `payload->>'chunk_text'`, everywhere** (read tool
output, slice source, `source_sha256`). The judge sees the slice of that same text.

### B3. Ubiquitous-Language collisions with the POC code  ⚠️ naming
The contract redefines two terms the codebase **already uses for something else**:
- **"Fragment":** contract-Fragment = a raw `claim_chunks` row. But the repo has a POC `Fragment`
  model + `fragments` table (`models/fragment.py`, `fragments.codex_entry_id`, `fragment_text`, char
  offsets) — a *different* unit. SCOPE §10 marks the POC `fragments` table verify-then-archive.
  → My grounding-core reads **`claim_chunks` directly** and never touches the POC `fragments` table.
- **"Codex":** the contract's Codex = the index (`codex_entities` + `enrichment_links`). The repo has
  a **retired** `CodexEntry` model + `codex_entry_store` + `codex_entries` table / `codex_entry_id`
  FK on Fragment. New tables are `codex_entities` (entities) and `enrichment_links` — **distinct** from
  the old `codex_entries`. No collision in SQL, but the term is doubly-booked in prose.
  → **Ask Architect:** add a one-line disambiguation to the Ubiquitous-Language table so "Fragment"
  and "Codex" unambiguously mean the new things; the POC `Fragment`/`CodexEntry` are legacy/archived.

## C. Blockers / need PO action before the relevant build step

### C1. The grounding judge is **DOWN and unregistered**  🔴
- `:8082` → **connection refused**; ports 8080–8083 all closed.
- LiteLLM exposes `lane1_general, lane2_multi-gpu, lane3, lane4_vision, r9700_qwen72b, embed_bge_large,
  embed_qwen3_8b` — **no `judge` alias**. `lane3` returns a backend "Connection error" too.
- Impact: the judge is the heart of the invariant. **Unit build is unblocked** — I inject a judge
  client behind an interface and fake it in tests. **Integration + acceptance need the judge live.**
- **Need (Joe / privileged ops, SCOPE §13):** stand up Qwen2.5-14B-Q6 and register a stable LiteLLM
  alias (proposed name **`judge`**, per §16 purpose-driven naming). I'll code to that alias.

### C2. Applying DDL to the live `context_reliquary` DB, and a schema-only read
- I can **write** `schema/*.sql` + rollbacks with no DB access. **Applying** them to prod, and one
  **schema-only** (`information_schema`, no claim content) confirmation query for exact `claim_chunks`
  column types, need your approval — auto-mode (correctly) blocked me from touching the prod corpus.
- **Need:** approval to run schema-only reads + apply the new-table DDL (new tables only; the spine
  tables are untouched).

### C3. Read tools that mint Chunk Handles don't exist yet
- Handle mode (Pass 3, contract §3-1 / decision C) needs a read tool to issue `F1…` handles into the
  in-process map. Today only `query_vector_db` exists — no `get_chunk`/`get_neighbors`.
- Per-Fragment mode (Pass 2, decision A) needs **no** handle — the orchestrator sets "current Fragment".
- **Scope question (below):** do I build `get_chunk` (+ handle minting) in this pass, or land
  write/link against per-Fragment + raw-id first and add handle-minting read tools next?

## D. Recommended reconciliation: single SERVER, code in THIS repo
SCOPE decision #2 = **single MCP server** (don't spin a new one). The brief says push code to
`reliquary_enrichment`. These reconcile cleanly — "single server" ≠ "single repo":

> Make `reliquary_enrichment` its own pip-installable package, `pip install -e` it into the
> **same `context-reliquary` conda env**, and have `context_reliquary.mcp_server` import the
> enrichment tools and register them on the **same FastMCP instance** (one process, one port 9666,
> one service). Code lives in this repo; the spine repo gets a ~3-line registration hook.

This keeps the spine untouched except a tiny, reviewable hook, keeps provenance enforced in *our*
write path, and satisfies "single server." The alternative — code as a subpackage inside the
`context_reliquary` repo — also yields one server but puts our code in the spine repo (against the
brief). **Recommend the separate-package option; needs sign-off because the hook edits the spine repo.**

## E. Proposed build order (once D + C unblocked) — unchanged from brief, TDD-first
1. `schema/` DDL + rollback: `enrichment_records`, `codex_entities`, `enrichment_links`,
   `enrichment_meaning` — in the `context_reliquary` schema, beside `claim_chunks`.
2. **Shared grounding-core** (pipeline steps 1–6: resolve → load → bounds → slice → judge → tier-gate),
   judge client injected. Unit-tested standalone with a fake judge + a seeded test Fragment. **This is
   the heart — built and tested first.**
3. `write_enrichment` — contract §9 tests first (incl. 🔴 89503 regression, date/word drift,
   span-is-code-sliced, provenance-hash integrity, entity resolution).
4. `link_events` — codex §8 tests first (incl. `same_event` materialization, entity dedupe, both-span hashes).
5. Register both on the existing FastMCP server; reload service. Re-register the RAG MCP in Turnstone
   (lost in the 2026-06-14 DB wipe — brief §3.5).

## F. Decisions I need from PO/Architect (asked live alongside this note)
1. **Code placement** — confirm the separate-package + registration-hook approach (D), incl. the small
   edit to the spine's `mcp_server.py`.
2. **Judge** — confirm Joe stands up Qwen2.5-14B + registers a `judge` LiteLLM alias; I code to that name.
3. **DB** — approval for schema-only reads + applying new-table DDL to live `context_reliquary`.
4. **Read-tool scope** — `get_chunk`/handle-minting in this pass, or per-Fragment + raw-id first?
