# Contract: `write_enrichment` — the validated provenance write boundary

_Architect deliverable (the WHAT/WHY + acceptance tests). The Engineer implements the HOW in
`mcp_server/` against this. Joe (PO) approved the design 2026-06-14; this revision folds in his
review (provenance-validation attestation, coverage acceptance, the Codex ontology)._

> **The single most safety-critical tool in the system** — the only path by which extracted meaning
> reaches storage. Its whole job is to make `invariant-llm-not-a-data-bus` **mechanical**. Read §1
> and §3 first.

---

## 1. Purpose & the invariant it enforces
On 2026-06-14 (Milestone 0) GLM-4.5-Air, asked to remember `chunk 89503c71 — supervisor reversal`,
stored `eight nine five zero three c71 … reversible` and read it back shorter still. It corrupted a
precise token **both writing and reading**, while declaring success.

`write_enrichment` exists so that can never reach the corpus. **The one rule:**

> **The model never transcribes an exact token that gets stored. It _points_; code _copies_; the
> judge _checks_; the record _attests_.**

The model reasons — *what* a span means and *why* it matters to the denial. Every exact token is
copied **by code** from the source; the claim is verified **by a judge** against that code-copied
source; and the result is frozen into an immutable **Provenance Validation** attestation — all
before a single row is written.

## 2. Ubiquitous Language — the three-tier ontology (== terms in code, schema, docs; SCOPE.md §15)
| Domain term | Is | Storage |
|---|---|---|
| **Fragment** | one raw source chunk — *the context* | `claim_chunks`, keyed by `chunk_id` (UUID) |
| **Chunk Handle** | a short, session-scoped alias for a Fragment (`F1`…), issued by the read tools | in-process map (§10-C) |
| **Enrichment Record** | one grounded extracted fact or interpretation — *the data* (what this tool writes) | `enrichment_records` |
| **Evidence Span** | the exact substring of a Fragment, **sliced by code**, that grounds a record | `enrichment_records.evidence_span` |
| **Provenance** | `{chunk_id, char_start, char_end, page, document}` — all **code-derived** | columns on the record |
| **Provenance Validation** | the immutable attestation a record passed grounding: verdict + judge identity + content hashes + time | `enrichment_records.provenance_validation` (jsonb) |
| **Grounding Verdict** | the judge's ruling that the Evidence Span supports the claim | inside `provenance_validation` |
| **Tier** | `fact` (must be literally grounded) \| `interpretation` (inference that cites facts) | `enrichment_records.tier` |
| **Codex** | the structured **index** over the corpus — normalized **Entities** + cross-record **Links**. NOT raw context, NOT the records: *the navigable map.* | `codex_entities` + `enrichment_links` (sibling deliverable) |
| **Entity** | a normalized date / event / actor that records *point at*, shared **across** record schemas | `codex_entities` |
| **Link** | a cross-record relation (temporal / causal) | `enrichment_links` (written by `link_events`) |

**Three tiers:** **Fragment** (raw context) → **Enrichment Record** (grounded fact) → **Codex**
(the index: Entities + Links). _"Codex Entry" is retired_ — it conflated the index with the records.
The Codex is precisely the layer where a date in one record and the same date in another resolve to
**one Entity**, and where events link across pages — the cross-schema context-sharing the design
needs.

## 3. The corruption-proof design — defenses in order
1. **The model points; it does not transcribe the id.** Read tools return Fragments tagged with a
   short **Chunk Handle**; `write_enrichment` takes the *handle* — or, in per-Fragment passes, **no
   chunk reference at all** (the orchestrator sets the "current Fragment"). Code resolves handle →
   canonical `chunk_id`. A 1–2 char handle is far harder to corrupt than a 36-char UUID; a corrupted
   handle resolves to a *different real Fragment* whose text won't support the claim → caught at (3).
2. **Code slices the Evidence Span; the model never quotes the source.** The model supplies integer
   `char_start`/`char_end`; code does `fragment_text[char_start:char_end]`. The stored quote is
   **byte-exact from the corpus**.
