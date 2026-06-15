# Reliquary Enrichment — Scope & Architecture

_Draft 2026-06-13. The claim-aware MEANING layer over the context_reliquary corpus._

## 1. What this is
A reasoning model (GLM-4.5-Air) reads the Aflac case file region-by-region and extracts
**structured, cross-linked, *cited* meaning** — events, entities, dates, codes, claim-relevance —
and writes it to the DB so retrieval hits on **meaning, not words**.

**Why:** vector search alone can't surface the answers — the gold note (the B. Smith supervisor
reversal) ranks ~30–47 under *every* embedder we tried. The lever is enrichment, not the embedder.

## 2. What this is NOT
- **Not** a rebuild of the retrieval spine. The RAG MCP (`query_vector_db` on mcp-hub:9666) is
  PROVEN working end-to-end through Turnstone — we **extend** it, we do not touch it.
- **Not** the LangGraph / SilverBullet-markdown memory POC (archived — see §10).
- **Not** a home for raw chunk text — that lives in `context_reliquary.claim_chunks`.

## 3. Relationship to context_reliquary
- **context_reliquary** = the retrieval product (corpus + `query_vector_db`). The spine.
- **reliquary_enrichment** (this) = the meaning layer that makes retrieval *work*. A new product
  under the umbrella.
- **Shared:** the DB (192.168.1.53), the corpus (`claim_chunks`), Turnstone, GLM-Air, LiteLLM.

## 4. Architecture (extends the proven spine)
- **Agent:** GLM-4.5-Air, in a Turnstone **regular** workstream (coordinators have no MCP surface).
- **Working memory:** Turnstone **native structured memory** holds cross-pass state —
  the discovered schema (`reference`), the entity/date registry (`reference`), corrections
  (`feedback`). BM25-auto-injected each turn → the agent always sees the current schema/registry.
- **New MCP server** (`reliquary_enrichment`, SEPARATE from the RAG MCP so the spine stays
  untouched), on mcp-hub, streamable-http, registered separately in Turnstone.
- **Grounding judge:** a local Qwen-14B, called *inside* `write_enrichment` to verify each fact
  against its cited span. **Provenance enforced mechanically at the write boundary.**
- **Turnstone security judge:** point at the same local Qwen (cross-model) for tool-call safety;
  verdicts auto-logged to `intent_verdicts`.

## 5. MCP tool specs (the new server)
| Tool | Purpose | Approval |
|---|---|---|
| `get_chunk(chunk_id)` / `get_neighbors(chunk_id, window)` | read source + document context (provenance origin) | auto (read-only) |
| `search(query, mode)` | vector + keyword — find related-but-distant events | auto (read-only) |
| `write_enrichment(payload)` | schema-validated write **with built-in local-Qwen grounding check**; rejects/flags ungrounded claims; every row carries provenance (chunk_id, char offsets, page) | judge-checked write |
| `link_events(a, b, relation, evidence)` | record temporal/causal alignments across distant chunks | judge-checked write |

## 6. Multi-pass workstream (constraint + direction; emergent schema)
- **Per-pass validation gate (calibration canary) — Joe, 2026-06-14:** before running ANY pass over
  the full region, run it on a SMALL hand-checked sample and confirm the model captured what we
  expect, *in the form* we expect. Scale to the full pass only once the sample passes. Cheap
  calibration beats an expensive re-run, and a wrong-but-confident pass poisons everything
  downstream. (Born from the 2026-06-14 memory-save catch: GLM verbalized + corrupted `89503c71`
  while declaring success — see [[invariant-llm-not-a-data-bus]].)
- **Acceptance weighs precision AND recall — Joe, 2026-06-14:** the gate also asks *are we capturing
  ENOUGH?* It's a lot of pieces the model must align before persistence is greenlit — track
  bounce-rate + missed-fact-rate on the sample; **too sparse** (over-strict bouncing that starves
  coverage) fails acceptance as hard as false information. Lever if it does (not now):
  **strict-core / soft-rest** — bounce only on the grounded fact + provenance, flag-don't-bounce the
  softer interpretation / relevance.
