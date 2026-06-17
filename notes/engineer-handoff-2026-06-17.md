# Engineer Handoff — Four-Model Audition + Status Heartbeat (2026-06-17)

From: Architect. To: Sr. Engineer. Pairs with the lane **BATON** (new — §4). The raw-storage /
isolation / scoring requirements from `audition-2026-06-16/engineer-handoff.md` still stand and
are restated in §5; this doc replaces only the *model-readiness* picture.

## 0. Read this first — the "GPU wedge" was not real
The wedge that paused everything was a **test artifact**, not hardware. The thinking models were
probed with a tiny `max_tokens`, so they spent the whole budget inside their hidden `<think>`
block and returned empty `content` — which I misread as a dead GPU. big-thinker served OpenWebUI
fine the entire time; the cold power-cycle was unnecessary. **Why it matters to you: the same
starved-cutoff will sink the audition if the harness uses a small `max_tokens` or a short
per-call deadline on these models.** That is the #1 thing this handoff fixes (§2).

## 1. The four candidates — all validated, all serve
Re-validated with a real budget, reading `content` **and** `reasoning_content`, against the live
lane. Profiles: `llm-lxc:/home/joe/lanes/profiles/`, all `ENGINE=llamacpp`, `-c 16384 --jinja`:

| profile | weights | thinking? | validated extraction |
|---|---|---|---|
| `llama-3.3-70b` | Q6_K_L | no | ✅ clean JSON, verbatim quotes |
| `llama-4-scout` | UD-Q4_K_XL (62 GB MoE) | no | ✅ clean JSON, 5 facts, **tightest** spans |
| `gemma-4-31b` | UD-Q8_K_XL | **yes** | ✅ granular (5 facts), ~800 think-tokens/call |
| `qwen3.5-122b` | UD-Q4_K_XL (77 GB MoE) | **yes** | ✅ clean — **requires thinking OFF** |

(Reference: `qwen3-14b`, audition #1's model + currently serving OpenWebUI, is also a thinking
model — same handling as qwen3.5.)

## 2. THE harness fix — kill the arbitrary cut-offs (blocking)
Audition #1 timed gemma out everywhere; cause = thinking + a short read-deadline, **not** a slow
or broken model. Two settings:

1. **`max_tokens` on the extraction call: high (≥1536)**, not 64/400. A thinking model needs room
   for `<think>` *plus* the answer; with a small cap it returns empty and looks broken.
2. **Per-call deadline (the HTTP read-timeout): generous (≥180s/call)** for the thinking models —
   their `<think>` pass is real latency. Keep the graceful-skip; just give it real headroom.

**Thinking control, per model:**
- **llama-3.3-70b, llama-4-scout** — non-thinking. Nothing special; a modest `max_tokens` is fine.
- **qwen3.5-122b** — **must** run thinking-OFF or it never answers (burns >2048 tokens
  deliberating on a trivial input). Verified working via per-request
  `"chat_template_kwargs": {"enable_thinking": false}` → answers in <100 tokens.
- **gemma-4-31b** — thinking-ON works *and* gives the most granular output; just give it the
  budget (≥1536) + deadline. (A gemma thinking-off toggle is unconfirmed; not needed — it finishes.)
- **qwen3-14b** (if included) — same family as qwen3.5; `enable_thinking:false` expected to work
  (verify on first use).

Recommended for a **fair** comparison: run thinking-OFF where the toggle exists (qwen3.5,
qwen3-14b) and budget-generous where it doesn't (gemma), so you compare extraction, not
deliberation length. **Architect TODO:** bake the thinking-off flag server-side into the thinking
profiles (verifying `--chat-template-kwargs`) on the next lane window, so the probe stays
model-agnostic. Until then, set it per-request as above.

## 3. Status heartbeat (new — Joe's ask)
Emit a one-line status to **both `progress.log` and stdout, every ~15 min of wall-clock**, with:
- **progress** — `chunks_done / total (pct%)`
- **rolling chunk accept-rate** — chunks with ≥1 accepted (`ok=true`, grounded) record ÷ chunks
  processed so far. (This is the live coverage/recall signal — the audition-#1 F3 metric, surfaced
  *as it runs* instead of buried at the end.)
- **current tok/s** — rolling throughput over the last window (completion tokens ÷ seconds), **not**
  the lifetime average.

Suggested line:
```
[HB +42m] 47/131 (36%) | accept 31/47 chunks (66%) | 18.4 tok/s | ETA ~80m
```
ETA optional but welcome. Cadence is time-based (~15 min), not per-chunk, so a long stall shows.

## 4. The lane + the BATON (new)
- Lane = the 3 GPUs on `llm-lxc`, LiteLLM alias `big-thinker`, profile-swappable
  (`bin/lane swap`). One operator at a time.
- **New file: `llm-lxc:/home/joe/lanes/BATON`.** Read it before touching the lane. Rule: only the
  current HOLDER runs `lane up/down/swap`; release by writing a `DONE` line and flipping HOLDER;
  never pick up on the assumption the other is finished — wait for the explicit "I'm Done"; Joe's
  real-time direction overrides.
- Right now **HOLDER: architect**, lane serving OpenWebUI (`qwen3-14b`). I'll flip HOLDER to
  engineer when Joe gives the go — **do not swap profiles until then** (it would drop Joe's
  OpenWebUI session).

## 5. Still required from audition #1 (unchanged)
Blocking before, blocking now:
1. **Export raw `enrichment_records` (incl. `evidence_span`) to `records.jsonl` BEFORE dropping the
   schema** — re-analysis must be possible (audition #1's evidence is gone).
2. **Order: score → export → drop. Never drop unscored** — that's how the qwen2.5-72b partial was lost.
3. **Populate `isolation.json`** — prod counts before/after, assert unchanged.
4. **Surface coverage in the scorecard** — `chunks_with_proposals`.
5. **Reuse the frozen slice** `probe/slice/chunk_ids.txt` (131 chunks) exactly — comparability
   depends on it being identical.

## 6. Standing boundaries (unchanged)
- `probe` role only; no prod-write credential; corpus read-only; throwaway `probe_<label>` schemas.
  The structural wall stays.
- Do **not** kill / swap / restart a run without Joe's explicit OK.
- "Preserved / done / safe" claims get verified against the DB/disk before they're reported.
