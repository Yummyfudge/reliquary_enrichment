# `schema/` — enrichment DDL (additive, beside `claim_chunks`)

The four enrichment tables live in the **`context_reliquary`** schema, next to `claim_chunks`
(brief §3.1). All DDL here is **additive** (`CREATE TABLE/INDEX/FUNCTION/TRIGGER`,
`ADD CONSTRAINT`). Per **Decision D3** the **engineer WRITES** these migrations and validates
them on a local scratch Postgres; the **Architect APPLIES** them to live `context_reliquary` as
**`joe_dba`**. The engineer never touches prod (the corpus stays walled off). Every `*.up.sql`
has a matching `*.down.sql`.

## Apply order (up)
```
001_enrichment_records.up.sql      # records first — entities & links reference it
002_codex_entities.up.sql          # entities (first_seen_record -> records)
003_enrichment_links.up.sql        # links (record_a/b -> records, event_entity -> entities)
004_enrichment_meaning.up.sql      # per-chunk meaning (embedding column DEFERRED)
005_enrichment_records_fragment_fk.up.sql   # OPTIONAL: FK into claim_chunks; skip if no REFERENCES priv
```
Rollback runs in **reverse**: `005 → 003 → 002 → 001` (004 is independent). The shared
write-once guard function is dropped by `001.down` (the last teardown step) — by then both
triggers are gone (each `DROP TABLE` removes its own trigger).

## Roles — who does what
| Role | Used by | Notes |
|---|---|---|
| `joe_dba` | the Architect, to APPLY migrations | full privileges; runs `001-005.up.sql` + `grants.runtime.sql` |
| `context_reliquary_app` (runtime) | the live MCP tools | reads `claim_chunks`, SELECT/INSERT enrichment tables (after grants); **no** UPDATE/DELETE on records & links (write-once) |

The engineer applies nothing to prod — only validates on an ephemeral scratch Postgres.

## For the Architect / Joe to apply
- **`001-005.up.sql`** — the additive schema (applied as `joe_dba`).
- **`grants.runtime.sql`** — grants the runtime app role SELECT/INSERT on the new tables
  (and UPDATE on `codex_entities` only). **The tools cannot run live until this is applied.**
- **All `*.down.sql`** — destructive (`DROP`); applied only on an intentional rollback.

## Design notes
- **Write-once** is enforced two ways: a `BEFORE UPDATE OR DELETE` trigger
  (`reliquary_enrichment_forbid_mutation`) on `enrichment_records` and `enrichment_links`,
  **and** the grant layer (no UPDATE/DELETE granted). Corrections are new INSERTs via
  `enrichment_records.supersedes`.
- **Provenance Validation** is `jsonb`:
  `{ verdict, judge_model, judge_version, evidence_sha256, source_sha256, validated_at }`
  (records) / both-span hashes (links). The hashes freeze the exact bytes grounded against —
  tamper-evident on audit.
- **Dedupe key** for entities is `UNIQUE (entity_type, canonical)` — exact match to start
  (codex §9-B "start minimal"); fuzzy canonicalization is a later, curation-gated task.
- **`event_date`** is `text`, not `date`, to tolerate normalized-but-partial values; the
  `date` Entity canonicalizes (parsed ISO can live in `codex_entities.metadata`).
- **`enrichment_meaning.embedding`** is deferred (Qwen3 dimension unsettled — brief §4/§7).