- **Pass 0 — Segment & classify** each region (kv / narrative / event-log / file-list / status-change).
- **Pass 1 — Schema DISCOVERY** (emergent): the model *proposes* the record types / fields /
  entities / relations it actually SEES, each **citing example spans**; NOT applied. Curated
  (Joe + Architect) → written to Turnstone memory as the working schema.
- **Pass 2 — Extraction/fill** into the curated schema; every field grounded + cited; judge-checked.
- **Pass 3 — Cross-linking/alignment** (the core need): link events that relate but sit pages
  apart. A *separate* pass — you can't link what you haven't yet extracted.
- **Pass 4 — Claim-relevance interpretation** (inference tier): claim-significance +
  **questions-this-answers** (what we embed). Flagged separate from fact, cites the facts it rests on.

## 7. Schema (emergent on a fixed spine)
- **Core anchors (pre-defined):** provenance (chunk_id, char_start/end, page, document),
  normalized date, actor, generic record (`type`, `confidence`, `tier ∈ {fact, interpretation}`).
- **Emergent (from Pass 1):** record types, per-type fields, entity types, relation types —
  discovered, curated, carried in Turnstone memory.

## 8. DB schema (proposed, beside `claim_chunks`)
- `enrichment_records` — grounded **Enrichment Records** (`record_type`, `fields jsonb`, `actor`,
  `event_date`, `claim_relevance`, `tier`, `confidence`, provenance: `source_chunk_id` + char
  offsets + page, `evidence_span`, **`provenance_validation jsonb`** [verdict + judge id +
  evidence/source SHA-256 + time → immutable, tamper-evident], `entity_refs jsonb`). **Write-once.**
- **The Codex — the index layer (promoted to first-class; Joe 2026-06-14):**
  - `codex_entities` — normalized **Entities** (dates / events / actors) that records point at,
    shared **across** record schemas. This is what enables cross-boundary linking — no longer
    "optional later."
  - `enrichment_links` — cross-record **Links** (`record_a`, `record_b`, `relation`, `evidence`,
    `confidence`), written by `link_events`.
- `enrichment_meaning` — per-chunk `claim_meaning` + `questions_answered`; **EMBEDDED (Qwen3)** →
  fused with `claim_chunks` vectors at query time.

## 9. Test run (prove the needle)
- **Scope:** the **notes section** (densest mixed-meaning; the gold note lives here).
- Run Passes 0–4 over it; embed the resulting `claim_meaning` into Qwen3 space.
- **Measure:** does the gold note (`89503c71-5ca2-424b-9386-6698a8337dc3`) rank lift on
  `verify_rank.py`? + spot-check grounding on a sample.

## 10. Archive map (move + note, don't delete)
**KEEP (the spine, untouched):** the RAG MCP (`query_vector_db`, `context_reliquary_mcp.service`
on mcp-hub); `claim_chunks` corpus + embeddings.
**ARCHIVE + note (superseded POC):**
- The SilverBullet-markdown context-memory MVP (`store_context_memory` / `retrieve_context_memory`)
  → superseded by Turnstone native memory.
- The LangGraph Phase-1 plan → superseded by Turnstone orchestration.
**VERIFY then decide:** `codex_entries` / `fragments` / `active_constructs` tables + their stores —
confirm unused for the claim mission before archiving the *code*; the empty DB tables are harmless
to leave but should be flagged as POC.

## 11. Dependencies
- **Embedding cutover finished** (`embed_qwen3_8b` alias + `vector_search` → `embedding_qwen3`,
  deployed to the RAG MCP) — so enrichment embeds `claim_meaning` into the SAME space as the corpus.
