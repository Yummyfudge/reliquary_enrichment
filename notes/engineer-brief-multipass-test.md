# Engineer Brief — Multi-Pass Extraction Test (replaces the single-pass probe)

_From: Architect (Opus). To: Sr. Engineer. PO: Joe — requirements aligned 2026-06-17._
_**This is a starting point, not a finished spec.** Build it, run it, and let feedback fill the
gaps — do not wait on perfect documentation. The pass boundaries are the TDD boundaries._

## Why
The current probe (`probe/`) does the whole job in **one extraction call per chunk** — the
"elephant." It timed models out and never validated the multi-pass direction. This replaces it
with a **multi-pass** harness, one focused job per pass, so a model isn't asked to eat the whole
chunk at once.

## The pipeline — one job per pass; each pass runs the WHOLE FILE start→finish before the next
1. **Prose vs. non-prose** — the split, nothing else. (A unit that's both — identifier header +
   prose body — splits here, re-links later via the context layer, many-to-many.)
2. **Object types (non-prose)** — identify *types*, not values. Seed the starter set below; the
   **LLM** places signal onto types and the set may grow (emergent). **Identifiers via the LLM,
   NOT regex** — OCR'd scans, real variety; code is for the deterministic (pull chunk, slice
   offsets), the LLM for messy reality.
   - **2.9 Consolidate** — collapse the type sprawl. **Persist raw set + final set + the mapping**
     (each raw point → where it got slotted).
3. **Fill the values** — model fills; judge gives feedback; model retries.
   **Retry bound = confidence-plateau** (stop when the model's own confidence stops climbing —
   emergent count, no magic number). **Flag this as a tunable knob** (PO will turn it later;
   document what/why/how-to-turn). The judge owns *correctness*, not the loop.
4. **Prose signal keywords** — keep signal, drop noise. **Boilerplate is just a *type* of noise,
   dropped here** — noise-heavy content (plan language) never reaches Pass 5.
   - **4.9 Cleanup** — signal/noise scrub before persistence.
5. **Meaning** — the needle-mover: full semantic meaning, built on the codex + actors/places from
   the prior passes.

## The judge
- *Out* of the early passes (the chunk is **code-served** — nothing to ground). *In* at Pass 3
  (feedback) and at scoring.
- **Strict-core / soft-rest:** strict only on "grounded in source, not hallucinated"; **lenient
  on type-getting** (narrow perfection starves coverage; 2.9 cleans the slop later).

## Scoring — two SEPARATE readings, never combined into one number
- **Gate (faithfulness)** — judge-side. Per chunk, on the final-pass output **before persist**:
  *is this derived from, and pointing back to, the original source?* Anti-hallucination, not
  perfection. The judge re-reads the full chunk.
- **Needle** — big_thinker-side. **Ask the question of the full reassembled dataset and read
  where the gold note lands in the result set.** That placement *is* the answer (this is the
  existing `verify_rank` idea). Everything before is setup.
- Final score is on the **final pass** — passes *multiply* into the final shape.

## Capture (glass box)
- **Snapshot state at the END of every pass** — the inspectable trail (so "multiply" failures are
  diagnosable and the tunable has evidence). 2.9 keeps raw + final + mapping.
- **Full-fidelity for the audition** (production may trim later).

## Test set
- The frozen **131-chunk slice** (already holds the **gold note** — the needle) **+ the two
  uploaded claim-file PDFs** (`400-426`, `575-580`) — ~85% of the document *shapes* (notes /
  case-snapshot / boilerplate).
- **One model per audition, one at a time;** compare across runs.

## Seed object types (additive; ⭐ = keeper — Pass 2.9 must NOT drop or consolidate these)
- **Identifiers (anchors):** ⭐`claim_note_id` · ⭐`case_number` · ⭐`benefit_claim_id` ·
  `absence_claim_id` · `payment_id`
- **Parties:** ⭐`claimant` · `case_manager` · ⭐`treating_provider` · ⭐`medical_facility`
  (provider/facility ⭐'d so 2.9 doesn't wrong-merge them)
- **Dates:** `created_modified` · ⭐`decision_date` · ⭐`authorization_date` ·
  ⭐`return_to_work_date` · `event_date`
- **Status & decision:** ⭐`claim_status` · ⭐`benefit_status` (+reason) · `absence_status`
- **Classification:** `note_type` · ⭐`benefit_type` (STD/LTD/RTW)
- **Clinical:** ⭐`diagnosis_code` · ⭐`condition`
- **Rolled up:** `financial_amount` · `note_flags`

## Build guidance
- **TDD — test first, per pass.** Each pass + each `.9` step is its own tested boundary.
- **Reuse what fits from the current probe:** the frozen slice fixture, the `judge` alias +
  grounding-core, `write_enrichment`, the lane-swap/`run.sh` shape, the probe role + isolation
  guard (no prod-write credential, ever).
- **Deliberately left open — let feedback decide, don't pre-spec:** the exact pass-to-pass
  interfaces, the consolidation logic in 2.9, how emergent types are proposed/grown, the
  confidence-plateau threshold.
- Standards unchanged: conda env, file-header docs, ubiquitous language (SCOPE.md §15), provenance
  is code-derived.

## Acceptance (v0 — "it runs end to end")
- A model runs all passes over the slice + the two PDFs; per-pass state is captured; 2.9 keeps
  raw+final+mapping; the **gate** reads per-chunk faithfulness; the **needle** reads the gold
  note's placement when the question is asked. Then we look at the readings and iterate.
