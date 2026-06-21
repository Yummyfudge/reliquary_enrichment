-- Migration 008 (up) — GIN index on enrichment_records.entity_refs (idempotent backstop).
--
-- What: ensures a GIN index on the denormalized entity_refs jsonb so the codex read APIs
--   (records_by_entity / chunks_by_entity / cooccurrence — the discriminative-weight count,
--   brief §5.2 LANDMINE + §9) resolve via jsonb-containment (`entity_refs @> '[{"entity_id":
--   ...}]'`) instead of a per-entity full scan.
-- Why: entity_refs is denormalized jsonb on enrichment_records (there is NO entity<->record
--   join table); the entity->record reverse lookup MUST be containment-indexed.
--
-- VERIFIED @ codex-refactor PRE-FLIGHT: migration 001 ALREADY creates this exact index
--   (idx_enrichment_records_entity_refs, in 001_enrichment_records.up.sql). On a prod built
--   from 001 this migration is an IDEMPOTENT NO-OP backstop (CREATE INDEX IF NOT EXISTS) — it
--   exists to satisfy the refactor migration manifest and to guarantee the index on any
--   environment predating 001's GIN line. The PROBE schema lacks this index; it is added
--   directly in multipass/isolation_schema.py _tables_ddl (not a prod migration, since the probe schema is
--   recreated each run). Applied by Joe. ADDITIVE (an index).
--   Down in 008_entity_refs_gin_index.down.sql. Requires 001.

SET search_path TO context_reliquary;

CREATE INDEX IF NOT EXISTS idx_enrichment_records_entity_refs
    ON context_reliquary.enrichment_records USING gin (entity_refs);
