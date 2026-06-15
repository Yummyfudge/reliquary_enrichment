-- Migration 001 (down) — rollback enrichment_records.
--
-- DESTRUCTIVE. Per Decision D3 the engineer WRITES this but does NOT apply it;
-- DROP is handed to Joe. This is the LAST teardown step: run 003.down then 002.down
-- first (they reference enrichment_records). DROP TABLE removes the table's own
-- trigger automatically; the shared guard function is dropped here, last, once no
-- trigger depends on it.

SET search_path TO context_reliquary;

DROP TABLE IF EXISTS context_reliquary.enrichment_records;  -- add CASCADE only if dependents intentionally go too

-- Shared mutation-guard function — dropped last, after both triggers (records via the
-- DROP TABLE above, links via 003.down) are gone.
DROP FUNCTION IF EXISTS context_reliquary.reliquary_enrichment_forbid_mutation();
