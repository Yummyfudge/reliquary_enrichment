# Multi-Pass Test Harness — v0 Design (Engineer interpretation)

_2026-06-17. Retires the single-pass probe. The brief
`notes/engineer-brief-multipass-test.md` is referenced but **not yet in the repo** — this
captures my interpretation from Joe's message so it can be corrected early (build it, run it,
let feedback fill the gaps). Not a finished spec._

## Why we're here
Single-pass did the whole job in one call per chunk (the "elephant") — that timed models out
(gemma: **105/131 chunks ReadTimeout**, even at a 600s deadline). Multi-pass = one focused job
per pass, each pass running the whole file before the next. Smaller jobs → models don't starve.

## The shape (passes, in order)
1. **prose vs non-prose** — classify each chunk (narrative vs kv/list/form). Routes handling.
2. **object-types** — per chunk, what TYPES of records it holds (not values).
   - **2.9 consolidate** — merge per-chunk types → one emergent schema. **Keep raw + final +
     the mapping** (glass box).
3. **fill-values** — extract the actual values into the 2.9 schema; grounded + judge-checked.
   **Judge-feedback retry loop; retry bound = confidence-plateau** (stop when confidence stops
   improving). Reuses `write_enrichment` + the grounding core.
4. **signal-keywords** — per chunk, the claim-relevance signals/keywords.
   - **4.9 cleanup** — dedupe/normalize.
5. **meaning** — the per-chunk `claim_meaning` (what we embed for the needle).

## Two SEPARATE readings (never combined)
- **GATE — per-chunk faithfulness (judge-side).** Does each pass's output stay faithful to the
  chunk? The fixed Qwen2.5-14B judge rules. Measures **precision** of the passes.
- **NEEDLE — gold-note rank (big_thinker-side).** Ask the question; where does the gold note
  (`89503c71`, the B. Smith reversal) land in retrieval over the enriched corpus? Measures
  **findability** — the actual goal.

## Glass box
Every pass writes its input + output state to disk per chunk, so each pass is inspectable.
2.9 specifically retains raw/final/mapping.

## Status heartbeat (REQUIRED — carries the audition-2 §3 line forward, adapted)
Emit a status line to **both `progress.log` and stdout, every ~5 min of wall-clock**
(`MULTIPASS_STATUS_INTERVAL_S`, default 300). Multi-pass aware — it must show which pass and
overall progress across ALL passes, not just within one pass:

