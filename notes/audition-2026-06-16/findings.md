# Extraction-Probe Audition — Findings & Flags (2026-06-16)

Independent Architect review of the first extraction-probe audition. The raw artifacts for
the one completed run (qwen3-14b) are archived next to this file in `qwen3_14b/`
(`scorecard.json`, `attempts.jsonl`, `run_meta.json`, `isolation.json`, `progress.log`).
The qwen2.5-72b run left only `run_qwen2_5_72b.log` (a one-line start stub) — see F2.

## TL;DR
- **qwen3-14b completed (131/131 chunks).** Scorecard independently re-derived from the raw
  `attempts.jsonl` — the numbers are faithful.
- **Smoking-gun captured (✅):** qwen3-14b grounded a fact on the gold note (chunk
  `89503c71`, the B. Smith reversal). The decider is a yes.
- **Hidden flag:** it engaged only **56 of 131 chunks** — high precision, low recall on a
  slice built to be dense.
- **qwen2.5-72b has no result.** It hung, was killed, and its partial schema was **dropped
  before it was ever scored** — gone.
- **Process flaw (F4):** the probe drops the `probe_<label>` schema after scoring, so the
  raw grounded records (the evidence text — the provenance itself) are not retained.
  Re-analysis of *what* was grounded is impossible after the fact. Must fix before next run.

## qwen3-14b — independent review

### Verified directly from `attempts.jsonl` (not trusted from the scorecard)
| metric | scorecard | recomputed | match |
|---|---|---|---|
| proposals | 271 | 271 | ✓ |
| located | 258 | 258 | ✓ |
| written (ok=true) | 180 | 180 | ✓ |
| located-but-rejected | 78 | 78 — **all `ungrounded_fact`** | ✓ |
| chunks processed | 131 | 131 (run_meta) | ✓ |
| distinct chunks w/ proposals | — | **56** | (flag F3) |
| gold chunk `89503c71` | smoking-gun ✓ | 1 proposal, grounded | ✓ |

From the scorecard (needs the dropped records, not independently recomputable): grounded
179 / flagged 1 of the 180 written; pass-rate 69.4% (179/258); cross-context entities 26;
wall 5271s (~88 min).

The judge rejected 78 of 258 located proposals — **all `ungrounded_fact`**: the grounding
gate correctly bouncing facts whose asserted values weren't in the quoted span. Integrity
mechanism working as designed.

### Smoking-gun: ✅ captured — one caveat
Gold note `89503c71` drew exactly one proposal and it grounded (`ok=true`, record
`576c2c6b`). Scorer signals: actor=Smith, reversal-direction "back to", condition-swap — all
true. The "back to" broadening was implemented (the gold note says "back to," not
"reverse"), so the ✅ is real, not a loose-matcher artifact. **Caveat:** the schema was
dropped after scoring, so the actual grounded *quote* is gone — structure confirmed, exact
text not re-readable (see F4).

## All flags

### Obvious
- **F1 — qwen2.5-72b hung.** Root cause: the extraction call had **no `max_tokens` cap**; a
  slow/runaway generation wedged the LiteLLM socket (0:07 CPU over ~2h, record count frozen
  at 189). Hardening (`max_tokens` + graceful per-call deadline) added afterward.
- **F2 — qwen2.5-72b partial LOST.** Killed while hung (~189 records / 40 chunks). Reported
  "preserved," but `probe_qwen2_5_72b` was **dropped before being scored** — confirmed gone
  from `pg_namespace`, no scorecard on disk. Unrecoverable. **No qwen2.5-72b data point
  exists.** Lesson: "preserved" claims must be verified against the DB, not trusted.

### Hidden / not in the scorecard headline
- **F3 — coverage 56 / 131.** Only 56 distinct chunks produced any proposal; the other **75
  produced zero** — despite every chunk being selected for mentioning B. Smith / long COVID /
  the Mental-Health limitation / the Feb-2025 dates. High precision, **low recall** on a
  deliberately dense slice. We **cannot tell model-weakness from thin-slice** because the
  qwen2.5-72b baseline that would answer it was lost (F2). This is the concrete cost of F2.
- **F4 — raw evidence not retained.** Dropping `probe_<label>` after scoring destroys the
  grounded records (evidence spans = the actual provenance). Only the scorecard + attempt
  *metadata* survive. For a provenance system, the proof is precisely what isn't kept.
- **F5 — isolation self-check not recorded.** `isolation.json` has
  `prod_untouched / prod_counts_before / prod_counts_after = null`. The wall held
  *structurally* (the `probe` role is permission-denied on prod enrichment — verified
  directly), but the run never captured its own before/after proof.

### Resolved earlier
- Smoking-gun matcher's brittle literal-"revers" dependency broadened to "back to" — fixed;
  the ✅ is genuine.

## Required before the next run (harness changes)
1. **Export raw records BEFORE dropping the schema.** Dump `enrichment_records` (incl.
   `evidence_span`, `provenance_validation`, `fields`, `actor`, `event_date`, `entity_refs`)
   to `records.jsonl` per run, beside `attempts.jsonl`. Re-analysis is non-negotiable. The
   schema may still be dropped — but only **after** the export.
2. **Order: score → export → drop. Never drop unscored.** F2 was a drop-before-capture.
3. **Populate `isolation.json`** — actually record prod counts before/after (F5).
4. **Keep** `progress.log` + the `max_tokens`/deadline hardening (already in for qwen3-14b).

## Status
- **qwen3-14b:** honest single-candidate result, archived here. Grounds cleanly, catches the
  gold note, but leaves >half the relevant chunks untouched.
- **qwen2.5-72b:** no result; partial lost.
- A true two-model comparison requires re-running qwen2.5-72b (now hardened) **with
  raw-result storage in place** so this review can be done on real evidence, not metadata.
