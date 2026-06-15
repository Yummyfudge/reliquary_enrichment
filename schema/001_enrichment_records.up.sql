-- Migration 001 (up) — enrichment_records: the grounded-fact write target.
--
-- What: one row per grounded Enrichment Record written by write_enrichment — the
--   only path by which extracted meaning reaches storage. Lives BESIDE claim_chunks
--   in the context_reliquary schema (brief §3.1).
-- Why: makes invariant-llm-not-a-data-bus mechanical — provenance + the immutable,
--   hashed Provenance Validation attestation ride every row; records are WRITE-ONCE
--   (corrections supersede, never edit in place). See contracts/write_enrichment.md §7.
--
-- ADDITIVE ONLY (Decision D3): CREATE TABLE / INDEX / FUNCTION / TRIGGER. The matching
-- down-migration (DROP) lives in 001_enrichment_records.down.sql and is applied by Joe.
-- Apply order: 001 (records) -> 002 (entities) -> 003 (links) -> 004 (meaning).

SET search_path TO context_reliquary;

CREATE TABLE IF NOT EXISTS context_reliquary.enrichment_records (
    record_id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- WHAT was found (the model's judge-checked reasoning).
    record_type            text        NOT NULL,                 -- controlled vocab, emergent (Pass 1)
    tier                   text        NOT NULL
        CONSTRAINT enrichment_records_tier_chk CHECK (tier IN ('fact', 'interpretation')),
    fields                 jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- structured meaning, shape per record_type
    actor                  text,                                 -- judge-verified vs span; resolved to a Codex Entity
    event_date             text,                                 -- normalized string (tolerates partials); date Entity canonicalizes
    claim_relevance        text,                                 -- why it matters to the denial (usually interpretation)
    confidence             double precision
        CONSTRAINT enrichment_records_confidence_chk
            CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),

    -- Provenance — ALL code-derived from the Fragment, never from the payload.
    source_chunk_id        uuid        NOT NULL,                 -- -> claim_chunks.claim_chunk_id (app-enforced; opt. FK in 005)
    char_start             integer     NOT NULL
        CONSTRAINT enrichment_records_char_start_chk CHECK (char_start >= 0),
    char_end               integer     NOT NULL,
    page                   integer,                              -- from claim_chunks.page_number
    document               text,                                 -- from claim_chunks.document_name
    evidence_span          text        NOT NULL,                 -- code-sliced substring of the Fragment's chunk_text
    CONSTRAINT enrichment_records_span_order_chk CHECK (char_end > char_start),
    CONSTRAINT enrichment_records_span_nonblank_chk CHECK (evidence_span ~ '[^[:space:]]'),

    -- Provenance Validation — the immutable attestation this record passed grounding.
    -- { verdict, judge_model, judge_version, evidence_sha256, source_sha256, validated_at }.
    provenance_validation  jsonb       NOT NULL,

    -- Codex Entity references this record points at (resolved at write time, step 9).
    entity_refs            jsonb       NOT NULL DEFAULT '[]'::jsonb,

    flagged                boolean     NOT NULL DEFAULT false,   -- partial grounding -> flag, don't bounce
    created                timestamptz NOT NULL DEFAULT now(),

    -- Corrections supersede (write-once): the NEW row points at the record it replaces.
    supersedes             uuid
        CONSTRAINT enrichment_records_supersedes_fk
            REFERENCES context_reliquary.enrichment_records (record_id)
);

-- Lookups: by Fragment, by type, by entity (jsonb containment), and the curation queue.
CREATE INDEX IF NOT EXISTS idx_enrichment_records_source_chunk
    ON context_reliquary.enrichment_records (source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_records_record_type
    ON context_reliquary.enrichment_records (record_type);
CREATE INDEX IF NOT EXISTS idx_enrichment_records_entity_refs
    ON context_reliquary.enrichment_records USING gin (entity_refs);
CREATE INDEX IF NOT EXISTS idx_enrichment_records_flagged
    ON context_reliquary.enrichment_records (created) WHERE flagged;

-- Write-once enforcement at the storage layer (the record "attests" and is tamper-evident):
-- forbid UPDATE/DELETE on grounded rows. Corrections are new INSERTs via `supersedes`.
CREATE OR REPLACE FUNCTION context_reliquary.reliquary_enrichment_forbid_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'reliquary_enrichment: % on % is forbidden — records/links are write-once; supersede with a new row',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_enrichment_records_immutable
    ON context_reliquary.enrichment_records;
CREATE TRIGGER trg_enrichment_records_immutable
    BEFORE UPDATE OR DELETE ON context_reliquary.enrichment_records
    FOR EACH ROW EXECUTE FUNCTION context_reliquary.reliquary_enrichment_forbid_mutation();