3. **The judge verifies the claim against the code-sliced span.** Qwen2.5-14B catches a wrong handle,
   bad offsets, fabricated claims, and **value drift** (`reversal`→`reversible`, `03-30`→`03-29`).
4. **The record attests.** The passing result is frozen into `provenance_validation` — verdict,
   judge identity, and **content hashes of the Evidence Span and the Fragment** — making each record
   self-verifying, tamper-evident, and immutable.

**Net: no path exists by which a model-typed exact token reaches storage unchecked or unattested.**

## 4. Payload — what the MODEL provides (and what it must NOT)
```jsonc
{
  // WHICH Fragment — reference mode (Pass 3 / multi-Fragment). OMIT in per-Fragment mode (§10-A).
  "chunk_handle": "F3",
  // WHERE in it — the model POINTS; code slices:
  "char_start": 412,
  "char_end":   487,
  // WHAT was found — the model's real job (reasoning; judge-checked):
  "record_type":     "status_change",   // controlled vocab once Pass 1 curates the emergent schema
  "tier":            "fact",            // fact | interpretation
  "fields":          { },               // jsonb — structured meaning, shape per record_type
  "actor":           "B. Smith",        // judge-verified vs span; resolved to a Codex Entity
  "event_date":      "2025-02-18",      // normalized; judge-verified vs span; resolved to a Codex Entity
  "claim_relevance": "…",               // why it matters to the denial (usually tier=interpretation)
  "confidence":      0.9
}
```
**NOT in the payload:** `chunk_id`, `page`, `document`, `evidence_span` text, the hashes — all are
**code's job**. An optional echoed `chunk_id` is allowed only as a redundant cross-check, never as
the source of truth.

## 5. Validation pipeline — ordered; short-circuit on first failure; the record is **write-once**
1. **Resolve Fragment** — handle → canonical `chunk_id`, or orchestrator's current Fragment. Miss → `REJECT unknown_fragment`.
2. **Load Fragment** from `claim_chunks`. Miss → `REJECT fragment_not_found`.
3. **Bounds-check** — `0 ≤ char_start < char_end ≤ len(fragment_text)`. Else → `REJECT bad_offsets`.
4. **Slice Evidence Span** = `fragment_text[char_start:char_end]` (CODE). Empty/whitespace → `REJECT empty_span`.
5. **Grounding judge** — Qwen2.5-14B on `(claim, evidence_span, tier)` → **Grounding Verdict**.
6. **Tier gate** — `fact` & verdict≠`grounded` → `REJECT ungrounded_fact` (name failing values);
   `interpretation` & `ungrounded` → `REJECT unsupported_interpretation`; `partial` → `flagged=true`.
7. **Derive provenance** entirely from the Fragment — `source_chunk_id`, `page`, `document`. Never from the payload.
8. **Compute Provenance Validation** — `{ verdict, judge_model, judge_version, evidence_sha256,
   source_sha256, validated_at }`. The hashes freeze the exact bytes this record was grounded against.
9. **Resolve Codex Entities** — normalize the **judge-validated** `actor`/`event_date` and
   register-or-resolve them in `codex_entities`; the record stores Entity refs. (Cross-boundary
   sharing. *Links* between records are `link_events`' job, not this tool's.)
10. **Write** the Enrichment Record (provenance + judge-passed meaning + provenance_validation +
    entity refs + handle trace) — immutable.
11. **Return** (§6).

## 6. Return contract
- **Success:** `{ ok:true, record_id, source_chunk_id, evidence_span, provenance_validation }`
- **Rejection:** `{ ok:false, reason_code, detail }`,
  `reason_code ∈ { unknown_fragment, fragment_not_found, bad_offsets, empty_span, ungrounded_fact,
  unsupported_interpretation, schema_invalid }`. `detail` is agent-readable **so the agent fixes and
  retries by re-pointing — never by re-transcribing. The rejection IS the feedback loop.**

