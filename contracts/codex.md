# Contract: the Codex — `codex_entities`, `enrichment_links`, `link_events`

_Architect deliverable. Sibling to `write_enrichment.md`. The Engineer implements the HOW in
`mcp_server/`; Joe (PO) approves before build. Draft 2026-06-14._

> The **Codex** is the *index* layer — normalized **Entities** + cross-record **Links** — the
> navigable map over Fragments (context) and Enrichment Records (facts). It is **the lever**: the
> gold note's meaning only emerges when the reversal record links to the approval it undid, the
> supervisor who drove it, and the date it happened — across pages vector search can't bridge.
> Read §2 first; the Codex inherits `write_enrichment`'s discipline wholesale.

---

## 1. What the Codex is — and is NOT
- **Is:** the structured index — shared **Entities** (the nouns) + typed **Links** (the edges) — that
  cross-references Enrichment Records so meaning sitting pages apart becomes explicit and embeddable.
- **Is NOT:** raw context (Fragments) or the facts themselves (Enrichment Records). The Codex *points
  at* them; it never duplicates them.
- **Why it's the lever:** SCOPE.md §2 — the gold note ranks ~30–47 under every embedder because its
  significance is *relational*, not lexical. The Codex makes the relations first-class.

## 2. The principle (inherits `write_enrichment` wholesale)
> **The model proposes refs and links; code materializes the index; the judge checks every link; the
> row attests. Nothing in the index is ever ungrounded.**

The model never types an Entity into existence and never asserts a Link that isn't checked. Entities
are **code-materialized** from grounded record-refs and grounded Links. Every Link passes the same
point → copy → check → attest boundary as a record — the **shared grounding core** (SCOPE.md §10-D).

## 3. `codex_entities` — the shared nouns
The normalized things records point at, shared **across** record schemas (the cross-boundary sharing).
- **Types:** `actor` (person/org), `date` (calendar), `event` (a canonical occurrence). Extensible:
  `document`, `provision`, `code`.
- **Schema:** `entity_id, entity_type, canonical (normalized value/name), aliases jsonb, metadata
  jsonb, first_seen_record, created`.
- **Materialized — never model-typed:**
  - `actor` / `date` — at **`write_enrichment`** time (its step 9): code normalizes the
    judge-validated `actor`/`event_date` and resolves-or-creates the Entity; the record stores the ref.
  - `event` — materialized by **code from `same_event` Links** (§5–6): when the model grounds a
    "these two records describe the same occurrence" Link, code creates/merges the Event Entity and
    points both records at it.
- **Normalization/dedupe** is the hard part (§9-B): "B. Smith" vs "manager B. Smith" vs "Bruce Smith".
  The model *proposes* a match; code/judge *confirms*; unsure → **flag for curation, never
  silent-merge.**

## 4. `enrichment_links` — the cross-record edges
- **Schema:** `link_id, record_a, record_b, relation, tier (fact|interpretation), evidence jsonb
  (cited spans/refs), confidence, provenance_validation jsonb, flagged, created`. **Write-once.**
- **Relation vocabulary** (seeded + curated, emergent like record_types):
  - temporal — `precedes` / `follows`
  - causal — `causes` / `results_from`
  - evidential — `corroborates` / `contradicts`
  - structural — `elaborates` / `same_event` / `references`
- **Directionality:** some directed (`precedes`), some symmetric (`corroborates`) — marked per relation.
- **Combinatorial guard:** the model proposes *specific candidate* Links from reasoning — **never
  all-pairs.** Cross-linking is where noise explodes.

## 5. `link_events` — the validated Link write boundary (mirrors `write_enrichment`)
**Payload (model provides):**
```jsonc
{
  "record_a": "<id or handle>",        // points at an existing Enrichment Record
  "record_b": "<id or handle>",
  "relation": "results_from",          // from the curated vocabulary
  "tier":     "interpretation",        // fact (explicit cross-ref) | interpretation (inference)
  "evidence": { "a_span": [s, e], "b_span": [s, e] },   // points; code slices
  "rationale": "…",                    // why the relation holds (judge-checked)
  "confidence": 0.8
}
```
**Pipeline — reuses the shared grounding core (`write_enrichment` §5 steps 1–6, factored out):**
1. **Resolve both records** (id/handle) → must exist in `enrichment_records`. Miss → `REJECT unknown_record`.
2. **Load both records + their Fragments.**
3. **Slice the evidence spans** from each Fragment (CODE).
4. **Grounding judge** — tier-aware: `fact` → "does the cited evidence *explicitly* state this
   relation?"; `interpretation` → "is `relation` a reasonable inference from A, B, and this evidence,
   not contradicting it?" → Grounding Verdict.
5. **Tier gate** — bounce `ungrounded` (and `fact`≠grounded); `partial` → `flagged=true`.
6. **Compute `provenance_validation`** — verdict + judge id + **SHA-256 of _both_ evidence spans** + time.
7. **If `relation = same_event`** — code resolves/creates the Event Entity, re-points both records' refs.
8. **Write the Link** (write-once).
9. **Return** `{ ok:true, link_id, relation, provenance_validation }` or `{ ok:false, reason_code, detail }`.

## 6. The `same_event` case — how Event Entities form
The *only* way an Event Entity is born: the model grounds a `same_event` Link; code materializes or
merges the Event Entity and re-points both records' `entity_refs`. Transitive merges (A~B, B~C ⇒ one
event) are **code's** job — the model asserts pairwise + grounded; code maintains the cluster. Keeps
"model points, code builds" intact.

## 7. Coverage — precision AND recall (same gate, SCOPE.md §6)
Too few Links → the story stays fragmented (the gold note stays unconnected). Too many → noise drowns
signal. Acceptance measures **both** Link precision (are these real?) and recall (did we find the
Links that matter — especially *around the gold note*?) on the calibration sample.

## 8. Tests (TDD — write FIRST; they are the acceptance criteria)
1. **Happy path** — grounded relation over two real records → Link written; both evidence spans
   byte-exact; `provenance_validation` hashes verify.
2. **🔴 Corrupted record ref** — a mangled record id → `REJECT unknown_record`; nothing written.
   (The 89503 discipline, for record ids.)
3. **Ungrounded relation** — A and B don't actually relate / evidence doesn't support it → bounce, with reason.
4. **Contradiction tiering** — `contradicts` correctly distinguished from `corroborates` by the judge.
5. **`same_event` materialization** — exactly one Event Entity; a transitive third record merges into
   the same cluster (no duplicate events).
6. **Entity dedupe** — "B. Smith" / "manager B. Smith" → one actor (or flagged); never silent-wrong-merge.
7. **provenance_validation integrity** — both span hashes match; tampering either source is detectable.
8. **Combinatorial guard** — proposals are specific, not all-pairs (exercise the proposal path).

## 9. Decisions (recommended; confirm before build)
- **A. Event-entity formation → materialize from `same_event` Links** (recommended; keeps the model
  out of entity-creation) vs resolve-at-write. ← *most conceptually load-bearing; your call.*
- **B. Entity normalization → start minimal** (exact + a small per-type alias table), grow with
  evidence; full fuzzy-canonicalization is its own task later.
- **C. Relation vocabulary → the seed set above + curate emergent relations in Pass 1/3** (like record_types).
- **D. Shared grounding core → a factored module** both tools import (confirmed, SCOPE.md §10-D); this
  contract assumes it exists.
- **E. Link symmetry → store directed, mark symmetric** so queries don't double-count.

**Depends on:** the `write_enrichment` contract (records + the shared core) and the `schema/` DDL.
