# Findings — Extraction Probe Design Review (Engineer → Architect + PO)

_2026-06-16. Before building, per the brief ("Flag anything you'd design differently before
you build it") + the three-party discipline. Reviewed against the live mcp-hub system._

The probe is a good idea and buildable. Most of it (driver + isolation + scoring + tests) I
can build host-agnostically right now. A few design points fight the brief's framing or need
your call first.

## A. The architectural crux: the candidate is the EXTRACTOR; the judge is held FIXED
`write_enrichment` is a validated *write boundary*, not an extractor — its internal judge is
the fixed Qwen2.5-14B. The model under test (qwen2.5-72b vs qwen3-14b) is the **agent that
reads a chunk and PROPOSES records** (char offsets + record_type + tier + fields + actor +
date + claim_relevance); `write_enrichment` then slices, judges, and writes. So the probe
must include a scoped **extraction driver + prompt** — essentially Pass-2 extraction, frozen
to the slice. **The candidate is the only variable; the judge stays fixed** — otherwise we'd
be scoring the judge, not the candidate. The invariant holds unchanged (candidate points,
code copies, judge gates, row attests). _Confirm this framing — it's the biggest wasted-work
risk if I've read it wrong._

## B. Where the probe RUNS + how lanes are swapped — I can't resolve this from here  ⚠️ blocker
- `~/model_sandbox`, `audition_loop.sh`, and lane control (`:8000`, `lane down/up`) live on the
  **GPU host (llm-db, .53)** — not on mcp-hub. From mcp-hub only LiteLLM `:4000` and Postgres
  `:5432` are reachable; `:8000`/lane control are **closed**, and I have **no configured ssh
  key** to .53. I cannot see the sandbox scripts to mirror them, nor swap a lane from here.
- The **run + score** half is host-agnostic: the driver calls the candidate by **LiteLLM
  alias** (`:4000`) and writes to Postgres (`:5432`) — works from anywhere on the LAN.
- The **loop** half (`probe_loop.sh`: sed lane profile, `lane down/up`, wait `/health`, restore
  trap) is intrinsically GPU-host-side.
- **Recommendation:** deploy + run the whole probe on **llm-db** (mirror model_sandbox exactly
  — DB, judge, candidate lanes all local; scoped `probe` role local). I'll build it
  host-agnostic so it runs there cleanly. **I need:** (1) confirm the deploy host, and (2) the
  lane-swap primitive (`audition_loop.sh`'s exact mechanism — a `lane` CLI? sed a llama-server
  unit + `systemctl`? a LiteLLM config reload?) so `probe_loop.sh` matches it.
- **Candidate aliases drifted:** LiteLLM now shows `big-thinker` (new) and `judge`;
  `r9700_qwen72b` is gone. The probe will call a **configurable candidate alias** (env
  `PROBE_CANDIDATE_MODEL`); confirm which aliases map to `qwen2.5-72b` / `qwen3-14b`.

## C. Freezing the slice reads crown-jewel CONTENT — same wall as the corpus
Building the slice = `ILIKE` over `payload->>'chunk_text'` for the reversal's web (`B. Smith`,
`JoAnn F`, `long COVID`, `Mental Health limitation`, Feb-2025 dates, RN/claim numbers). That
reads prod claim **content** — which auto-mode (correctly) blocked me from doing last build.
**Plan (mirrors the DB split):** I write a committed **slice-builder script** (seed = the gold
note `89503c71…` + the known web terms); the **Architect/Joe runs it once** under the read-only
`probe` role to emit + commit `probe/slice/chunk_ids.txt`. The frozen fixture is then content-
free (just UUIDs). _Alternative: I run the read-only builder now with explicit approval._

## D. Isolation — the refactor it forces, and the role split
- **Stores hardcode `context_reliquary.`** for every write. For isolation I'll **split read-
  schema from write-schema**: `claim_chunks` reads stay `context_reliquary` (corpus, read-only);
  record/entity/link writes target a configurable schema, set to **`probe_<label>`** per run.
  Small, clean refactor (a `schema=` arg, default unchanged) — keeps prod behavior identical.
- **`probe_<label>` is created fresh per run and dropped after scoring.** For dynamic labels the
  `probe` role needs **CREATE on the database** (to make/drop its own `probe_*` schemas).
  Least-privilege otherwise: `SELECT` on `claim_chunks`, **no** write on `context_reliquary`
  enrichment tables at all (so "no prod-write credential" is structural, not just policy).
- **Per the standing DB split:** I write the `probe` **role + GRANT** SQL → **Joe applies**; the
  additive `probe_*` table DDL is schema-parametrized and applied **by the harness at runtime as
  the probe role** (that's the throwaway-per-run design). Confirm the CREATE-on-db grant is OK,
  or pre-provision a fixed probe schema instead.
- **Prod-untouched guard:** snapshot `context_reliquary.{enrichment_records,codex_entities,
  enrichment_links}` counts before/after each loop; assert unchanged (belt to the role's
  suspenders).

## E. Smoking-gun + scoring notes
- Gold note `89503c71…` MUST be a seed of the slice (it is, by construction). Smoking-gun =
  a **grounded** record in the probe schema with `source_chunk_id = 89503c71…` whose
  actor/fields capture the triad *B. Smith → long COVID removed → back to Mental Health
  limitation*. I'll score it as a targeted pass/fail with a transparent matcher (actor=B. Smith
  + reversal/limitation terms in the grounded fields), and log the matched record for audit.
- **Cross-context** = `enrichment_links` whose two records sit on **different** source chunks
  (links spanning the web), plus shared `codex_entities` referenced by records on different
  chunks. Note: getting links requires the driver to also propose `link_events` (Pass-3), or we
  measure only the shared-entity form. **Decision:** the probe drives **extraction
  (write_enrichment) first**; cross-context is scored primarily via **shared entities across
  chunks**, with `link_events` proposing as a stretch goal (flag if you want full Pass-3 in v1).
- `temperature=0`; throughput from per-chunk timestamps; nothing capped.

## What I'll build now (answer-independent)
The schema-split refactor, the extraction driver (candidate→proposals→write_enrichment), the
probe-schema setup/teardown, the scoring (grounding% / cross-context / smoking-gun / throughput
→ `RESULTS.md`), `run.sh`, and the role/DDL SQL — all TDD'd against the **scratch Postgres** +
a fake/real candidate via LiteLLM, never prod. `probe_loop.sh`'s lane-swap I'll draft to the
audition pattern and finalize once B is answered.
