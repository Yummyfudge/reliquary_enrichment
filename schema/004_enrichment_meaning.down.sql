-- Migration 004 (down) — rollback enrichment_meaning.
--
-- DESTRUCTIVE. Engineer writes, Joe applies (D3).

SET search_path TO context_reliquary;

DROP TABLE IF EXISTS context_reliquary.enrichment_meaning;
