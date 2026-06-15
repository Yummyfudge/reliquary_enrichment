-- Migration 005 (up, OPTIONAL hardening) — FK enrichment_records.source_chunk_id -> claim_chunks.
--
-- What: a foreign key making it structurally impossible to write an Enrichment Record
--   whose source_chunk_id is not a real Fragment.
-- Why: defense-in-depth for the 89503 invariant. The grounding core ALREADY rejects a
--   missing Fragment at the application layer (resolve+load, write_enrichment §5 steps
--   1-2), so this FK is belt-and-suspenders, not the primary guard.
--
-- SEPARATE / OPTIONAL because it crosses into the spine table claim_chunks and needs the
--   REFERENCES privilege on claim_chunks (distinct from content SELECT). The enrichment_ddl
--   role may not hold it — if this migration errors on privilege, SKIP it; the app-layer
--   guard stands. Requires claim_chunks.claim_chunk_id to carry a PK/UNIQUE constraint.
--
-- ADDITIVE (a constraint). Down in 005_enrichment_records_fragment_fk.down.sql (Joe).

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.enrichment_records
    ADD CONSTRAINT enrichment_records_source_chunk_fk
    FOREIGN KEY (source_chunk_id)
    REFERENCES context_reliquary.claim_chunks (claim_chunk_id);
