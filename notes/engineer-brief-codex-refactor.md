# Engineer Brief — Refactor the Multipass Enrichment Harness to the Meaning↔Codex Architecture

_Authoritative implementation brief. Architect → Engineer. Build TDD, test-first, throughout. Edit `/Users/yummyfudge/Projects/reliquary_enrichment` ONLY. The sibling `/Users/yummyfudge/Projects/context_reliquary` is the Phase-1 product and has an UNRELATED, identically-named `CodexEntry` — do not touch it._

> **Path convention.** Bare filenames in this brief (`write_enrichment.py`, `entities.py`, `stores.py`, `models.py`, `mcp.py`, `link_events.py`, `read_tools.py`) live under **`src/reliquary_enrichment/`** (the top-level package). Sub-path names (`postgres/record_store.py`, `multipass/cli.py`, `probe/schema.py`, `passes/...`) are also under `src/reliquary_enrichment/`. Only **`schema/`** and **`probe/slice/`** are at repo root. All line numbers below are verified against commit `794d715`.

---

## 1. Framing

This is a **wire-up + Pass-5 rewrite, not a rebuild.** The codex infrastructure — entities, links, the grounding spine, the schema, the §5 isolation harness — is already built and audition-proven. The link layer (`link_events.py`) is fully built and **orphaned**: no pass calls it. The job is to (a) replace the untyped lexical passes with typed closed-vocabulary entity extraction, (b) wire the orphaned linker in, (c) rewrite Pass 5 from whole-claim-significance to a thin local-fact meaning, and (d) enforce the bright line physically in storage.

Build every step test-first. The grounding law is inviolable throughout: **the model POINTS (a quote/span), code COPIES (slices the bytes), the judge CHECKS (verdict over the code-sliced span), the row ATTESTS (hashes frozen).** Never free-type an id; use the `HandleMap` / record-ref discipline. Every file gets a terse doc header (what it is, why it exists — SCOPE §15).

---

## 2. Why (the audition surfaced this gap)

The multipass framework works — `pipeline.py` drives passes with a glass-box + heartbeat; `pass_base.py`'s injected `Completer`/`ModelClient` carries the audition-2 hardening (big `max_tokens`, 600s deadline, thinking-off); the `grounding/` spine grounds every write; the §5 isolation harness (throwaway `probe_<label>` schema, raw-export-before-drop, never-drop-unscored, prod-untouched proof) is solid. **The framework is not the problem.**

The problem is **what the passes produce.** Today's passes 2/2.9/3/4/4.9 emit **untyped lexical bags** (`pass4_keywords.py` produces keyword lists; `pass2_9_consolidate.py` invents an open-vocabulary type schema per run) and Pass 5 (`pass5_meaning.py`) writes a **whole-claim-significance meta-description** plus `questions_answered`. None of that is the lever. **CRQ-001 proved retrieval-tuning alone cannot surface the gold note** (`89503c71-5ca2-424b-9386-6698a8337dc3`, line 71 of the 131-chunk slice): the generic terms that bury it (Long COVID, "the claim", the claimant) **are the ubiquitous themes**. The fix is enrichment that produces *typed, normalized, discriminative-weighted entities + grounded cross-chunk links* (the codex an agent walks), and a *small, local, discriminative meaning* (the only embedded artifact).

**Codex-first sequencing:** entities must exist BEFORE meaning is written, so the meaning's key nouns are guaranteed-real, followable codex entities (the hook-resolution check, §10).

---

## 3. Target architecture

### 3.1 The bright line (physical, enforced in storage)

| | **MEANING** | **CODEX** |
|---|---|---|
| What | small, LOCAL, standalone-FACT natural language per chunk | typed NORMALIZED entities (`actor`/`date`/`event`/`document`/`provision`/`code`/`location`) + cross-chunk LINKS |
| Embedded? | **YES** — Qwen3-Embedding-8B, 4096-dim. **The ONLY embedded artifact.** | **NEVER embedded.** |
| Job | RETRIEVE the right chunk. Discriminative; scoped to what THIS fragment literally says. | The structured joins an AGENT walks at QUERY time to assemble the larger answer. |
| Forbidden | "this chunk indicates…" meta-description; whole-claim significance | being embedded; ever holding raw context |
| Table | `enrichment_meaning` (the `embedding` column is the only embedded column anywhere) | `codex_entities` + `enrichment_links` |

Do **not** embed the larger context. The larger answer is *assembled at query time by walking the codex*, not packed into a vector.

### 3.2 Codex-first

Entities are extracted and normalized **before** meaning is written. The meaning pass then writes a local fact whose nouns are *those resolved entities* — and a hook-resolution check (§10) flags any meaning whose key nouns don't resolve to ≥1 codex entity on the chunk's records.

### 3.3 Signal/noise = discriminative weight

After normalization, compute each canonical entity's **discriminative weight = the count of distinct chunks it appears in** (deterministic, code, **no LLM**). This is the real job the old keyword pass missed:

- **RARE** (few chunks) = a discriminator/locator/join-key — `B. Smith`, `F06.4`, a specific date. **HIGH-RECALL — must not miss.**
- **UBIQUITOUS** (most chunks) = a **THEME** — Long COVID, the claimant, "the claim". One node, **flagged as theme, kept-never-deleted**, **excluded as a sole link join-key (the linking stoplist)**, and **down-weighted as a discriminator.**

**No named buckets.** Type + weight give every bucket on demand; the agent groups at query time. Theme cutoff is a **tunable knob** (a spectrum, not a binary). Rarity applies to **grounded typed entities only**. This IS the CRQ-001 lever.

---

## 4. PRE-FLIGHT (step 0 — do these FIRST, before any pass code)

1. **Pin the repo.** Confirm `requires-python = ">=3.12"` and the package builds; record the working commit (`794d715`) as the **v0 baseline tag** before refactoring. The first refactored scored run is a NEW baseline (artifact shape changes); v0 is archived; the **gold-note floor** (§10) is the continuity anchor across both.

