# Engineer Handoff — Extraction Probe, after Audition #1 (2026-06-16)

From: Architect. To: Sr. Engineer. Pairs with `findings.md` (the independent review) and the
`qwen3_14b/` artifacts in this folder.

## 1. Where things stand
- **qwen3-14b: complete and reviewed.** Ran all 131 chunks; scorecard independently verified
  against the raw `attempts.jsonl` (271 proposals / 258 located / 180 written — all match).
  Smoking-gun ✅ (gold note `89503c71` grounded). Artifacts archived here.
- **qwen2.5-72b: no result.** It hung (no `max_tokens` cap → wedged LiteLLM socket), was
  killed, and its partial schema was dropped **before it was scored**. Unrecoverable. There
  is no 72B data point.
- **Net:** an honest single-candidate result, not a comparison.

## 2. What the audition proved
- The real path works end-to-end on live corpus + the real judge: candidate extracts → code
  locates the quote → judge grounds → row attests. The grounding gate is doing its job
  (78/258 located proposals correctly bounced, all `ungrounded_fact`).
- qwen3-14b is **high-precision, low-recall**: 69% of its proposals ground, but it produced
  proposals on only **56 of 131 chunks** — the other 75 (all entity-matched to the reversal
  web) returned nothing. Whether that's the model or the slice is unknowable without the 72B
  baseline we lost. That ambiguity is the concrete cost of the partial loss.

## 3. Required before the next run (blocking)
1. **Export raw records before dropping the schema.** Per candidate, dump
   `enrichment_records` — including `evidence_span`, `provenance_validation`, `fields`,
   `actor`, `event_date`, `entity_refs` — to `records.jsonl` beside `attempts.jsonl`.
   Independent re-analysis (including re-reading the smoking-gun quote) must be possible after
   the run. It currently is not: the qwen3-14b evidence is gone.
2. **Order: score → export → drop. Never drop unscored.** The qwen2.5-72b partial was dropped
   before capture and reported "preserved." Treat a schema as live until its score *and* raw
   export are on disk.
3. **Populate `isolation.json`.** Record prod `enrichment_records`/codex counts before and
   after; assert before == after. Currently null. The wall held structurally (the `probe`
   role is permission-denied on prod enrichment — Architect-verified), but the run kept no
   proof of its own.
4. **Surface coverage in the scorecard.** Add `chunks_with_proposals` (and ideally
   `chunks_empty`) so the recall signal isn't buried under `chunks_seen=131`.

## 4. The next run
- **Hardened qwen2.5-72b re-run** — `max_tokens` + the graceful per-call deadline are already
  in; add the raw-record export from §3.1. Goal: the real two-model comparison **and**
  re-analyzable evidence this time.
- **Reuse the frozen slice** `probe/slice/chunk_ids.txt` (131 chunks) exactly — do not rebuild
  it; comparability depends on it being identical.
- Restore `PROFILE=qwen2.5-72b` on the lane at the end (trap), as before.

## 5. Acceptance (next run is "done right" when)
- `records.jsonl` present and non-empty for each candidate, with `evidence_span` populated.
- `isolation.json` shows prod counts captured and unchanged.
- `scorecard.json` includes `chunks_with_proposals`.
- No schema was dropped before its score + raw export landed on disk.
- `RESULTS.md` carries both candidates (qwen2.5-72b full + qwen3-14b), labeled comparable.

## 6. Standing boundaries (unchanged)
- `probe` role only; no prod-write credential; corpus read-only; throwaway `probe_<label>`
  schemas. The structural wall stays.
- **Do not kill, swap, or restart a run without Joe's explicit OK** — the standing rule after
  the qwen2.5-72b kill. Diagnose and report; let him make the call.
- "Preserved / done / safe" claims get verified against the source of truth (DB, disk) before
  they're reported. On this project, verifying the claim *is* the work.
