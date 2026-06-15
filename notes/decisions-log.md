# Decisions Log — reliquary_enrichment build

Resolved decisions that govern the build. Newest first. Each entry: the decision, who made
it, and the why. Pairs with `findings-build-readiness.md` (the questions these answer).

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

**D3. DB access → additive DDL via a scoped role; destructive ops to Joe.**
Apply **additive** DDL to live `context_reliquary` — `CREATE TABLE` (the four enrichment
tables), `CREATE INDEX`, `ADD COLUMN` — plus `information_schema` reads, connecting as a scoped
**`enrichment_ddl`** role (Architect provisioning) that **cannot** read `claim_chunks` content
or `DROP`/`GRANT`. Spine tables untouched. **Every migration ships a matching rollback** in
`schema/`. Any `DROP`/`TRUNCATE`/`GRANT`/`REVOKE`: **write the SQL, do not apply — hand to Joe.**
Write the DDL now; the role + cert land before apply.

**D4. Read tools → build both this pass.**
Build `get_chunk` and `get_neighbors` (read-only, auto-approve), minting **Chunk Handles**
(`F1…`) into the in-process, workstream-keyed handle map. Both reference modes then work:
per-Fragment (Pass 2) and handle (Pass 3).

**Architect action items (in flight; unit work does not block on them):**
register the `judge` LiteLLM alias; provision the `enrichment_ddl` role + cert.

**Build order (unchanged):** conda env → schema DDL → shared grounding-core (TDD vs fake judge)
→ `write_enrichment` → `link_events` → `get_chunk`/`get_neighbors` → the 3-line spine hook.
