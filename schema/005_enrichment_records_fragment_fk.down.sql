-- Migration 005 (down) — drop the optional claim_chunks FK.
--
-- DESTRUCTIVE (drops a constraint). Engineer writes, Joe applies (D3).

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.enrichment_records
    DROP CONSTRAINT IF EXISTS enrichment_records_source_chunk_fk;
