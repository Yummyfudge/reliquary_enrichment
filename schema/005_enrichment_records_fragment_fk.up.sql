-- Migration 005 (up) — FK enrichment_records.source_chunk_id -> claim_chunks(claim_chunk_id).
--
-- What: a foreign key making it structurally impossible to write an Enrichment Record
--   whose source_chunk_id is not a real Fragment. CONFIRMED wanted by the Architect ref
--   (2026-06-14); applied by joe_dba alongside 001-004.
-- Why: defense-in-depth for the 89503 invariant. The grounding core ALREADY rejects a
--   missing Fragment at the application layer (resolve+load, write_enrichment §5 steps
--   1-2); this FK is the belt to that suspenders — corruption can't even reach the row.
--
-- Kept as a SEPARATE migration only to isolate the one cross-reference into the spine
--   table claim_chunks (which carries a PK on claim_chunk_id). ADDITIVE (a constraint).
--   Down in 005_enrichment_records_fragment_fk.down.sql.

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.enrichment_records
    ADD CONSTRAINT enrichment_records_source_chunk_fk
    FOREIGN KEY (source_chunk_id)
    REFERENCES context_reliquary.claim_chunks (claim_chunk_id);
