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

## GOLD-DATE PIN (FLAG-7 owed deliverable) — RESOLVED

Mined the corpus for the B. Smith reversal date (gold note `89503c71`, doc
`...Aflac_claim_file_2025-03-30-final.txt`):
- The **reversal record itself is UNDATED in-text** (confirmed) — "Body Reviewed with manager B. Smith:
  Place claim back to a Mental Health limitation…" carries no date. So the date is soft/linked, never
  grounded-on-the-gold-chunk (matches the §8d corrected floor).
- "Feb 18" is **NOT a single value** in the corpus — it appears across **2023, 2024, AND 2025** as
  document timestamps (`2/18/2023`×8, `2-18-23`×4, `2/18/2024`+`2-18-2024`+`2-18-24` ≈5, `2/18/2025`+
  `2/18/25` ≈3). The one nearest the reversal context is `2/18/2024` (a C-AUTH doc "Last Modified
  2/18/2024, 3:06 PM").
- **PIN: the authoritative reversal date is `2024-02-18`** (soft/linked, captured AS-IS) — NOT the
  brief's original `2025-02-18` (that was unverified and is wrong). It is genuinely ambiguous in the
  corpus and is **NOT a hard-floor requirement**; the floor is entity-level on the gold chunk's OWN text
  (B. Smith actor + the reversal event/content). For the brief/notes correction: gold date → 2024-02-18.

## DEFERRED DECISION — theme-as-qualifier on links (Joe, step 7 addition)

CrossChunkLink anchors on its shared **non-hub/specific** entity (stoplist), and ALSO **records** the
shared **theme**-flagged entities as link metadata (`evidence.shared_themes`) — captured, **never acted
on** (no boost / no ranking / no effect on which links form, the floor, or the walk). A guardrail test
asserts `shared_themes` never influences link creation/ranking. WHY: makes the deferred theme-as-qualifier
feature **measurable without building it** — from the first real run we can estimate applicability
(how often a specific-anchored link also shares a theme) and measure value offline (re-rank links with vs
without theme-boost against the gold-note acceptance), then decide build-or-not from data. **Resolved
after the first real grounded run**, not a permanent defer. (Joins the deferred list: 0.4 theme-fraction
re-validation; this; the needle/CRQ-001.)

## Step 7 — CrossChunkLinkPass + gold FLOOR — DONE (full suite 166 green)

Wired the orphaned `LinkEvents` into the connective layer (link_events.py byte-unchanged):
- **`pass_link.py`** — bounded candidate-gen (cross-chunk pairs sharing a NON-THEME anchor; themes
  STOPLISTED; per-anchor fan-out F **and** a global K ceiling; dry-run glass-box before any model call),
  TWO grounding classes (code-derived temporal precedes/follows over two ISO dates citing each record's
  own grounded span; model-asserted semantic via the proposer), the `same_event` PRECISION guard
  (same-anchor / DIFFERENT-dates never merges), and **`shared_themes` captured PER-LINK** (keyed
  record_a/record_b/link_id) in the glass-box only — never on the Link row, never in any decision path
  (guardrail-tested), so #9 (theme-as-qualifier) is offline-measurable.
- **`floor.py`** — the entity-level gold FLOOR (B. Smith actor entity + reversal content on the chunk's
  OWN text; date NOT required; whitespace-tolerant).
- **`link_wiring.py`** — the real proposer; CODE injects the record ids (the model never supplies them).

### Adversarial verification (2 lenses, executed against the REAL LinkEvents+GroundingCore) — HOLDS
Invariant holds end-to-end: over-merge is airtight (a different-date same_event NEVER reaches
materialization), `shared_themes` is provably write-only (written once, passed through once, read in zero
decisions), the grounding spine is intact (code-injected ids; the judge proven a REAL gate — grounded a
valid temporal, rejected a mis-sliced one storing 0; locate-miss dropped), and link_events.py is
unmodified. **Fixed 3 LOW hardening items:** (1) global K ceiling on candidate count (§10 "pairs ≤ K",
reported not silent); (2) case-insensitive same_event guard (a `SAME_EVENT` variant can't slip the guard
yet write an inconsistent edge — defense-in-depth on the highest-severity over-merge); (3) the floor's
reversal-marker check is now whitespace-tolerant (survives OCR line-wrap; the continuity anchor must).

## Step-7 note (gold-floor is ENTITY-LEVEL under record_type=entity_type)

Joe confirmed: because each typed entity is its OWN record (record_type=entity_type), the gold-note
floor is entity-level — chunk `89503c71` grounds a **`B. Smith` actor entity AND the reversal event
entity as SEPARATE records** (not one record carrying both). Build the floor gate (step 7/12) to
assert the actor entity + the reversal event/content, each on its own grounded record.

## Step 8 — gated MeaningWriter + meaning_store (the embedded side of the bright line) — DONE

The meaning side, SEPARATE from `write_enrichment` (meaning NEVER routes through enrichment_records):
- **`meaning_writer.py`** — pipeline, cheap checks first: (1) META-PHRASE pre-filter (kill the
  "this chunk indicates / the significance to the claim is / what this means for the denial is" family);
  (2) HARD DISCRIMINATIVENESS gate (REJECT, not flag) — the ONLY trivia defense, since the judge only
  checks non-contradiction; (3) GROUNDING at `Tier.INTERPRETATION` via the shared GroundingCore
  (point→copy→judge→attest); (4) HOOK-resolution check (FLAG, not reject) for a capitalized/date span
  the codex doesn't carry. Stores ONLY `(source_chunk_id, claim_meaning)`; the attestation + flag ride
  in the write RESULT, not the row (the 004 schema has no provenance column — meaning-provenance-on-row
  is the logged open question).
- **`postgres/meaning_store.py`** — the ONLY writer of `enrichment_meaning`; `set_embedding` is the
  EXCLUSIVE embedding-write path (deferred needle §5.4 #11 — nothing embeds today).
- **Bright-line guardrail** (`test_no_cross_context.py`): a regex sweep proves `meaning_store.py` is the
  sole file that ever writes an embedding — fails the suite if anything else embeds.

### Two-pole calibration (Joe's acceptance) + adversarial verification (2 lenses) — HOLDS
Both poles asserted BEFORE the first scored run: "Cheers, Joe" / theme-only OUT (`non_discriminative`),
the gold local fact ("Manager B. Smith placed the claim back under the Mental Health limitation") IN
(discriminative + grounded + hooks resolve). The review confirmed the bright line and grounding are
SOLID (no enrichment_records / write_enrichment / set_embedding from the writer; grounds at INTERPRETATION;
ungrounded→reject, partial→accept+flag). It found the predicted brittleness in the two regex gates —
**4 real findings, all fixed (red→green):**
- **HIGH false-reject** (the exact risk Joe named): the discriminativeness gate did a LITERAL substring
  match of the EXACT entity surface, so a discriminative gold paraphrase naming the SAME B. Smith entity
  via surname-only ("Smith…"), no-space ("B.Smith"), or title ("Dr. Smith") — without ALSO quoting the
  provision verbatim — was wrongly rejected (the provision phrase was masking it in the happy path).
  **Fix:** word-level distinctive-token overlap (`_name_tokens`, ≥3-char non-common tokens), so any
  natural actor-surface paraphrase resolves the entity.
- **MED false-accept:** the same substring test matched 'Smith' inside 'Blacksmith' (not word-boundary
  aware). **Fix:** the token approach is word-level, not infix — 'Blacksmith' no longer matches 'Smith'.
- **HIGH meta under-reject:** "What this means for the denial is…" evaded the regex and (if it carried a
  non-theme entity) would be STORED. **Fix:** the meta regex now anchors on the meta SUBJECT (this
  chunk/record, the significance, what this means), catching the evader.
- **MED meta over-reject:** the old 4th alternative killed ANY "shows/reflects/documents that" regardless
  of subject — over-rejecting legit facts like "Dr. Smith shows that the MRI is normal". **Fix:** the
  meta-subject anchor means a verb with a REAL subject is a fact, not meta.
- Hook precision improved alongside (token-based resolution, name-token filter so Title-Case of common
  words like "The Claim" no longer false-flags); residual: genuinely novel Title-Case nouns still flag by
  design (the brief's intent — surface a codex gap). Every review reproduction re-run green.

## Step 9 — codex_walk: the query-time AGENTIC-ASSEMBLY walker — DONE

The bright line's other half: the larger answer is **assembled at query time by WALKING the codex**, not
embedded (§3.1). `codex_walk.py` is that walk — pure structure, **no embeddings**:
- **`CodexWalk`** over the three read-API stores. Primitive cited hops: `entities_of_chunk(chunk)` →
  `records_for_entity(entity)` → `neighbors(record)`. `assemble(target_record, seed_chunk|seed_entity,
  max_hops)` BFS-walks seed→target and returns the cited path + glass-box `examined` count.
- **GROUNDING LAW as a structural read-time invariant:** only **cited** edges are walkable. A record with
  a blank `evidence_span` and a link without the code-sliced `a_span`/`b_span` pair are **invisible to
  assembly** — an ungrounded edge can never smuggle a path. `Hop.cited` is kind-specific.
- **Added read API `records_by_chunk`** (protocol + Postgres + fake parity, same commit) — the chunk-seed
  `entities_of(chunk)` needs it; served by `idx_enrichment_records_source_chunk` (migration 001).
- **§10 acceptance (fixture-level):** from a B. Smith-mentioning chunk the walk reaches the gold reversal
  record, and the decision-it-undid + date node (which share **no** entity with the seed) **only via
  grounded links** — link-based assembly, not shared-entity coincidence; every hop cited.

### Adversarial verification (3 lenses, executed against the REAL walker) — found + fixed 6
Lens 2 cleared the BFS outright (no correctness bug: no dedup hazard, cycles/self-links terminate,
`max_hops` exact, reach-via-links genuine — remove the link and the target goes unreachable). Lens 1 + 3
found real gate/parity defects, **all fixed red→green:**
- **HIGH** — "only cited edges walkable" tested dict **truthiness**, not a real span: a non-empty but
  span-less link `evidence={"note":"x"}` was walkable and could smuggle a path. **Fix:** `_link_grounded`
  requires the code-sliced `a_span`/`b_span` int-pair the linker actually writes (link_events.py:175);
  `_span_grounded` requires a non-blank record span. The invariant is now structural at read time, not a
  lean on writer discipline. **Plus migration 009** (authored; Architect applies) adds the matching
  DB-side `CHECK (evidence ? 'a_span' AND evidence ? 'b_span')` on `enrichment_links` — mirroring the
  records' nonblank check (003 had only `NOT NULL`); rejects no legitimate link.
- **MED** — whitespace-only `evidence_span` read as a citation → `_span_grounded` strips (mirrors the DB
  `enrichment_records_span_nonblank_chk`).
- **MED** — `records_by_chunk` raised on a non-UUID chunk_id in Postgres but returned `[]` in the fake →
  guard with `UUID(str(...))` like `get()`, returns `[]` (parity).
- **MED** — walk path depended on arbitrary Postgres scan order → `ORDER BY record_id` on
  `records_by_chunk`/`records_by_entity` + fake sorts to match → deterministic, fake==prod cited paths.
- **LOW** — `cited` cross-key OR could smuggle citedness → kind-specific check closes it.
- **LOW** — comment wrongly implied no `source_chunk_id` index → corrected (001 creates it).
Positive confirmations re-run green: span-less/empty/None link evidence and blank spans all unwalkable;
200 randomized adversarial trials (Lens 1) found 0 emitted-uncited-hop; the gold edge still assembles.

## Step 10a — integration: §7 wiring + two-artifact persistence + MeaningWriterPass — DONE (build)

The codex-refactor pass chain, wired end to end (the real-corpus RUN is 10b, needs the lane):
- **`all_passes()` rewired to the §7 LITERAL order** (`cli.py`): Pass1 → Pass2 → Pass3 → EntityNormalization
  (the "2.9" SLOT, positioned AFTER 3) → DiscriminativeWeight → CrossChunkLink → MeaningWriter. The list
  index IS the run order; codex-first sequencing is positionally enforced (test: normalize after 3, link
  after discriminative, meaning last).
- **`MeaningWriterPass`** (rewrote `pass5_meaning.py`) + **`meaning_wiring.make_meaning_proposer`** — the
  gated, embedded side wired as a Pass: assemble the chunk's resolved codex entities (theme-flag from §9),
  model POINTS a local fact + verbatim span, CODE locates it, the gated MeaningWriter grounds/judges/stores.
- **Deleted** `pass4_keywords`, `pass4_9_cleanup`, `pass2_9_consolidate` (untyped lexical bags → typed
  entities + the theme-flag). Their tests removed; §7-order + buildability guards added.
- **`_build_services`** — ONE shared GroundingCore + all four stores + every per-pass service as one extras
  dict (records, links, meaning all judge against the SAME probe schema). **FLOOR-FIRST** (gold floor is
  the first acceptance, exit 2 on fail) + **two-artifact export** (`export_records` + new `export_codex`:
  entities/links/meaning jsonl, BEFORE drop) + isolation/drop unchanged. `review.py` rewired to the new
  pass outputs.
- **`test_multipass_pipeline_integration.py`** — the centerpiece: the FULL §7 chain over fakes (no lane/DB)
  produces a codex where B. Smith stays a DISCRIMINATOR (12 fillers → cutoff 5, margin 3), the date is a
  THEME, the gold EDGE forms (theme stoplisted), the FLOOR passes, the gated meaning stores, and the codex
  is WALKABLE. 201 green / 13 deselected.

### Adversarial verification (3 lenses, executed against the real pipeline) — found + fixed 4
Lens 1 (wiring) CLEAN: every pass gets its extras (no KeyError), the core is genuinely shared, floor-first
+ export-before-drop + never-drop-unscored + breach-raise all hold across failure paths, theme-flags
round-trip in-run. Lens 3 essentially clean (only unreachable defensive gaps; the one integration-marked
failure is an env DB-privilege issue, not a regression). Fixed:
- **(LOW, real source bug) meaning gate date hole** (`meaning_writer.py`): `has_discriminative_substance`
  short-circuited on ANY date token BEFORE the theme check, so a THEME-date-only (or codex-absent-date)
  meaning passed the hard gate and was stored. **Fix:** a date counts as substance ONLY when tied to a
  NON-THEME date entity on the chunk (added `entity_type` to `resolved_entities_for_chunk`); regression
  tests added.
- **(MED, test fragility) cutoff knife-edge**: the fixture had B. Smith at degree 2 vs cutoff 3 (margin 1)
  — ±1 filler flipped the whole §10 acceptance. **Fix:** 12 fillers → cutoff 5, margin 3 (robust to ±1);
  real-corpus robustness already lives in `test_discriminative.py`.
- **(MED, test over-claim) walk "via links"**: `assemble()` reached the gold record via the shared B. Smith
  entity (mentions→cites), NOT over the link. **Fix:** the assertion is now honest — the gold record is
  reachable via the codex AND the formed link is independently a walkable cited edge (`neighbors` →
  relation `corroborates`); genuine link-ONLY reach stays proven in `test_codex_walk.py`, real-corpus in
  10b.
- **(LOW, observability) silent degradation**: a contained whole-state pass crash (e.g. discriminative)
  emptied the theme stoplist yet the run still reported PASS. **Fix:** `execute_multipass` now collects
  `pass_errors` from `{"error":...}` outputs, emits a DEGRADED warning, and returns them. (+ `review.py`
  `_by_chunk` guards malformed jsonl.)

## Build order (§11) — in progress
1–3 vocabulary → validators → canonicalizers · 4–5 multi-record extract → normalize ·
5.5–6.5 read-APIs → discriminative-weight → gate · 7–8 linker → MeaningWriter ·
9–10 walker → persistence/throws/wiring · 11 needle (DEFERRED). §5 isolation + grounding spine
untouched throughout; gold-note FLOOR runs first.
