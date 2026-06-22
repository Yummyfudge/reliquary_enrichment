-- Migration 008 (down) — no-op (the entity_refs GIN index is owned by migration 001).
--
-- 008 up is an IDEMPOTENT BACKSTOP (CREATE INDEX IF NOT EXISTS). On any environment the
-- index idx_enrichment_records_entity_refs is created and owned by 001_enrichment_records.up.sql.
-- Reversing 008 must NOT drop the index 001 depends on — so down is intentionally a no-op.
-- To remove the GIN index entirely, roll back 001. Engineer writes, Joe applies (D3).

SET search_path TO context_reliquary;
-- intentionally empty: see header.
