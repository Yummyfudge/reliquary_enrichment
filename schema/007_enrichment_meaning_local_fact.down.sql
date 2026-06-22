-- Migration 007 (down) — restore questions_answered + drop the local-fact constraints.
--
-- DESTRUCTIVE. Engineer writes, Joe applies (D3). Re-adds questions_answered as the original
--   NOT NULL DEFAULT '[]'::jsonb (the data dropped by 007 up is NOT recoverable). Drops the
--   UNIQUE + FK in reverse order.

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.enrichment_meaning
    ADD COLUMN IF NOT EXISTS questions_answered jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE context_reliquary.enrichment_meaning
    DROP CONSTRAINT IF EXISTS enrichment_meaning_source_chunk_fk;

ALTER TABLE context_reliquary.enrichment_meaning
    DROP CONSTRAINT IF EXISTS enrichment_meaning_source_chunk_uq;