```
Test running | <model> | Pass <p>/<N> | Chunk <c>/<total> | <tok/s> tok/s | <pct>% total
```
- **Pass `p`/`N`** — current pass index / total passes in the pipeline.
- **Chunk `c`/`total`** — current chunk / total inputs this pass (the slice + the 2 PDFs' chunks).
- **tok/s** — rolling throughput (last window), not lifetime average.
- **`pct`% total** — overall = `(completed_passes × total + c) / (N × total) × 100` (every pass
  runs every chunk, so the denominator is the SUM of chunks across all passes). This is the "% of
  the whole test" Joe asked for, so a long pass doesn't read as a stall.

Time-based cadence (~5 min), not per-chunk, so a stall still shows. The pipeline runner owns it.

## Architecture — greenfield package, reuse the bones
New package `src/reliquary_enrichment/multipass/`:
- `pass_base.py` — the `Pass` boundary (in → state out) + per-pass state capture.
- `passes/` — `pass1_prose`, `pass2_objecttypes`, `pass2_9_consolidate`, `pass3_fillvalues`,
  `pass4_keywords`, `pass4_9_cleanup`, `pass5_meaning` — each its own TDD'd boundary.
- `pipeline.py` — runs passes in order over the slice (+ PDFs), captures state.
- `gate.py` (faithfulness) / `needle.py` (gold rank) — the two readings.
- `cli.py` + top-level `multipass/` scripts (run.sh, state output).

**Reuse (the probe's bones):** `reliquary_enrichment.grounding` (judge + core), `write_enrichment`,
`postgres` stores + `probe.schema`/`probe.export` (§5 helpers), the frozen slice
`probe/slice/chunk_ids.txt` (identical), the lane-swap. **Carry forward (still blocking):**
max_tokens ≥1536 + deadline ≥180s, thinking-OFF for qwen profiles, raw `records.jsonl` before
drop, order score→export→drop, populate `isolation.json`.

**Retire (no bloat):** the single-pass orchestration (`probe.extraction`/`runner`/`scoring`/
`cli`/`report`, `probe/run.sh`, `probe_loop.sh`) stays as the archived probe — not extended.
The multipass is its own clean package; shared helpers are imported, not duplicated.

## Build order (TDD, pass by pass)
v0 = runs end-to-end over the slice (+ PDFs once named), per-pass state captured, **GATE read**.
Order: framework → Pass 1 → 2 → 2.9 → 3 → 4 → 4.9 → 5 → gate. Each lands with tests against
fakes + the scratch DB; the real candidate run needs the lane (re-acquire baton).

**RESOLVED 2026-06-17 (Joe):**
- **NEEDLE deferred for v0** — v0 reads the GATE (faithfulness) only; the needle (gold-rank over
  fused retrieval) comes in a later iteration once the embed cutover / CRQ-002 is confirmed live.
- **Test PDFs = corpus chunks for the page ranges** (`Aflac_claim_file_400-426`, `_575-580`):
  comparable units (same chunker as the slice), the real production input, no OCR confound. Raw-PDF
  ingestion is a SEPARATE later test, swapped behind the same ChunkRef interface. **DEDUP the
  union:** slice (notes-section) + ranges (400-426, 575-580 = progress-notes) may overlap (found 4
  slice chunks in-range) — union by chunk_id so nothing is processed or counted in /~330 twice.

- **Pass 3 confidence-plateau (the retry bound) — exact rule:** each retry, read the model's
  self-reported confidence; **STOP when a retry fails to beat the best-so-far confidence by ≥
  epsilon.** Self-terminating (confidence∈[0,1], running max only climbs, each continue costs ≥
  epsilon → ≤ ~1/epsilon retries; bound EMERGES from epsilon, no magic count; "beat best-so-far"
  survives oscillation/saturation). **epsilon** is the one tunable (start ~0.05); **log the full
  per-chunk confidence trajectory** (part of the glass-box capture) — that's what we tune from.
  **Loop and judge stay SEPARATE:** the judge's feedback SHAPES each retry but the PLATEAU decides
  the stop. A low plateau ≠ loop failure (means "more retries won't help"); the judge's gate at
  persist then accepts/flags/bounces. Loop owns "keep trying?", judge owns "is it right?". Never
  read a high plateau as "correct" — self-reported confidence is weak.

## Flagged gaps — need feedback (building reasonable defaults meanwhile)
1. **Which two claim PDFs?** Candidates under `context_reliquary/aflac_claim_intake/`:
   `source/evidence_master.pdf` + `evidence_working_ocr.pdf` (the full claim file — likely), or
   the `Mini-Split-*` pair. Assuming the evidence pair until told otherwise.
2. **NEEDLE infra.** "Where the gold note lands when you ask the question" implies embed the
   pass-5 meaning → fuse with the corpus → query → rank. The Qwen3 embed cutover + retrieval
   fusion (CRQ-002) may not be live. **v0 proxy:** rank the gold note's pass-5 meaning vs the
   other chunks' meanings for the reversal question via the existing embed/query path; swap in
   the real fused retrieval when CRQ-002 lands. Confirm.
3. **Confidence-plateau** (Pass 3 retry bound) — exact signal? v0: retry while the judge's
   grounded-value count strictly increases; stop after K with no gain.
4. **Per-pass model** — all passes on the one candidate (big_thinker), judge fixed? Assuming yes.
5. First lane candidate to audition on multipass: **llama-4-scout** (per Joe).