2. **Confirm `segment_index` vs `char_start_offset` adjacency (DB check).** `postgres/fragment_reader.py` `neighbors()` (`_NEIGHBORS`, lines 26-37) orders by `segment_index` with an explicit flagged NOTE to confirm vs `char_start_offset`. Document-adjacency candidate links (§8) depend on this being the true intra-document ordering key. Run a **read-only** query against `context_reliquary.claim_chunks` for a couple of documents, compare `ORDER BY segment_index` vs any `char_start_offset`/offset column, and **resolve the NOTE before adjacency links rely on it.** If `segment_index` is not the ordering key, fix `_NEIGHBORS` first.

3. **Add the `+location` migration (additive).** `schema/002_codex_entities.up.sql` line 20 `CHECK (entity_type IN ('actor','date','event','document','provision','code'))` is **MISSING `location`**. Add a new **additive** migration `schema/006_codex_entities_add_location.up.sql` (+ `.down.sql`) that drops and re-adds `codex_entities_type_chk` with `location` included. Mirror the same enum into the probe DDL `_tables_ddl` in `probe/schema.py` (the `entity_type IN (...)` check). Do **not** rewrite 002 in place — it's already applied to prod; **D3 = additive only**.

---

## 5. KEEP / CHANGE / THROW / ADD (file-level)

### 5.1 KEEP (untouched — audition-proven)

- **Driver + glass-box + heartbeat** — `multipass/pipeline.py` (the `_heartbeat`, per-pass persist; **passes run in strict list-index order**, `for p_idx, p in enumerate(self._passes)`, line 60 — this invariant is load-bearing for §7).
- **Pass ABC** — `multipass/pass_base.py` (`Pass`, `per_chunk`, `process_chunk`/`process_all`).
- **`ModelClient`/`Completer`** — `pass_base.py` (big `max_tokens`, 600s deadline, thinking-off `extra_body`).
- **Loaders + slice-wins dedup** — `multipass/inputs.py`.
- **`ConfidencePlateau`** — `multipass/confidence.py`.
- **Pass 1 prose/non-prose classifier** — `passes/pass1_prose.py`.
- **`GroundingCore`** point/slice/judge/attest — `grounding/core.py`; **fail-closed judge** — `grounding/judge.py`.
- **`Fragment`/`FragmentReader`** single-slice-source — `grounding/fragments.py`.
- **`HandleMap`** — `grounding/handles.py`.
- **`WriteEnrichment` spine** — `write_enrichment.py` (steps 0-11; the point→copy→check→attest pipeline). Two surgical edits only (§5.2): `_resolve_entities`, and the `claim_relevance` removal.
- **`EntityResolver` resolve-or-create + aliases-not-silent-merge + `EventMaterializer` union-find** — `entities.py` (canonicalizers added, §5.2; the contracts untouched).
- **`LinkEvents`** — `link_events.py` (fully built, write-once, no-self-link, dual-hash, one-link-per-call, `same_event` materializes the Event). **UNTOUCHED — including its deliberate accept-unknown-relations contract** (lines 26-31: "new relations are EXPECTED… unknown relations are accepted, not hard-rejected"). See §5.2 validator note.
- **Postgres connection + `qualified()` guard** — `postgres/connection.py`.
- **Schemas 001/002/003/004/005** — keep; 002 gains `location` via additive 006; 004 changes via additive 007 (§5.2). Write-once `forbid_mutation` triggers + grant layer — keep.
- **ALL of §5 isolation** — `probe/schema.py` (throwaway `probe_<label>`), `claim_chunks` read-only, `probe/export.py` (raw-export-before-drop), never-drop-unscored + prod-untouched proof in `multipass/cli.py` (`execute_multipass` finally-block, `_isolation_unchanged`/`prod_enrichment_counts`). **Stays untouched throughout** (the export/probe-DDL files gain additive columns/tables per §5.2/§6, but the isolation mechanism is untouched).
- **`GateReading` mechanism** — `multipass/gate.py` (the dataclass + `read_gate` shape; semantics change, §5.2).
- **Grounding types/`Tier`** — `grounding/types.py`; **`safe_json_*` never-raise floor** — `multipass/parsing.py`.

### 5.2 CHANGE (file-level)

- **`passes/pass5_meaning.py` → thin LOCAL-FACT meaning, AFTER chunk entities.** Rewrite `_SYSTEM` (lines 16-21) to **forbid the meta-phrase family** ("this chunk indicates/shows/reflects/documents…", "the significance to the claim/denial is…", "this is important because…") **and whole-claim significance**, and to **demand a small standalone dated fact whose nouns are the chunk's resolved entities** (e.g. "On 2025-02-18, B. Smith placed the claim back to the Mental Health limitation."). **Drop `questions_answered`** (delete from `_SYSTEM`, `parse_meaning`, and the returned dict). Meaning is GROUNDED at `Tier.INTERPRETATION` via the **new `MeaningWriter`** (§5.4) and persisted to `enrichment_meaning` — **not** through `WriteEnrichment`. `per_chunk` stays `True`; it runs AFTER `EntityNormalizationPass` so resolved entities are in `prior`.

- **`passes/pass2_9_consolidate.py` → entity-normalization** (renamed file `pass2_9_normalize.py`, class `EntityNormalizationPass`, `per_chunk=False`). The 2.9 SLOT becomes deterministic entity normalization, **not** open-vocab type-merge. **THROW the open-vocab type-merge MECHANISM + silent-identity fallback** (`parse_consolidation` lines 25-50; the `mapping.setdefault(t, t)` sprawl 45-49). New behavior: deterministic canonicalizers run **FIRST** (date→ISO, identifier/code canonical, actor-name), LLM only for **residual ambiguous alias merges**, **flag-don't-silent-merge** (route to curation, never collapse on uncertainty). **Keep the raw/final/mapping glass-box output shape** — but now `mapping` is `surface → entity_id`, not `raw_type → canonical_type`.

