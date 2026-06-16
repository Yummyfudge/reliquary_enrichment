# Handoff — Extraction Probe Built (Engineer → Architect + PO)

_2026-06-16. The probe is built, green, and validated end-to-end against the real candidate +
real judge on a scratch DB. Here's what it surfaced (incl. a prod bug it caught) and the
setup that's yours._

## What shipped (all TDD)
**83 tests pass** (73 unit + 10 integration). The harness under `probe/` + the importable
`reliquary_enrichment.probe` package:
- **Candidate-as-extractor driver** (P1): the candidate proposes records (verbatim quote +
  fields + actor/date); code locates the quote → offsets → real `write_enrichment` (fixed judge
  gates). Pointing interface = **verbatim quote**, not raw char offsets (LLMs can't count
  chars; a corrupted quote fails to locate and is never stored — invariant intact).
- **Isolation:** schema-split stores (writes target a throwaway `probe_<label>` schema, corpus
  reads stay `context_reliquary`); fresh-per-run schema, dropped after scoring; scoped `probe`
  role with **no grant on prod enrichment** (structural wall); prod-untouched count guard.
- **Scoring → RESULTS.md:** grounding pass-rate, cross-context (shared entities across chunks,
  P4), smoking-gun (the decider), throughput. `run.sh` + `probe_loop.sh` (ssh-llm-lxc lane swap
  + **restore-`qwen2.5-72b`-on-trap**).
- **End-to-end real run** (big-thinker + live judge, gold-note chunk on scratch):
  **grounding 100%, smoking-gun ✅ captured, prod untouched, schema dropped.**

## What the probe SURFACED
1. **🔴 Prod bug in `write_enrichment` — FIXED.** `render_record_claim` put `record_type` into
   the *grounded* claim, so the judge demanded the category label ("claim_status_change") appear
   literally in the span → **spurious `ungrounded_fact` for every fact record** whose
   record_type words aren't in the text. This affected **prod extraction**, not just the probe.
   The fake-judge unit tests couldn't catch it; the probe's real judge did immediately. Fix:
   `record_type` excluded from the judged claim (it's a label, not a value); regression test
   added. _This alone justifies testing on the real job._
2. **Extraction prompt — quote must cover all asserted values.** Candidates quoted half a
   sentence while asserting whole-sentence values → legitimate ungrounded. Strengthened the
   extraction system prompt to require the quote contain every asserted value (constant across
   candidates; the **judge is untouched** — this is fair-prompt quality, not grounding
   relaxation). After it: big-thinker grounds + captures the smoking gun.
3. **Pointing interface (verbatim quote) — flagged for blessing.** It keeps the invariant (stored
   bytes are code-sliced; corrupted quotes drop) and is realistic, but it's a design choice worth
   your confirmation.

## Your setup before the first real audition
1. **Joe — `probe/sql/probe_role.sql`:** create the scoped `probe` role + grants; set its auth
   (cert/password per the standard). Role/GRANT split — engineer doesn't apply.
2. **Joe — ssh key mcp-hub → llm-lxc** (192.168.1.120): `probe_loop.sh` swaps the `big-thinker`
   lane over ssh (Decision P2).
3. **Architect — freeze the slice:** run `probe/slice/build_slice.sql` as the read-only `probe`
   role, commit `probe/slice/chunk_ids.txt` (content-free UUIDs; Decision P3). Tune `web_terms`
   to ~60-100 chunks.
4. **Confirm the lane mapping:** `big-thinker` alias ↔ `qwen2.5-72b` / `qwen3-14b` PROFILEs
   (the aliases drifted since the last session — `r9700_qwen72b` is gone, `big-thinker` is new).

## Acceptance (from the brief) — status
- `probe_loop.sh` runs both candidates end-to-end + emits RESULTS.md: **ready** (gated on the ssh
  key + frozen slice above).
- Re-running on the locked slice yields comparable numbers: **yes** (temperature=0; slice +
  scoring fixed; LLM nondeterminism aside).
- `qwen2.5-72b` serving again at the end: **yes** — restored on the loop's EXIT trap.
- Prod `enrichment_records`/codex untouched: **yes** — structural (no grant) + verified by the
  before/after count guard (proven in the dry run).
