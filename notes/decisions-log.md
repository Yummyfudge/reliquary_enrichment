# Decisions Log — reliquary_enrichment build

Resolved decisions that govern the build. Newest first. Each entry: the decision, who made
it, and the why. Pairs with `findings-build-readiness.md` (the questions these answer).

---

## 2026-06-16 — Architect (via PO Joe): extraction-probe decisions (P1-P4)

**P1. Probe shape → candidate extracts, judge fixed.** The candidate (qwen2.5-72b /
qwen3-14b) is the extraction agent: read chunk → propose records (offsets + fields +
actor/date); `write_enrichment` + the fixed Qwen2.5-14B `judge` is the write boundary. We
score the **candidate's extraction**, never the judge. Invariant unchanged.

**P2. Deploy → SPLIT.** Run the probe on **mcp-hub** (candidate via LiteLLM `:4000`, DB via
Postgres `:5432`, both over LAN). **SSH into `llm-lxc` (192.168.1.120)** for lane swaps (NOT
llm-db). Joe cuts the ssh key mcp-hub→llm-lxc per the key standard. Lane-swap primitive
(`audition_loop.sh`'s):
```
ssh llm-lxc "sed -i 's/^PROFILE=.*/PROFILE=<cand>/' /home/joe/lanes/lanes/big-thinker/lane.env; \
             /home/joe/lanes/bin/lane down big-thinker; /home/joe/lanes/bin/lane up big-thinker"
# then poll /health on :8000; restore PROFILE=qwen2.5-72b on a trap at the end.
```
The candidate serves on the stable **`big-thinker`** LiteLLM alias (the underlying PROFILE
swaps). The probe driver calls `big-thinker`; `probe_loop.sh` swaps what it points to.

**P3. Slice freeze → engineer writes the builder; Architect freezes it.** Engineer commits
the slice-builder (seed `89503c71…` + the reversal web terms); the Architect runs it once
under the read-only `probe` role and commits the content-free `chunk_ids.txt` (UUIDs only).
Keeps crown-jewel content out of the engineer's path (mirrors the DB-write split).

**P4. Cross-context (v1) → shared entities across chunks.** Score cross-context as shared
`codex_entities` referenced by records on DIFFERENT source chunks (extraction-only). `link_events`
(Pass-3) proposing is **v2**, out of this probe.

---

## 2026-06-14 — Architect (via PO Joe): the four build-readiness decisions

**D1. Code placement → separate package + thin spine hook.**
Enrichment code lives in *this* repo as its own pip-installable package, editable-installed
(`pip install -e`) into the **`context-reliquary` conda env** (the env the live MCP server runs
in). It registers onto the **existing** FastMCP instance via a ~3-line hook in the spine's
`mcp_server.py`:
```python
from reliquary_enrichment.mcp import register_tools
register_tools(mcp)
```
One server, one port (9666), one service. The hook is the *only* edit to the spine repo.
Do **not** subpackage into `context_reliquary`. _Why:_ "single server" (SCOPE #2) ≠ "single repo";
this satisfies both and keeps the spine untouched but for a reviewable hook.

**D2. Judge → build now behind an interface; Architect wires the live judge.**
Define a `GroundingJudge` interface. Real impl calls LiteLLM model alias **`judge`** (same
LiteLLM base-url as the agent, `http://192.168.1.53:4000`); ship a **fake/stub** for unit tests.
Unit-test the grounding-core against the fake. The `judge` alias → the existing Qwen2.5-14B
container is **being registered by the Architect** before acceptance. Unit-build now;
integration/acceptance waits on that wiring. _Why:_ the judge was down at review time (:8082
refused, no alias); the interface seam unblocks TDD without it.

**D3. DB access → engineer WRITES the DDL; the Architect APPLIES it. Engineer never touches prod.**
_(Superseded the earlier scoped-role plan — Architect ref, 2026-06-14.)_ The medical corpus
stays walled off: the engineer **never** queries or mutates live `context_reliquary`. Write every
migration **+ matching rollback** into `schema/` — `CREATE TABLE` (the four enrichment tables),
`CREATE INDEX`, `ADD COLUMN`, the confirmed `source_chunk_id → claim_chunks` FK. The Architect
applies the additive DDL as **`joe_dba`**. Anything destructive (`DROP`/`TRUNCATE`) or
permissions (`GRANT`/`REVOKE`): write the SQL, **Joe applies**. The exact `claim_chunks` schema
was provided by reference (no prod query needed) — see findings B1/B2; `embedding_qwen3` is
`vector(4096)`, the space `enrichment_meaning.embedding` targets. Engineer validates all DDL on a
local **ephemeral scratch Postgres** (no claim content) — never prod.

**D4. Read tools → build both this pass.**
Build `get_chunk` and `get_neighbors` (read-only, auto-approve), minting **Chunk Handles**
(`F1…`) into the in-process, workstream-keyed handle map. Both reference modes then work:
per-Fragment (Pass 2) and handle (Pass 3).

**Architect action items (in flight; unit work does not block on them):**
register the `judge` LiteLLM alias; provision the `enrichment_ddl` role + cert.

**Build order (unchanged):** conda env → schema DDL → shared grounding-core (TDD vs fake judge)
→ `write_enrichment` → `link_events` → `get_chunk`/`get_neighbors` → the 3-line spine hook.