## 7. DB write (`enrichment_records` — DDL lives in `schema/`; SCOPE.md §8)
Tool sets: `record_type, tier, fields(jsonb), actor, event_date, claim_relevance, confidence,
source_chunk_id, char_start, char_end, page, document, evidence_span, provenance_validation(jsonb),
entity_refs(jsonb), flagged, created`. **Provenance + hashes are code-derived.** Records are
**write-once** (immutable); corrections are new records that supersede, never in-place edits. The
**Codex** tables (`codex_entities`, `enrichment_links`) are a sibling deliverable.

## 8. The grounding judge call (the heart)
- **Model:** Qwen2.5-14B-Q6 on the `judge` lane (`:8082`) via LiteLLM (SCOPE.md decision #3).
- **Tier-aware prompt:** `fact` → "Is EVERY asserted value (actor, date, each field) literally
  supported by this span? grounded/partial/ungrounded + name any value that fails." `interpretation`
  → "Reasonable inference from this span? Need not be literal, must not contradict it."
- **Output:** structured `{ verdict, failing_values:[], reason }` (force/parse defensively).
- The judge sees the **code-sliced** span — never the model's prose.

## 9. Tests — TDD, write these FIRST; they are the acceptance criteria (SCOPE.md §15)
1. **Happy path** — valid handle + offsets over a real fact → grounded → written; stored
   `evidence_span` byte-identical to the corpus slice; `source_chunk_id` canonical.
2. **🔴 The 89503 regression** — model passes a digit-mangled chunk reference → wrong/no Fragment →
   REJECT or judge-bounce. **Storage never contains the corrupted id.**
3. **Date-drift** — `event_date` 2025-02-18, span says the 19th → `REJECT ungrounded_fact`,
   `failing_values=[event_date]`.
4. **Word-drift** — claim "reversal", span supports nothing reversed → ungrounded.
5. **Bad offsets** — `char_end > len` → `REJECT bad_offsets` (no judge call, no write).
6. **Fabrication** — `fields` assert a fact absent from the span → ungrounded.
7. **Interpretation tier** — grounded-but-not-literal → stored; contradicts the span → bounced.
8. **Span is code-sliced** — a payload-supplied `evidence_span` is ignored in favor of the code slice.
9. **🔒 Provenance Validation integrity** — `evidence_sha256 == sha256(stored evidence_span)` and
   `source_sha256 == sha256(fragment_text)`; and tamper-evidence: mutating the source row later makes
   `source_sha256` mismatch, detectable on audit.
10. **Entity resolution** — `actor`/`event_date` resolve to an existing Entity when one exists (no
    duplicates), create when new; the record stores correct `entity_refs`.

Each test states what it proves. **Coverage/recall is a *pass-level* acceptance metric (SCOPE.md §6),
not a unit test: too-sparse fails as hard as false-info.**

## 10. Decisions — RESOLVED 2026-06-14 (Joe)
- **A. Fragment reference mode → BOTH.** ✅ Per-Fragment passes (Pass 2): orchestrator-set current
  Fragment, model gives *zero* chunk refs. Cross-link pass (Pass 3): handles.
- **B. Judge structured-output → Engineer's call** ✅ (JSON mode vs grammar vs parse-retry; flag the choice).
- **C. Session handle-map → in-process, keyed by workstream id** ✅ (revisit if multi-node).
- **D. Cross-boundary sharing → the Codex layer.** ✅ Dates/events/names become shared **Entities**
  records point at; `link_events` writes cross-record **Links**. Factor pipeline steps 1–6 (the
  grounding core) into a shared component both `write_enrichment` and `link_events` call.
- **E. Naming → Fragment / Enrichment Record / Codex.** ✅ "Codex Entry" retired; table stays
  `enrichment_records`; **Codex** = the index (Entities + Links), its own sibling contract.

**Follow-on deliverables (not blockers):** the **Codex contract** (`codex_entities`,
`enrichment_links`, `link_events`, entity-normalization rules); the `schema/` DDL; the shared
grounding-core module (D).
