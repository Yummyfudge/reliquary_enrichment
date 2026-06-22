-- Migration 007 (up) — enrichment_meaning becomes a LOCAL FACT, one per chunk.
--
-- What: (a) UNIQUE(source_chunk_id) — exactly one meaning row per chunk (the MeaningWriter
--   writes one local standalone dated fact per chunk); (b) FK source_chunk_id -> claim_chunks
--   (mirror of 005 — the 89503 belt-and-suspenders, now for the meaning table); (c) DROP
--   COLUMN questions_answered — the refactor retires whole-claim Q/A. Meaning is the small
--   local dated fact and the ONLY embedded artifact (the embedding column stays).
-- Why: 004 modeled meaning as whole-claim "interpreted significance" + questions_answered.
--   The refactor (notes/engineer-brief-codex-refactor.md §3.1/§5.2) makes meaning a
--   discriminative LOCAL fact; questions_answered is unread after the pass5/review change.
--
-- ADDITIVE constraints + one column DROP. Does NOT rewrite 004 (already applied to prod). The
--   DROP COLUMN is acceptable per brief §5.2 (nothing reads questions_answered after the
--   pass5/review edits — land those code edits BEFORE applying this). Applied by Joe.
--   Down in 007_enrichment_meaning_local_fact.down.sql. Requires 004.
--   PRECONDITION: no duplicate source_chunk_id rows (the UNIQUE add fails otherwise); every
--   source_chunk_id references a real claim_chunks row (the FK add fails otherwise).

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.enrichment_meaning
    ADD CONSTRAINT enrichment_meaning_source_chunk_uq UNIQUE (source_chunk_id);

ALTER TABLE context_reliquary.enrichment_meaning
    ADD CONSTRAINT enrichment_meaning_source_chunk_fk
    FOREIGN KEY (source_chunk_id)
    REFERENCES context_reliquary.claim_chunks (claim_chunk_id);

ALTER TABLE context_reliquary.enrichment_meaning
    DROP COLUMN IF EXISTS questions_answered;