- **`passes/pass2_objecttypes.py` + `passes/pass3_fillvalues.py` + `fill_wiring.py` → MULTI-record typed entity INSTANCES over the FIXED closed vocab.** Every date/actor/event/code/location/document with its own verbatim quote becomes a record. **Keep the propose/ground/judge-feedback/`ConfidencePlateau` loop verbatim** (`Pass3FillValues.process_chunk` lines 47-66). **THROW the single-record-per-chunk assumption** in `fill_wiring.py` (the "v0 simplification: one record per chunk" comment + single-proposal `make_proposer`/`make_grounder`): the proposer now emits a **list** of typed-entity proposals, the grounder grounds **each** (one `write_enrichment` call per proposal), and the plateau/feedback loop wraps the per-chunk batch. Pass 2 names the **closed-vocab types present** (from the vocabulary module, §5.4).
  - **DATA-FLOW REWIRE (mandatory).** Currently `Pass3FillValues.process_chunk` reads its schema from `prior["2_9_consolidate"].outputs.get("final")` (lines 35-38). Since normalization (2.9) now runs **after** Pass 3 (§7), Pass 3 **must no longer read `prior["2_9_consolidate"]`.** Pass 3's "schema" input becomes the **closed vocabulary from `vocabulary.py`** (the fixed taxonomy), optionally narrowed by **Pass 2's own per-chunk typed-types output** (`prior["2_objecttypes"]`). Replace the lines-35-38 read accordingly. Pass 3 depending on a pass that runs later is the bug this rewire prevents.

- **`WriteEnrichment._resolve_entities`** (`write_enrichment.py` lines 223-235) → **resolve EVERY typed entity**, not just `actor`/`event_date`. Today it only resolves `actor` and `event_date`. Extend so a record's `fields`-carried typed entities (code, location, document, provision) each `resolve_or_create` and append an `EntityRef`. Keep `EntityRef.role`/`entity_type` discipline (`models.py` lines 15-30); extend `role` beyond `"actor"|"event_date"`.

- **`EntityResolver`** (`entities.py`) → **add per-type canonicalizers.** Today `_NORMALIZERS` (line 32) is `{"actor": normalize_actor, "date": normalize_date}`, both near-identity (lines 22-29). Add real canonicalizers: `date → ISO-8601` (`Feb 18 2025`/`02/18/2025`/`2025-02-18` → `2025-02-18`, flag-on-ambiguity not silent-guess), `code → canonical` (`f06.4` → `F06.4`, whitespace/punctuation-normalized), `location → canonical`, `document → canonical`, and a stronger `actor` name canonicalizer (still **alias-not-merge** on variant ambiguity per `resolve_or_create` lines 57-60). Keep `resolve_or_create`'s aliases-not-silent-merge contract verbatim.

