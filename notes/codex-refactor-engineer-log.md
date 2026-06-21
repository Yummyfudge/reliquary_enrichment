# Codex Refactor — Engineer Log

Running log for the codex/meaning refactor (brief: `notes/engineer-brief-codex-refactor.md`).
Engineer → Architect. Records PRE-FLIGHT results, brief↔code discrepancies the mapping pass
surfaced, and decisions taken. Source verified unchanged since `794d715` (HEAD `25f1cc5` only
adds the briefs); all brief line-refs valid.

## PRE-FLIGHT (§4) — COMPLETE

- **v0 baseline tagged:** `v0-baseline` → `794d715` (annotated). Gold-note floor is the
  cross-baseline continuity anchor.
- **segment_index DB check (§4.2) — RESOLVED:** read-only query on `context_reliquary.claim_chunks`
  (5119 rows, 2 docs). `char_start_offset` is **degenerate** — constant `0` for every row
  (5117/5117 adjacent pairs tie; gold note `89503c71` char_start=0), so it carries **no ordering
  signal**. `segment_index` IS the intra-document ordering key; `_NEIGHBORS` needs **no logic fix**.
  Caveat for §8 adjacency: `segment_index` has 77 `(document, segment_index)` tie-groups + 75 NULL
  rows corpus-wide — adjacency candidate-gen must dedupe/bound accordingly. Resolution written into
  the flagged NOTE in `postgres/fragment_reader.py`.
- **Migrations authored + verified clean (up+down) on a throwaway schema replica (zero prod
  contact), 8/8 checks pass:**
  - `006_codex_entities_add_location` — drops/re-adds `codex_entities_type_chk` with `location`.
  - `007_enrichment_meaning_local_fact` — ADD UNIQUE(source_chunk_id) + FK→claim_chunks (mirrors
    005) + DROP COLUMN questions_answered.
  - `008_entity_refs_gin_index` — see FLAG-1 (idempotent backstop; down is a no-op).
  - Probe DDL: `location` mirrored into `probe/schema.py` `_tables_ddl` codex_entities CHECK
    (additive; the claim_relevance drop + meaning table + GIN are coupled to build step 5.5).

## FLAGS for the Architect (brief↔code discrepancies found while mapping)

- **FLAG-1 — migration 008 is a prod NO-OP.** Prod already creates the entity_refs GIN index in
  `schema/001_enrichment_records.up.sql:63-64` (`idx_enrichment_records_entity_refs`). 008 was
  authored as an **idempotent backstop** (`CREATE INDEX IF NOT EXISTS`, down = no-op). The real gap
  is the **probe** schema, which lacks it — that GIN goes into `probe/schema.py` at step 5.5. Brief
  §5.2/§6 premise that prod lacks the index is incorrect.

- **FLAG-2 — claim_relevance touch-point list (§5.3) is INCOMPLETE; the probe extraction-probe stack
  couples to the §6 probe-DDL drop.** Beyond the §5.3 sites, `claim_relevance` also lives at:
  `probe/scoring.py:74` (`_haystack` reads `rec.get('claim_relevance')`), `probe/scoring.py:153`
  (`load_probe_records` SELECT), `probe/runner.py:193`, `probe/extraction.py:60/76/117`
  (`ExtractionProposal` — a **separate** dataclass from `EnrichmentRecord`; dropping the models.py
  field does NOT break these). **Coupling:** §6 drops `claim_relevance` from the probe records DDL →
  `probe/scoring.py:153` SELECT becomes a runtime breaker **for the retired single-pass extraction
  probe CLI** (not exercised by multipass). **Proposed resolution (at build step 5.5):** drop the
  probe-DDL column AND strip `claim_relevance` from `probe/scoring.py:74,153` (minimal coupled fix);
  leave `probe/extraction.py`/`runner.py` (own dataclass, write through write_enrichment binds NULL).
  Confirm before executing.

