-- Migration 003 (down) — rollback enrichment_links.
--
-- DESTRUCTIVE. Engineer writes, Joe applies (D3). Teardown order is 003 -> 002 -> 001
-- (links reference records & entities, entities reference records). DROP TABLE drops
-- the table's own trigger automatically. The SHARED guard function is dropped by
-- 001.down (the last teardown step) — NOT here — because enrichment_records' trigger
-- still depends on it until 001 runs.

SET search_path TO context_reliquary;

DROP TRIGGER IF EXISTS trg_enrichment_links_immutable
    ON context_reliquary.enrichment_links;

DROP TABLE IF EXISTS context_reliquary.enrichment_links;