- **`multipass/gate.py` coverage → discriminative-substance.** `read_gate` (lines 29-50) currently counts a chunk faithful iff Pass 3 grounded **anything**. Change so a grounded-but-trivial record (e.g. a grounded `"Cheers, Joe"` sign-off) does **NOT** count toward faithfulness — coverage means **grounded discriminative substance** (≥1 grounded record carrying a **non-theme** typed entity or a concrete dated action). Keep the `GateReading` dataclass shape. _Depends on the theme-flag (§9); build-order slot §11._ Separate from the HARD discriminativeness gate on the meaning write path (§5.4 #7) — **that one REJECTS; this one measures.**

- **004 → `claim_meaning` semantics + constraints.** Add **additive** migration `schema/007_enrichment_meaning_local_fact.up.sql` (+`.down.sql`): **ADD `UNIQUE(source_chunk_id)`** (one meaning per chunk) and **ADD FK `source_chunk_id → claim_chunks.claim_chunk_id`** (mirror 005's optional-FK pattern). **Drop `questions_answered`** (acceptable here — nothing reads it after the review change). Update the 004 header comment's "interpreted significance" wording to **local fact**. Do not rewrite 004 in place.

- **`PassContext.extras` → typed slots (ADDITIVE).** `pass_base.py` `PassContext.extras` (line 101) is a free dict; today `cli.py` (lines 100-101) populates `{"proposer": proposer, "grounder": grounder}` and Pass 3 reads `ctx.extras["proposer"]`/`["grounder"]` (lines 39-40). **Keep `proposer` + `grounder` keys — Pass 3 still needs them.** **ADD alongside** stable keys for: `entity_store`, `entity_resolver`, `linker` (`LinkEvents`), `meaning_writer`. Document them all in the dataclass docstring. `execute_multipass` populates **all** slots in the same extras dict. Keep injection-for-testability.

- **`stores.py` → ADD READ APIs (protocol + Postgres impl + fakes, same commit).** Today the protocols expose only `insert`/`find`/`get`/event-cluster ops; `EntityStore` has **no `get(entity_id)` and no `entities_of_type`**, and mutation is only `add_alias`/`set_event_members`/`mark_event_merged`. **ADD:**
  - `EntityStore.get(entity_id) -> Entity | None`
  - `EntityStore.entities_of_type(entity_type) -> list[Entity]`
  - `EntityStore.set_entity_flags(entity_id, *, weight: int, is_theme: bool) -> None` — the **only** post-insert metadata mutation besides event clustering; writes `weight`+`is_theme` into `metadata` (jsonb on Postgres via `jsonb_set`; dict patch on the fake). This is the discriminative-weight write path (§9); without it the theme-flag cannot persist.
  - `EnrichmentRecordStore.records_by_entity(entity_id) -> list[EnrichmentRecord]`
  - `EnrichmentRecordStore.chunks_by_entity(entity_id) -> list[str]` (distinct `source_chunk_id`s — the discriminative-weight count)
  - `EnrichmentRecordStore.cooccurrence(entity_id) -> dict[entity_id, int]` (entities sharing a record/chunk)
  - `LinkStore.links_for_record(record_id) -> list[Link]` / `LinkStore.neighbors_via_links(record_id) -> list[(relation, record_id)]`
  - **IMPLEMENTATION LANDMINE (entity→record reverse lookup).** `entity_refs` is **denormalized jsonb on `enrichment_records`** (`record_store.py` line 50 writes `json.dumps([r.as_dict() for r in record.entity_refs])`; `models.py` carries them on the dataclass — there is **no normalized join table**). So `records_by_entity`/`chunks_by_entity`/`cooccurrence` must be **jsonb-containment queries** (`entity_refs @> '[{"entity_id": ...}]'`), not FK joins. Add a **GIN index on `entity_refs`** in the probe `_tables_ddl` (`probe/schema.py`) so the discriminative-weight pass over 131 chunks is not a per-entity full scan; for prod add it as **additive migration `schema/008_entity_refs_gin_index.up.sql`** (+`.down.sql`). Add the GIN-index DDL to the probe-schema changes already listed in §6.
  - **Fake parity:** add all of the above to `FakeRecordStore`/`FakeEntityStore`/`FakeLinkStore` (`tests/fakes/fake_stores.py`) **in the same commit**, so the discriminative-weight (step 6) and walker (step 9) unit tests can go red→green against fakes.

- **`parsing.py` → ADD typed validators (never-raise floor preserved).** Keep `safe_json_array`/`safe_json_object`. **ADD:**
  - `validate_entity_proposal(obj) -> EntityProposal | None` — `type ∈ closed vocab` (`vocabulary.ENTITY_TYPES`), has a verbatim `quote`, has a canonical surface. Reject-to-`None` on shape failure.
  - `validate_link_proposal(obj) -> LinkProposal | None` — **ADVISORY ON RELATION, matching `link_events.py` lines 26-31.** Require structural shape (`record_a`/`record_b`/`a_span`/`b_span`/`rationale` present) → reject-to-`None` only on **structural** failure. For the relation: **accept any non-empty string**; set `emergent = True` (and optionally a `off_seed` advisory flag) when the relation is not in `vocabulary.SEED_RELATIONS`. **Never reject on relation vocabulary** — that would be stricter than the grounding boundary it feeds, and `link_events.py` stays untouched. The §10.1 unit test asserts "**flags** off-seed relation, does **not** reject it."

- **`SCOPE.md` + 002 enum + `review.py`.** Update SCOPE §8 (meaning = local fact, not significance) and the three-tier ontology note to reflect codex-first + discriminative weight; the enum change rides 006. In `multipass/review.py` (full blast radius — the pass4/2.9 changes break more than the meaning lines):
  - **re-render meaning as a local fact** (line 88 `- meaning:`).
  - **REMOVE `questions_answered` render** (lines 89-90) and the `5_meaning` progression handling at line 100 (re-render as local fact, no answers).
  - **REMOVE keyword renders** (pass4/4.9 deleted): the header `keyword vocabulary (4.9 final)` (line 58, reads `cleanup.get('final')`), the per-chunk `- keywords:` line (line 86, reads `cleaned`), and the `4_keywords→cleaned` progression line (line 99). Also drop the `cleanup`/`cleaned` loads (lines 34, 38).
  - **REWIRE the 2.9 renders** (the old open-vocab `final`/`mapping` keys are gone): the header `consolidated object-type schema (2.9 final)` (lines 56-57, reads `consolidate.get('final')`), and the per-chunk `canon = {mapping.get(t, t) for t in raw_types}` + `object-types → canonical` render (lines 72, 75). Either re-point them at the new 2.9 `surface→entity_id` mapping or fold them into the new CODEX section.
  - **ADD a CODEX section** per chunk: resolved entities by type + weight + theme-flag, and the links touching the chunk's records.

### 5.3 THROW (entirely)

- **`passes/pass4_keywords.py`** + **`passes/pass4_9_cleanup.py`** — delete both. Untyped lexical bags; their content becomes typed entities (§5.2 Pass 2/3) + the theme-flag (§9). Remove from `all_passes()` in `multipass/cli.py` (lines 31-32 imports; lines 49-50 the list literal `Pass4Keywords()`, `Pass4_9Cleanup()`).
- **The Pass 2.9 open-vocab type-merge MECHANISM + silent-identity fallback** — `parse_consolidation` sprawl (`pass2_9_consolidate.py` lines 25-50). The SLOT survives as entity-normalization (§5.2).
- **`questions_answered`** — Pass 5 output, the 004 column, the review render. Gone everywhere.
- **The whole-claim-significance CONTRACT** — `pass5_meaning.py` `_SYSTEM`/scope, the 004 "interpreted significance" comment. Replaced by local-fact.
- **`claim_relevance` from the enrichment_records path** — **DECIDED**: it is whole-claim significance relocated to the fact store. **The full touch-point list (the literal-execution build-breakers):**
  - `write_enrichment.py` — `_Payload`/`_validate`/`render_record_claim`/the record build (lines 42, 90, 104-105, 130-131, 200, 224). **NOTE the `render_record_claim` consequence (§below).**
  - `models.py` — the `claim_relevance` field on `EnrichmentRecord` (line 51).
  - `mcp.py` — the tool signature (line 100) and payload (line 117).
  - **`postgres/record_store.py`** — INSERT column-list (lines 24/26), VALUES placeholder (line 29), param dict (line 41 `record.claim_relevance`), SELECT projection (lines 64/66), and the `claim_relevance=row["claim_relevance"]` reconstruction (line 84). **KEEP the `enrichment_records.claim_relevance` column** (additive discipline — don't drop a prod column), but **bind a literal `None`** in the INSERT param dict (`"claim_relevance": None`) and **drop `claim_relevance` from the SELECT projection + the `EnrichmentRecord(...)` reconstruction** (since the dataclass field is gone). Do **not** read `record.claim_relevance` — the attribute no longer exists.
  - **`probe/export.py`** — drop `claim_relevance` from the `_load` SELECT (lines 26-27), the `records.jsonl` dict (line 59), and the `records.txt` render (lines 98-99). (Harmless-but-stale otherwise; the column is now always NULL.)
  - **ORDER (so the build never has a dangling `record.claim_relevance` read):** edit `record_store.py` + `export.py` + `write_enrichment.py` + `mcp.py` to stop referencing the field **FIRST**; remove the `models.py` dataclass field **LAST**.
  - **`render_record_claim` behavioral note:** removing the relevance branch (lines 130-131) means a pure-interpretation record with no `actor`/`date`/`fields` now falls through to the degenerate `"the span records a {record_type} event"` branch (lines 132-134). This is **acceptable** for typed-entity interpretation records — but **require ≥1 field/entity on every interpretation record** so the degenerate branch is effectively never the judge's input for a real entity record. State this in the Pass 3 proposer contract.
  - **Invariant test (§5.3/§10):** (a) nothing outside `enrichment_meaning.embedding` is ever embedded; (b) `enrichment_records.claim_relevance` is `NULL` for every row a refactored run writes (proves the relocation, not just the no-embed invariant).
- **The single-record-per-chunk assumption** — `fill_wiring.py` (§5.2).

### 5.4 ADD (new modules — built in §11 order)

1. **Closed VOCABULARY MODULE** — `multipass/vocabulary.py`. Single source of truth: `ENTITY_TYPES = frozenset({"actor","date","event","document","provision","code","location"})` (the 002+006 enum) and `SEED_RELATIONS` (**re-export from `link_events.SEED_RELATIONS`** — `precedes/follows/causes/results_from/corroborates/contradicts/elaborates/same_event/references`). **Built FIRST.** Every pass and validator imports the taxonomy from here; `len(ENTITY_TYPES)` (7) is the sprawl-regression bound (§10).
2. **`EntityNormalizationPass`** — `passes/pass2_9_normalize.py`, `per_chunk=False` (the 2.9 slot). Deterministic canonicalizers first, LLM residual-only, flag-don't-merge, glass-box raw/final/mapping over `surface→entity_id`.
3. **`CrossChunkLinkPass`** — `passes/pass_link.py`, `per_chunk=False`. Wires the orphaned `LinkEvents`. Bounded candidate-gen (§8) → propose → `LinkEvents.link()` grounds each. Runs after entities exist and after discriminative-weight (it needs the stoplist).
4. **`MeaningWriter` + `render_meaning_claim`** — `meaning_writer.py` (top-level package, SEPARATE from `write_enrichment.py`, embedded side). Grounds the local-fact meaning at `Tier.INTERPRETATION` via the shared `GroundingCore`, runs the meta-phrase pre-filter + hard discriminativeness gate + hook check, persists to `enrichment_meaning`. `render_meaning_claim` mirrors `render_record_claim` (the values the judge checks). **Never** routes through `WriteEnrichment`/`enrichment_records`.
5. **Discriminative-WEIGHT computation + theme-flag** — `multipass/discriminative.py`, post-normalization, per canonical entity: `weight = len(record_store.chunks_by_entity(entity_id))`; `is_theme = weight >= theme_cutoff` (tunable knob, calibrated §9). Persist via `EntityStore.set_entity_flags(entity_id, weight=..., is_theme=...)`. Theme entities are **kept never deleted**, **added to the linking stoplist**, **down-weighted as discriminators.** Deterministic, no LLM.
6. **Two-artifact persistence sink** — `persistence.py` (or extend the CLI wiring). meaning → `enrichment_meaning` (via `MeaningWriter`); codex → `codex_entities` + `enrichment_links` (existing stores). **Physical separation enforces the bright line.** Add an `EnrichmentMeaningStore` protocol + Postgres impl (`postgres/meaning_store.py`) — the **only** writer of the `embedding` column.
7. **HARD discriminativeness/substance GATE on the meaning write** — inside `MeaningWriter`. Grounds-clean **but** no discriminative (non-theme) entity / no concrete dated action → **REJECT, not flag.** Calibrate against a **trivia-vs-substance fixture BEFORE the first scored run** (the `"Cheers, Joe"` negative, §10).
8. **Hook-resolution check on `MeaningWriter`** — **deterministic definition (so it is testable):** key nouns = the **resolved-entity surface set the MeaningWriter was handed for this chunk** (canonical + alias surfaces of the chunk's grounded entities), matched **case-insensitively** against the rendered meaning string. **Flag `meaning-hook-unresolved`** iff the rendered meaning contains a **capitalized multi-token span or date-like token** that matches **NONE** of the chunk's resolved entity surfaces. **Flag, don't reject** (the meaning may be right but the codex incomplete; surfaces the gap). **No NER** — that breaks the model-agnostic seam.
9. **Codex READ API / agentic-assembly walker** — `codex_walk.py` (or extend `read_tools.py`). The query-time walker: from a seed (chunk or entity) → `entities_of` chunk → `records_by_entity` → `links_for_record`/`neighbors_via_links` → neighbor records, each hop returning its grounded evidence span. **Sequenced BEFORE declaring linking done** (§10 AGENTIC ASSEMBLY is its acceptance).
10. **Meta-phrase regex pre-filter** — in `MeaningWriter`, cheap, **ahead of the judge.** Rejects the meta-phrase family before spending a judge call. Calibrated against the rewritten `_SYSTEM`.
11. **Meaning-embed/needle step** — `needle.py` (DEFERRED build, specced): embed `enrichment_meaning.claim_meaning` in Qwen3 4096-dim, **brute-force exact search** (ANN deferred — pgvector caps at 2000 dims; 4096 exceeds it, per the 004 header note). Re-run CRQ-001 with baselines RE-MEASURED in Qwen3-4096.

---

## 6. Persistence model (the bright line, in tables)

| Table | Written by | Embedded? | Migration |
|---|---|---|---|
| `enrichment_records` | `WriteEnrichment` (multi-record typed instances) | no | 001 (keep; `claim_relevance` column retained, bound `NULL`); **008 (GIN on `entity_refs`)** |
| `codex_entities` | `EntityResolver` (resolve-or-create) + `EventMaterializer` (`same_event`) + `set_entity_flags` (weight/theme) | no | 002 + **006 (+location)** |
| `enrichment_links` | `LinkEvents` (one grounded link per call) | no | 003 (keep) |
| `enrichment_meaning` | **`MeaningWriter` / `PostgresEnrichmentMeaningStore` ONLY** | **`embedding` column — the ONLY embedded artifact** | 004 + **007 (UNIQUE(source_chunk_id), FK, drop `questions_answered`)** |

**Probe DDL disposition (explicit, for the deterministic structure test §10.2).** The probe schema is recreated fresh each run from `probe/schema.py` `_tables_ddl`, so it may diverge from prod freely:
- **DROP the `claim_relevance` column** from the probe `enrichment_records` DDL (it is no longer written; the §10.2 structure test asserts the probe records table has **no** `claim_relevance` column).
- **ADD the `location` value** to the probe `entity_type` CHECK.
- **ADD a GIN index on `entity_refs`** (for the discriminative-weight reads).
- **ADD a probe `enrichment_meaning` table** (it didn't exist before — `create_probe_schema` says "no meaning table"): `claim_meaning` text + provenance, **WITHOUT** the `vector` extension for structural runs (the `embedding` column omitted, or nullable-with-no-extension). Keep the probe role free of `CREATE EXTENSION`; the deferred needle step (which needs the extension) targets a meaning store pointed at a schema where the extension exists.

**Invariant test (§5.3):** assert no code path writes a vector/embedding to any table other than `enrichment_meaning.embedding`; assert `enrichment_records.claim_relevance` is NULL on every refactored-run row.

---

## 7. Pass sequence — the EXPLICIT `all_passes()` list literal

**The pass-list index IS the run order** (`pipeline.py` line 60). The numbers `1/2/3/2.9/...` are *slot names*, not run order. Replace `cli.py` `all_passes()` (lines 48-50) with this **literal, in true run order**:

```python
def all_passes() -> list:
    return [
        Pass1Prose(),               # 1  prose / non-prose (KEEP)
        Pass2ObjectTypes(),         # 2  typed entity types present (closed vocab)
        Pass3FillValues(),          # 3  MULTI-record grounded typed-entity instances
        EntityNormalizationPass(),  # 2.9 SLOT — runs AFTER Pass 3: canonicalize+resolve
        DiscriminativeWeightPass(), #     weight + theme-flag (code, no LLM)
        CrossChunkLinkPass(),       #     bounded candidate-gen -> LinkEvents grounds
        MeaningWriterPass(),        # 5  local-fact meaning (gated), embedded side
    ]
```

State plainly in the brief and in code comments: **normalization is physically positioned AFTER Pass 3 despite the "2.9" name** — Pass 3 grounds instances, normalization canonicalizes/resolves what 3 grounded. Pass 3 therefore sources its closed-vocab type list from `vocabulary.py` (+ optionally `prior["2_objecttypes"]`), **NOT** from `prior["2_9_consolidate"]` (which no longer runs before it — see §5.2 data-flow rewire).

Pipeline driver, glass-box persist, heartbeat, per-chunk error containment unchanged (`pipeline.py`). Whole-state passes use `process_all`; per-chunk passes use `process_chunk`.

**Buildability guard test:** assert that when `EntityNormalizationPass.process_all` runs, `prior` already contains `"3_fillvalues"` (codex-first sequencing is positionally enforced, not just named).

---

## 8. Linking design + guards

**Hybrid candidate generation (code bounds; model proposes; judge grounds):**

- **Code generates bounded candidate pairs ONLY** where two records share a **RESOLVED NON-hub canonical entity** (a non-theme entity from §9), **or** are **document-adjacent** (pending the §4 step-0 `segment_index` confirm). **Never all-pairs.**
- **Model proposes** relation + a span in EACH record.
- **`LinkEvents` grounds** it (the existing point→copy→check→attest, one link per call — `link_events.py` is already this, untouched).

**GUARDS:**

- **(a) Candidate-gen DRY RUN on the real 131-slice FIRST.** Before any model call: count each entity's chunk-degree (`chunks_by_entity`), set a concrete **per-entity fan-out cap F**, and **STOPLIST the hub entities** (= the high-weight themes from §9). Emit the candidate-pair count and per-entity fan-out as a glass-box artifact. This is the acceptance for "candidate explosion bounded" (§10).
- **(b) TWO grounding classes:**
  - **CODE-DERIVED temporal** (`precedes`/`follows` from two resolved dates): code cites each record's DATE-bearing span (which provably exists — the date entity was grounded from it), the judge verifies the **ordering** over the two date surfaces.
  - **MODEL-ASSERTED semantic** (`causes`/`corroborates`/`contradicts`/`elaborates`/`same_event`): verbatim span in each record + judge over the relation.
- **(c) `same_event` PRECISION guard:** require a **shared NON-hub entity** before `EventMaterializer` merges, **plus** a negative test: same actor, *different dates* → **NOT one event**. Over-merge is the **highest-severity** failure (it collapses distinct occurrences and destroys the timeline). The `EventMaterializer` union-find (`entities.py` lines 80-135) stays; the *candidate guard before calling it* is what's new.
- **(d) Name the gold-note REQUIRED EDGES** in the agentic-walk acceptance (§10 AGENTIC): the reversal record (`89503c71…`) must link to the decision records it undid, to the `B. Smith` actor node, and to the `2025-02-18` date node.

---

## 9. Signal/noise = discriminative weight (the CRQ-001 lever)

Deterministic, code, **no LLM**, post-normalization, per canonical entity:

```
weight(entity)   = | distinct chunks the entity appears in |   # record_store.chunks_by_entity()
is_theme(entity) = weight >= THEME_CUTOFF                       # tunable knob
persist:           entity_store.set_entity_flags(entity_id, weight=..., is_theme=...)
```

- **RARE** (low weight) → discriminator/locator/join-key → **high-recall, must-not-miss**, full weight as a discriminator, eligible as a link join-key.
- **UBIQUITOUS** (high weight) → **THEME** → one node, **flagged theme**, **kept never deleted**, **on the linking stoplist** (excluded as a *sole* join-key), **down-weighted** as a discriminator.

**No named buckets** — type + weight let the agent group on demand at query time. **THEME_CUTOFF is a knob**: calibrate on the 131-slice so the known themes (Long COVID, the claimant, "the claim") land above it and the known discriminators (`B. Smith`, the gold date, diagnosis codes) land below it. Weight + theme-flag persist in `codex_entities.metadata` via `set_entity_flags` (the only post-insert entity-metadata mutation besides event clustering — consistent with the write-once-RECORDS / mutable-ENTITY-metadata split already in the code). Rarity applies to **grounded typed entities only** — never to ungrounded surface strings.

---

## 10. Acceptance / test plan (TDD, bottom-up, model-agnostic via injected `Completer`/judge seams)

All unit tests use the existing fakes: `tests/fakes/fake_judge.py` (`ConstantJudge`/`ScriptedJudge`/`RuleJudge`), `tests/fakes/fake_stores.py` (`FakeRecordStore`/`FakeEntityStore`/`FakeLinkStore` — **extended with the §5.2 read APIs + `set_entity_flags`**), `tests/fakes/fake_fragment_reader.py`. **`FakeCompleter` already exists** at `tests/test_multipass.py:65` (drives all current passes) — **reuse it**; optionally promote to `tests/fakes/fake_completer.py` if it should be shared. **Only `FakeMeaningStore` is genuinely new** — add it.

**(0) PRE-FLIGHT** — §4: `segment_index` DB confirm; the 006 `+location` migration applies cleanly (up+down); 007 + 008 apply cleanly; repo pinned at `794d715`.

**(1) UNIT (fake judge/model):**
- closed-taxonomy validators: `validate_entity_proposal` rejects off-vocab types; `validate_link_proposal` **flags** an off-seed relation (sets `emergent`) and rejects **only** on structural shape failure (never on relation vocabulary — matches `link_events.py`);
- canonicalizers collapse known variants (`Feb 18 2025`/`02/18/2025`/`2025-02-18` → `2025-02-18`; `f06.4` → `F06.4`) AND **alias-not-merge** on ambiguity (`B. Smith` vs `Bruce Smith` → flagged, two nodes or curation, never silent collapse);
- candidate-gen emits **only** shared-NON-hub pairs (hub/theme entity present → no candidate);
- meaning writer **rejects ungrounded AND non-discriminative**; hook-resolution **flag** fires when the rendered meaning names a capitalized/date token absent from the chunk's resolved-entity surface set, and does **not** fire when it uses only resolved surfaces;
- store read-API units (against fakes): `chunks_by_entity`/`records_by_entity`/`cooccurrence`/`entities_of_type`/`get(entity_id)`/`set_entity_flags`/`links_for_record`/`neighbors_via_links` — **written BEFORE** the discriminative-weight (step 6) and walker (step 9) units;
- gate.py discriminative-substance: a `FakeEntityStore` pre-seeded with one theme entity + one rare entity → a chunk whose only grounded record carries the **theme** entity does **NOT** count as covered; a chunk carrying the **rare** entity does;
- **plus a REAL-judge integration run** for `render_meaning_claim` and relation grounding (marked `integration`, gated on the live judge alias).

**(2) CODEX STRUCTURE (probe schema, deterministic, agent-independent):**
- **GOLD-NOTE FLOOR FIRST** (hard regression gate, runs before anything else): chunk `89503c71-5ca2-424b-9386-6698a8337dc3` yields **≥1 grounded record naming `B. Smith` AND a `2025-02-18` date entity.** If this fails, **stop**.
- THEN the gold three entities — actor `B. Smith`, date `2025-02-18`, event "back-to-MH-limitation" — **EACH resolve to exactly ONE node.**
- grounded links connect the **reversal record to the decision records.**
- **sprawl-regression:** total distinct entity *types* ≤ `len(vocabulary.ENTITY_TYPES)` (7).
- surface variants collapse (the canonicalizer test, at corpus scale).
- candidate explosion bounded: distinct pairs ≤ K, no entity > F pairs (from the §8(a) dry-run).
- **probe shape:** the probe `enrichment_records` table has **no** `claim_relevance` column; a probe `enrichment_meaning` table exists.

**(3) NEEDLE (embedded half — deferred build, specced acceptance):**
- embed `claim_meaning` in Qwen3-4096 (**brute-force exact** search);
- re-run CRQ-001 with **baselines RE-MEASURED in Qwen3-4096** (BGE-1024 is being purged — decision);
- gold note ranks **materially better** than (i) the Qwen3-4096 cosine baseline AND (ii) the v0 meta-description meaning.

**(4) AGENTIC ASSEMBLY:**
- a query-time walk from **any chunk mentioning `B. Smith`** must **REACH the gold-note event via grounded links** — **even when its embedding does not rank top-k.** Name the required edges (§8d). Every hop cited.

**(5) SUBSTANCE:**
- a negative fixture grounds `"Cheers, Joe"` and it must score **0 substance / be REJECTED from `enrichment_meaning`** (the hard discriminativeness gate, calibrated before the first scored run).
- **invariant tests:** (a) nothing outside `enrichment_meaning.embedding` is ever embedded; (b) `enrichment_records.claim_relevance` is NULL on every refactored-run row.

**(6) ISOLATION every run** (the existing §5 harness — unchanged). First refactored run = **NEW baseline** (artifact shape changed); v0 archived; the **gold-note FLOOR is the continuity anchor** across baselines.

---

## 11. Bottom-up TDD build order

1. **`vocabulary.py`** (closed taxonomy + re-exported seed relations) — FIRST, single source of truth.
2. **Typed validators** (`Entity`/`Link`) in `parsing.py` — link validator advisory-on-relation (§5.2).
3. **`EntityResolver` canonicalizers** (`entities.py`) — date→ISO, code, location, document, actor.
4. **Multi-record EntityExtract** (Pass 2/3 + `fill_wiring.py`) — propose-list/ground-each, loop kept; **Pass 3 schema input rewired to `vocabulary.py` (+ `prior["2_objecttypes"]`)**, not `prior["2_9_consolidate"]`.
5. **`EntityNormalizationPass`** (2.9 slot, `pass2_9_normalize.py`).
   **5.5. Store READ-API layer** (`stores.py` protocols + Postgres impls + `fake_stores.py` parity, same commit) + migration `008_entity_refs_gin_index` + `set_entity_flags`. Fake-backed unit tests for every read API go green here, **before** anything depends on them.
6. **Discriminative-weight + theme-flag** (`discriminative.py`) — uses 5.5's `chunks_by_entity` + `set_entity_flags`.
   **6.5. `gate.py` coverage change** — discriminative-substance; depends on the theme-flag from step 6 + multi-record extraction from step 4; tested with a theme/rare-seeded `FakeEntityStore`.
7. **`CrossChunkLinkPass`** (`pass_link.py`) — wire `LinkEvents`; candidate-gen **dry-run + guards (§8) FIRST** (it needs the stoplist from step 6).
8. **Gated `MeaningWriter`** (`meaning_writer.py`) — local fact + meta-phrase pre-filter + hard discriminativeness gate + hook check; persist to `enrichment_meaning` via `postgres/meaning_store.py`.
9. **Codex READ API / agentic walker** (`codex_walk.py`) — before declaring linking done.
10. **Two-artifact persistence/export** (`persistence.py` + `postgres/meaning_store.py`; extend `probe/export.py` to dump entities/links/meaning alongside records, and drop its `claim_relevance` reads).
11. **(DEFERRED)** meaning-embed + needle (`needle.py`).

§5 isolation + the grounding spine stay untouched throughout. Wire `all_passes()` and `PassContext.extras` (`cli.py`, `pass_base.py`) only after the units pass — `extras` keys are **additive** (`proposer`+`grounder` stay; add `entity_store`/`entity_resolver`/`linker`/`meaning_writer`).

---

## 12. Standing constraints

- **TDD test-first, always.** Tests are the acceptance criteria; write them before the code.
- **§5 isolation every run** — throwaway `probe_<label>`, `claim_chunks` read-only, raw-export-before-drop, never-drop-unscored, prod-untouched proof.
- **The grounding law** — model POINTS / code COPIES / judge CHECKS / row ATTESTS; `HandleMap`; never free-type an id (the 89503 discipline, for record ids too — `link_events.py` step 1).
- **`link_events.py` stays untouched** — including its accept-unknown-relations contract; the link validator is strictly upstream advisory.
- **Doc header on every file** (what it is, why it exists — SCOPE §15).
- **Edit `/Users/yummyfudge/Projects/reliquary_enrichment` ONLY.** Never touch the sibling `context_reliquary` (its `CodexEntry` is unrelated).
- **Model choice is OUT OF SCOPE** — re-auditioned later via the injected `Completer`/judge seams. Build model-agnostic (no NER, no model-specific parsing).
- **Additive migrations only** (D3) — 006 (+location), 007 (meaning local-fact constraints), 008 (entity_refs GIN); never rewrite an applied migration in place. Joe/Architect apply migrations; never point the writer at prod.

---

**Key file map (verified @ `794d715`; bare names = `src/reliquary_enrichment/`):** rewrite `passes/pass5_meaning.py`, `passes/pass2_objecttypes.py`, `passes/pass3_fillvalues.py` (schema-source rewire, lines 35-38), `passes/pass2_9_consolidate.py`→`passes/pass2_9_normalize.py`, `multipass/fill_wiring.py`, `write_enrichment.py` (`_resolve_entities` 223-235; drop `claim_relevance` 42/90/104-105/130-131/200/224), `entities.py` (`_NORMALIZERS` 32 + canonicalizers), `multipass/gate.py` (29-50), `stores.py` (+read APIs, +`set_entity_flags`, +`get`/`entities_of_type`), `tests/fakes/fake_stores.py` (parity), `postgres/record_store.py` (`claim_relevance`→NULL, lines 24/26/29/41/64/66/84), `probe/export.py` (drop `claim_relevance` 26-27/59/98-99; +entities/links/meaning), `multipass/parsing.py` (+validators), `pass_base.py` (`PassContext.extras` typed slots, additive, line 101), `multipass/cli.py` (`all_passes` 48-50 literal; imports 31-32; extras 100-101), `multipass/review.py` (lines 34/38/56-58/72/75/86/88-90/99-100), `mcp.py` (drop `claim_relevance` 100/117), `models.py` (drop `claim_relevance` field 51 — LAST); delete `passes/pass4_keywords.py`, `passes/pass4_9_cleanup.py`; add `multipass/vocabulary.py`, `multipass/discriminative.py`, `passes/pass_link.py`, `meaning_writer.py`, `postgres/meaning_store.py`, `codex_walk.py`, `persistence.py`, `needle.py` (deferred), `schema/006_codex_entities_add_location.{up,down}.sql`, `schema/007_enrichment_meaning_local_fact.{up,down}.sql`, `schema/008_entity_refs_gin_index.{up,down}.sql`, `tests/fakes/fake_meaning_store.py`; extend `probe/schema.py` `_tables_ddl` (+location enum, +GIN on `entity_refs`, +meaning table, −`claim_relevance` column). Gold-note floor anchor: `89503c71-5ca2-424b-9386-6698a8337dc3` (slice line 71).

---

## 13. Addendum (2026-06-19) — no cross-context dependencies; the old probe goes in full

**Standing invariant (Joe).** **No cross-context dependencies.** Each context (the multipass harness, the codex, etc.) is **self-contained**: if it needs something from another context, that thing is **MOVED in**, never imported across the boundary. A deprecated context is removed **in full**; anything worth keeping **relocates to the context that uses it.** (This extends the §12 "edit `reliquary_enrichment` only / never touch `context_reliquary`" rule from the *external* boundary down to *internal* module boundaries.)

**FLAG-2 resolution — the old single-pass `probe/` harness is DEPRECATED IN FULL and DELETED.** It does not survive as a cross-context dependency of the multipass. Execute at **build step 5.5** with the coupling map:

1. **MOVE into the multipass's own namespace** the pieces the multipass currently imports from `probe/` — **plus any other `multipass → probe` import the coupling map surfaces** (Engineer finalizes the exact layout):
   - throwaway-schema create/drop (`probe/schema.py` → e.g. `multipass/isolation_schema.py`) — carrying the §6 DDL changes (+location, +GIN on `entity_refs`, +meaning table, **−`claim_relevance` column**) into the rehomed schema;
   - record export (`probe/export.py` → e.g. `multipass/export.py`) — with the `claim_relevance` drop + the entities/links/meaning additions;
   - isolation proof (`probe/cli.py` `_isolation_unchanged` / `prod_enrichment_counts` → e.g. `multipass/isolation.py`);
   - the frozen slice (`probe/slice/chunk_ids.txt` → `multipass/slice/chunk_ids.txt`; update `inputs.py`'s default `slice_path`).
2. **DELETE the rest of `probe/` entirely** — old scoring (`probe/scoring.py`), runner, extraction, the single-pass CLI (`probe/cli.py`'s `execute_probe`), `run.sh`, `RESULTS.md`.
3. Result: `probe/` is gone, the multipass is self-contained, **zero cross-context imports**, no orphaned namespace. The `claim_relevance` removal then has no superseded-probe coupling left to break.

**This SUPERSEDES the key-file-map block above:** the `probe/export.py` and `probe/schema.py` line-items become **moves into the multipass namespace** (carrying their listed changes), not in-place edits — and `probe/` is **deleted**, not retained.