- **FLAG-3 — existing TESTS that break are not enumerated by the brief (they are TDD acceptance
  rewrites).** Collection/run breakers once passes are renamed/deleted + claim_relevance/
  questions_answered removed: `tests/test_multipass.py` (imports L12/15/16; tests L40,124-155,
  215-234,243-253), `tests/test_multipass_e2e_integration.py` (L51,54,86,87,91),
  `tests/test_multipass_review.py` (L20-25,36), `tests/test_write_enrichment.py` (L137,149),
  `tests/test_probe_scoring.py` (L22). Each gets rewritten red→green in its build step.

- **FLAG-4 — 004 header reword ambiguity.** Brief §5.2 says reword 004's "interpreted significance"
  comment, but 004 is an applied migration (D3 = don't rewrite in place). Resolution: left 004
  byte-unchanged; the local-fact framing lives in the **007 header** instead. Confirm acceptable.

- **Line drifts (edit by content, not line number):** write_enrichment build-site is **202** (not
  200; "224" is a stray inside `_resolve_entities`, which has no claim_relevance); mcp.py payload is
  **118** (not 117); record_store `26/66` are SQL continuation lines (no token — `sed` on
  `claim_relevance` is safe, hits only 24/29/41/64/84).
- **Path convention:** passes live under `src/reliquary_enrichment/multipass/passes/` (brief writes
  `passes/...`). New `pass2_9_normalize.py` / `pass_link.py` go there; cli imports use
  `reliquary_enrichment.multipass.passes.<module>`.

## Build steps 1–3 — DONE (TDD red→green; full default suite 146 green)

- **vocabulary.py** — `ENTITY_TYPES` (7) + `SEED_RELATIONS` as a literal re-export of
  `link_events.SEED_RELATIONS` (asserted by identity). 6 tests.
- **parsing.py validators** — `validate_entity_proposal` (closed-vocab/quote/surface),
  `validate_link_proposal` (ADVISORY-on-relation: accepts any non-empty relation, flags off-seed
  via `emergent`, rejects only on structural shape). Both reject-to-None, never raise. 12 tests.
- **entities.py canonicalizers** — date→ISO (strict month tokens + `-`/`/`/`.` separators,
  no guess on ambiguity), code (upper/whitespace), location/document/provision, stronger actor;
  `resolve_or_create` alias-not-merge body untouched. 13 tests.

### Adversarial verification (3-lens workflow, executed break-attempts) — 1 real bug fixed

- **FIXED (correctness):** `normalize_date` over-collapsed a NON-month word whose first 3 letters
  matched a month (`"Marbles 5 2025"` → `2025-03-05`, silently merging onto the real `March 5 2025`
  node). Now requires the WHOLE token be a real month (`_month_num`). Regression-tested.
- **FIXED (recall):** widened date separators — year-first `2025/02/18` / `2025.02.18` and
  M/D/Y `.` separators now reach ISO. Zero new over-collapse.
- **FLAG-5 (deferred, documented):** `safe_json_array`/`safe_json_object` RAISE `TypeError` on
  truthy non-str input (`7`, `nan`) despite their "never-raise floor" docstring — the `raw or ""`
  guard only rescues falsy inputs. UNREACHABLE today (all callers pass the model's str reply) and
  the functions are §5.1-KEEP / "byte-equivalent", so **left untouched**; raise with Architect if
  the floor should be hardened (`raw if isinstance(raw,str) else ""`).
- **FLAG-6 (deferred):** `normalize_code` strips all whitespace + uppercases (matches the brief's
  `f06.4`→`F06.4`) but does not normalize punctuation (`F-06.4`/`F06,4` stay distinct) — conservative
  (avoids merging `F06.4`/`F064`); 2-digit-year dates (`2/18/25`) are not century-expanded (a guess).
  Both are dedup-recall gaps, not correctness bugs; deferred to curation.

### FLAG-7 (gold-floor date vs corpus) — RESOLVED by Architect (brief @ 46d1733)

I verified against the DB that the **gold note's own text (segment 15) contains NO date** — only
`10/2023`; "Feb 18" / "2/18/2024" live in NEIGHBOR chunks; literal `2025-02-18` is not in the corpus
near it. Architect confirmed this was an over-spec and corrected the brief:
- **Hard FLOOR drops the date.** Gate = chunk `89503c71` grounds ≥1 record ON ITS OWN TEXT naming
  `B. Smith` + the reversal content (Mental Health limitation / "place claim back"). `date=None` is
  fine (matches what both audition candidates already grounded).
- **The reversal date is a SOFT, linked/metadata entity (§8d)** — captured from the note's source
  record, value **AS-IS** (do NOT assume `2025-02-18`; corpus suggests `2024-02-18` / bare `Feb 18`).
  **TODO (at date-capture build):** pin the authoritative value and report back so the brief/notes
  are corrected.
- §8d required-edges + the §5.2 Pass-5 example were corrected to match (dated only when the chunk's
  own text carries a date). Cleared to build the floor at step 7/12 on the corrected spec.

## Step 4 — multi-record typed-entity extraction — DONE (full suite 149 green)

- **pass2** now names the **closed-vocab** types present (filtered to `ENTITY_TYPES`).
- **fill_wiring** proposer returns a **list** of `EntityProposal`s (validated, bad items dropped);
  grounder grounds **each** via one `write_enrichment.write` (actor→actor, date→event_date,
  code/location/document/provision/event→`fields[type]`, record_type=entity_type).
- **pass3** data-flow **rewired** (schema = `vocabulary.ENTITY_TYPES` narrowed by `prior["2_objecttypes"]`,
  **not** `prior["2_9_consolidate"]`); propose→ground→plateau loop kept, now wrapping the per-chunk
  batch with the plateau on **grounded-fraction** (Joe-confirmed). Output adds record_ids/n_grounded;
  keeps grounded/reason_code/attempts for the gate.
- **`write_enrichment._resolve_entities`** widened to resolve every `fields`-carried typed entity
  (code/location/document/provision) + EntityRefs; grounding LAW (resolve/slice/judge/attest) untouched.

### Adversarial verification (3 lenses, executed repros) — CLEAN on the core invariant

Nothing reaches storage ungrounded (every record still flows through `write_enrichment.write`); the
degenerate render branch is unreachable from Pass 3 (validate requires non-empty surface); record_type
=entity_type does NOT resurrect the "judge demands the type word" bug (record_type excluded from the
claim; the type appears only as a JSON field KEY, and the judge checks values); loop terminates within
`max_attempts` in every case; best-attempt record selection is correct. **Fixed:** dead `_FIELD_TYPES`
constant in fill_wiring.py removed. **Observations (no change):** (a) stray candidate `fields` can spawn
extra entities, but only judge-gated ones (value must be in the span) — acceptable; (b) `ConfidencePlateau`
stops one attempt early on an exactly-epsilon gain (float rounding) — in §5.1-KEEP `confidence.py`,
bounded/conservative, left untouched; (c) the `len(ok)==n_proposed` all-grounded short-circuit can stop
before a retry that might propose MORE entities — matches the brief's design (the model proposes the full
batch; the loop retries bounces), a model-recall/cost tradeoff, not a loop bug.

## Step 5 — EntityNormalizationPass + canonicalizer refinements — DONE (full suite 159 green)

Driven by REAL slice surfaces (Joe's steer — invented strings hide over/under-merge):
- **Canonicalizer refinements** (`entities.py`): `normalize_date` assumes the corpus's **US M/D/Y**,
  expands 2-digit years (00-68→2000s), NFKC-folds, and rejects 3-digit OCR years; `normalize_code`
  NFKC-folds full-width OCR digits (`F0６.４`→`F06.4`). Distinct dates/codes still map to distinct
  canonicals (no over-merge); only same-entity format/OCR variants collapse.
- **`pass2_9_normalize.py`** (`EntityNormalizationPass`, per_chunk=False): deterministic
  resolve_or_create over what Pass 3 grounded → surface→entity_id glass box (raw/mapping/final);
  residual LLM proposes same-type merges → **FLAGGED for curation, NEVER merged**.

### Adversarial OVER-MERGE hunt (3 lenses, mined the WHOLE slice, executed repros)

**No over-merge anywhere.** 278 real date surfaces → 132 ISO buckets, every multi-surface bucket =
variants of ONE real date (the canonicalizer even *healed* a scout model-error date split). All
distinct ICD codes stay distinct; full-width OCR folds correctly; distinct "Smith" people + the JoAnn
family stay distinct. The residual path never merged under aggressive fakes (5000-element arrays,
malformed/self/out-of-set pairs, non-JSON); crash-resistant (None records, empty fields, event skip).

**Fixed (TDD):** (1) 3-digit OCR year (`12/05/022`) no longer coerces to a confident wrong ISO —
`_NUM_RE` now requires exactly 2-or-4-digit years; (2) `flagged_merges` deduped (a spammy model reply
can't bloat the glass box). **Documented, not changed:** mapping is `surface→entity_id` per spec
(last-wins on the unreproducible same-string-two-types collision; `final` stays lossless); NFKC
roman-numeral fold + `F06 4` internal-space collapse (neither in the slice); `Dr Smith`/`Dr. Smith`
title-period **under**-merge (the safe direction — and the residual LLM flags it for curation).

## Step 5.5a — store READ-API layer — DONE (full suite 164 green)

Additive read APIs on the three stores (protocols in `stores.py`, Postgres impls, `fake_stores.py`
parity in the same change):
- `EntityStore`: `get`, `entities_of_type`, `set_entity_flags` (weight+is_theme via jsonb_set, PATCH
  not clobber — the §9 discriminative-weight write path).
- `EnrichmentRecordStore`: `records_by_entity`, `chunks_by_entity` (DISTINCT chunks), `cooccurrence` —
  the entity→record reverse lookup via **jsonb-containment** (`entity_refs @> '[{"entity_id":...}]'`),
  since entity_refs is denormalized jsonb (no join table).
- `LinkStore`: `links_for_record`, `neighbors_via_links` (the walker's hop).
Fake-backed unit tests (5) green; **8/8 Postgres checks pass against a real throwaway schema**
(records_by_entity / chunks_by_entity / cooccurrence / get / entities_of_type / set_entity_flags /
links_for_record / neighbors_via_links) — parity confirmed. The probe GIN on entity_refs + the §13
rehome land in 5.5b.

## Step 5.5b — §13 self-containment + claim_relevance throw — DONE (full suite 144 green)

- **Rehomed 4+1 pieces into `multipass/`** (probe/ deleted in full): `isolation_schema.py` (throwaway
  schema, carrying §6 deltas — −claim_relevance column, +GIN on entity_refs, +enrichment_meaning table
  with NO vector/embedding), `export.py` (−claim_relevance), `isolation.py` (prod-untouched proof),
  `locate.py` (locate_quote), and the frozen **slice** (now `multipass/slice/chunk_ids.txt`, package-
  relative default). Rewired the 4 prod imports + slice defaults.
- **claim_relevance THROWN** readers-first / models-field-last: record_store (INSERT/SELECT/recon),
  write_enrichment (_Payload/_validate/render/build), mcp (param+payload), models (field LAST), and the
  probe DDL. Choice (vs brief): record_store **omits** claim_relevance from the INSERT entirely (rather
  than binding literal None) — this resolves the §6 probe-DDL-drop conflict (the probe table has no such
  column) and still satisfies the NULL invariant on prod (nullable column, unwritten → NULL).
- **Add #1 (Joe):** e2e §5 isolation proof run end-to-end through the rehomed harness — create-schema →
  write → export → drop → prod-untouched, asserting the §6 structure + claim_relevance-clean artifact.
  Codified as `tests/test_isolation_e2e_integration.py` (integration); passes. Isolation here is the
  **stronger structural** form: the probe role is read-DENIED on prod enrichment, so before==after by
  permission-denial — the harness can't even read prod, let alone write it.
- **Add #2 (Joe):** no-cross-context invariant codified as `tests/test_no_cross_context.py` (zero
  `from/import …probe`, zero `from/import context_reliquary`, probe/ gone). It immediately CAUGHT a real
  pre-existing violation — `postgres/connection.py` imported `config` from `context_reliquary` — now
  fixed (connection owns its defaults; real runs are env-driven; DB connectivity confirmed).
- **Re-homed the probe's ISOLATION-BREACH hard-fail** into `execute_multipass` (the deleted probe raised
  on prod-touched; the multipass only logged it — pre-existing gap, but §13 "move in what's worth
  keeping" + Joe's "the one property we cannot regress"): now raises RuntimeError after recording
  isolation.json. Never fires on the clean (read-denied) path.

### Adversarial verification (2 lenses, executed greps + isolation-flow trace) — CLEAN
Both required properties hold: isolation byte-identical to HEAD (never-drop-unscored + export-before-drop
verified; prod-untouched proof fully wired), and zero stragglers (probe/ gone, 0 import failures, no live
claim_relevance read/write, no-embed invariant holds, guardrail airtight against import-evasions). Fixed
a stale `probe/schema.py` reference in the schema/008 comment.

## Step 6 + 6.5 — discriminative-weight + theme-flag + gate-substance — DONE (full suite 151 green)

- **`discriminative.py`** (DiscriminativeWeightPass, per_chunk=False, NO LLM): weight = distinct grounded
  chunk-degree (`chunks_by_entity`); is_theme = weight >= cutoff; persists via `set_entity_flags`; emits
  the theme **stoplist** for the linker (§8). Themes are kept-never-deleted, stoplisted, down-weighted.
- **Gate (6.5)**: coverage = a grounded record carrying a **NON-THEME typed entity** (a trivial grounded
  sign-off or a theme-only chunk does NOT count). Optional stores → back-compat (grounded-anything) until
  step-9 wiring; never rejects (measures only); never crashes on bad input.

### LOAD-BEARING calibration (Joe) + adversarial robustness fix
The known entities classify correctly against their REAL slice degrees: discriminators B. Smith(2)/gold
date(3)/F06.4(28) BELOW the cutoff, themes "the claim"(76)/claimant(82)/Long COVID(90) ABOVE.
- **B. Smith property HOLDS unconditionally** — grounded ≤ text < cutoff, so a discriminator can NEVER
  invert to a theme (the CRQ-001 lever can't flip via B. Smith). Verified.
- **Adversarial fix (MED):** the cutoff was `0.4 × total_chunks` (=52) but weight is the *grounded*
  degree (≤ text degree), and audition grounding was ~34-54% — at which rates all three THEMES would fall
  below 52 and mis-flag as discriminators (the lever inverting the wrong way). Changed to
  **`0.4 × max-grounded-degree`** (relative to the run's actual distribution) — robust at any grounding
  rate, with a regression test (`test_calibration_robust_to_low_grounding_rate`) that fails under the old
  formula. Gate also hardened against a None output value.
- **TODO (first real grounded run / re-audition):** re-validate the 0.4 fraction on ACTUAL grounded
  degrees — the calibration is currently on the text-occurrence proxy. The 28-vs-76 anchor separation is
  clean for codes/dates; some real clinical/role surfaces (RTW, fatigue, brain fog) crowd the cutoff —
  inherently borderline, tunable via the knob; the named anchors are safe.

## Step-7 note (gold-floor is ENTITY-LEVEL under record_type=entity_type)

Joe confirmed: because each typed entity is its OWN record (record_type=entity_type), the gold-note
floor is entity-level — chunk `89503c71` grounds a **`B. Smith` actor entity AND the reversal event
entity as SEPARATE records** (not one record carrying both). Build the floor gate (step 7/12) to
assert the actor entity + the reversal event/content, each on its own grounded record.

## Build order (§11) — in progress
1–3 vocabulary → validators → canonicalizers · 4–5 multi-record extract → normalize ·
5.5–6.5 read-APIs → discriminative-weight → gate · 7–8 linker → MeaningWriter ·
9–10 walker → persistence/throws/wiring · 11 needle (DEFERRED). §5 isolation + grounding spine
untouched throughout; gold-note FLOOR runs first.
