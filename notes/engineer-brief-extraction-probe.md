# Engineer Brief — Extraction Probe Harness

## Why
The aider coding sandbox was a **proxy** and a poor evaluator: of six candidates, three "failed" on harness/serving quirks (aider whole-file format, a `--jinja` template mismatch), not on model quality. The agent's real job isn't writing code — it's **extraction**: read a claim-corpus chunk, pull out grounded facts, attest them. So we test on *that*.

Build an **extraction probe** with the same shape as `~/model_sandbox` — **repeatable, isolated, loop-automated** — but it runs the real `write_enrichment` over a locked slice of the real corpus and scores the output.

## What to build
A harness in the `reliquary_enrichment` repo under `probe/`, mirroring `model_sandbox` conventions:
- `probe/run.sh <model_alias> [label]` — run the probe for one model → `probe/results/<label>/`.
- `probe/probe_loop.sh` — swap the lane through candidates, run, score, **always restore the default** (mirror `audition_loop.sh`).
- `probe/slice/chunk_ids.txt` — the **locked** test slice (frozen, committed).
- `probe/RESULTS.md` — the comparison table + per-model detail.

## 1. The slice — locked, cross-linked, no curation
Build it **once**, freeze it as a committed chunk_id fixture so every model runs the exact same input:
- **Seed:** the CRQ-001 gold-note pages (742/672 — the B. Smith reversal) and the eval's page-sets.
- **Expand:** `claim_chunks` where `payload->>'chunk_text' ILIKE` any of the gold note's web — `B. Smith`, `JoAnn F`, `long COVID`, `Mental Health limitation`, the Feb-2025 dates, the RN/claim numbers.
- Result: ~60–100 chunks, **cross-linked by construction** (every chunk ties to the reversal story). Freeze the chunk_id list. This is the fix for "random pages aren't connected."

## 2. Isolation / safety — non-negotiable (crown-jewel data)
- **Corpus is READ-ONLY.** The probe only `SELECT`s `claim_chunks`; it never writes them.
- **Enrichment output goes to a THROWAWAY namespace per run** — a `probe_<label>` schema, **not** prod `enrichment_records`/codex. Created fresh per run, dropped after scoring. A bad or experimental run cannot pollute production enrichment.
- **Scoped `probe` DB role:** `SELECT` on `claim_chunks`, full rights only inside `probe_*` schemas. Not the app role, not `joe_dba`.
- **No prod credential in the harness** (mirror the sandbox's no-secrets posture). The scoped role is the ceiling.
- **The invariant holds:** the judge gates every record exactly as in prod — the probe must not relax grounding to look better.

## 3. The run — `run.sh <model> [label]`
- Point `write_enrichment` at the candidate model (its LiteLLM alias on `:8000`/the lane) + the judge.
- Loop the locked slice; call `write_enrichment` per chunk; write records into the `probe_<label>` schema.
- Capture: records, judge verdicts / `provenance_validation`, per-chunk timestamps. Set `temperature=0` for max determinism.

## 4. Scoring — automated, written to `results/<label>/`
1. **Grounding pass-rate** — % of records the judge marked grounded (from `provenance_validation`). The safety floor.
2. **Cross-context capture** — count of links spanning *different* source chunks (`codex_entities` / `enrichment_links` that connect events across chunks). Does it stitch the reversal's web together vs. extract in isolation.
3. **Smoking-gun (the decider)** — targeted pass/fail: for the gold-note source chunk (`89503c71…`, mislabeled chunk_type "Medical Records Request"), is there a **grounded** record capturing the reversal fact — *B. Smith → long COVID removed → back to Mental Health limitation*? This answers the only question that matters now: does the model even capture the thing the system exists to surface.
4. **Throughput** — chunks/min, records/min (wall-clock from timestamps). Logged, not capped.

## 5. The loop — `probe_loop.sh` (mirror `audition_loop.sh`)
For each candidate: sed the lane profile + `lane down/up`, wait for `/health` (per-model load timeout), `run.sh`, score, move to `results/<label>/`. **Robust:** skip a candidate on any failure; **ALWAYS restore `qwen2.5-72b` via a trap** at the end.

## 6. Output — `RESULTS.md`
Table: `model | grounding% | cross-context links | smoking-gun | throughput | verdict`, plus a per-model detail section like the sandbox `RESULTS.md`.

## Scope
- **IN:** extraction quality — grounding, cross-context, smoking-gun, throughput.
- **OUT (deferred):** the full **Q7 retrieval-lift** ("does enrichment make the gold note *findable* end-to-end"). That needs **CRQ-002 (the retrieval fusion)** built first. The smoking-gun check is the stand-in: it proves the model *captures* the gold fact now; the retrieval payoff is validated once the fusion lands.

## First candidates
`qwen2.5-72b`, `qwen3-14b` — the two clean writers from the audition. GLM-Air (token corruption) and the three unread (harness fails) are out; the new MoEs (Llama-4-Scout-Q4, Qwen3.5-122B-A10B-Q4) once their quants are local.

## Standards / guardrails
- **Conda env (miniforge3), never venv** — build-step 0.
- **DB changes follow the standing rule:** Engineer writes the setup SQL (the `probe` role + `probe_*` schema-create grants); the **GRANT/role bits go to Joe to apply**, additive bits to the Architect. The harness never holds a prod-write credential.
- **Invariant:** code carries the exact tokens, the model reasons, the judge checks, the row attests — the probe must not bypass grounding.
- Source of truth = the mcp-hub repo; tests + docs per project standard.

## Acceptance
- `probe_loop.sh` runs both candidates end-to-end, emits `RESULTS.md`, and leaves prod `enrichment_records`/codex **untouched** (verify: prod row counts unchanged before/after).
- Re-running on the same locked slice yields comparable numbers (not bit-identical — LLM nondeterminism — but the slice + scoring are fixed).
- `qwen2.5-72b` is serving again at the end of the loop.