- **Resourcing — CONFIRMED 2026-06-14:** GLM-Air agent + Qwen2.5-14B judge **coexist on the 3× R9700**
  (~30 GB/card of 32 → ~2 GB/card headroom; two llama-server stacks, ~75 G + ~15 G). No GPU room for a
  third model → **Qwen3 query-embeddings serve on CPU** (fine for occasional one-shot query embeds),
  or trim GLM's context to make room. Watch the thin headroom under heavy long-context GLM load.

## 12. Decisions (resolved 2026-06-13)
1. **Repo name:** `reliquary_enrichment`. ✅
2. **MCP server: SINGLE** — add the enrichment tools to the existing `context_reliquary` MCP server,
   not a separate one. Provenance is enforced in the schema + write-path, not by server split. If
   separation is ever genuinely needed, split by **DB schema or API endpoint**, not by server.
3. **Grounding-judge model: Qwen2.5-14B-Q6** ✅ (A/B'd 2026-06-14, ~44 t/s, clean/correct/stops).
   Qwen3-14B-Q6 was **DISQUALIFIED** — it spiraled into a runaway *confabulation* (fabricated
   thousands of fake Mersenne exponents, never answered, hit the length cap; DRY didn't catch the
   *semantic* runaway). For a bounded verify task, a model that can fabricate data is disqualifying;
   the non-thinking reliability of Qwen2.5 is exactly the judge profile.

## 13. Team / workflow
- **Architect** (Opus): schema, tool contracts, eval, scope (this doc).
- **Sr Engineer** (separate Claude on the nodes): implements the MCP server + passes
  (the Architect→Engineer brief flow already exists under `turnstone_deploy/`).
- **Joe** (PO): forks + approval; runs privileged cluster ops.

## 14. Sequence (milestones)
0. **✅ VALIDATE Turnstone memory save/recall — DONE 2026-06-14.** Proven end-to-end: saved in
   ws-921c → recalled in a SEPARATE fresh workstream (agent answered "from our previous session"
   unprompted, via a **metacognition nudge** + memory surfacing). Continuity plumbing is solid.
   CAVEAT: the agent corrupts exact tokens both writing AND reading — `89503c71` never round-tripped
   (verbalized + digit-dropped) — so provenance MUST ride our validated write path, never free-typed
   agent memory. See [[invariant-llm-not-a-data-bus]].
1. **A/B the judge model** (Qwen2.5-14B-Q6 vs Qwen3-14B, perfect-numbers probe) → stand up the winner.
2. Build the enrichment tools on the existing `context_reliquary` MCP server + reload in Turnstone.
3. Run Passes 0–1 on the notes section → curate the emergent schema (lands in Turnstone memory).
4. Passes 2–4 → enrichment in DB → embed `claim_meaning`.
5. `verify_rank` on the gold note → measure the needle moved.
6. Finish the embedding cutover (Qwen3 live in the RAG path) — bundle with stack VRAM resourcing.

## 15. Standards (NON-NEGOTIABLE — and they must not slow us down)
- **TDD — test first, always.** Every tool, pass, and schema change ships with tests. Testing,
  testing, testing. Fast, but mandatory.
- **Ubiquitous Language.** Project terms first — the three-tier ontology (Joe 2026-06-14):
  **Fragment** (raw source context) → **Enrichment Record** (one grounded fact / interpretation) →
  **Codex** (the *index*: normalized **Entities** [dates / events / actors] + cross-record
  **Links**). Plus **Provenance** + **Provenance Validation** (the immutable, hashed grounding
  attestation), **Evidence Span** (code-sliced), **Tier** (fact | interpretation). _"Codex Entry"
  retired_ — it conflated the index with the records. Vendor terms only at the integration boundary;
  the same concept named the same way in docs, code, schema, and adapters. (The one genuinely good
  discipline carried from the POC.)
- **Documentation on every file.** Every file gets a terse header — what it is, why it exists.
  No exceptions; a few lines; never a slowdown.

## 16. Housekeeping (low-lift, alongside)
- Rename LiteLLM lanes to purpose-driven names (`r9700_qwen72b` → `heavyweight`, `lane1_general` →
  `general`, …) so the names stop lying about which model serves.
