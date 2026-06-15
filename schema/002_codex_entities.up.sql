-- Migration 002 (up) — codex_entities: the Codex's shared nouns.
--
-- What: normalized Entities (actor / date / event, extensible to document / provision /
--   code) that Enrichment Records point at, shared ACROSS record schemas. The
--   cross-boundary sharing layer. See contracts/codex.md §3.
-- Why: the gold note's meaning is relational — the SAME date/actor/event in two records
--   must resolve to ONE Entity for the Codex to link across pages. Entities are
--   code-MATERIALIZED, never model-typed: actor/date at write_enrichment time (step 9),
--   event from grounded `same_event` Links (codex §6).
--
-- ADDITIVE ONLY (D3). Down-migration (DROP) in 002_codex_entities.down.sql, applied by Joe.
-- Requires 001 (references enrichment_records).

SET search_path TO context_reliquary;

CREATE TABLE IF NOT EXISTS context_reliquary.codex_entities (
    entity_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type        text        NOT NULL
        CONSTRAINT codex_entities_type_chk
            CHECK (entity_type IN ('actor', 'date', 'event', 'document', 'provision', 'code')),
    canonical          text        NOT NULL,                  -- normalized value/name (the dedupe key)
    aliases            jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- observed surface forms ("manager B. Smith")
    metadata           jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- e.g. parsed ISO date, role, merge history
    -- first_seen_record is informational provenance, deliberately NOT an FK: an Entity is
    -- materialized in the same flow as the record that first cites it, and entity_refs
    -- must be present on the (write-once) record AT insert — an FK here would force
    -- entity-after-record ordering and add no real integrity (code always sets this to the
    -- record being written). Kept as a plain column. (See findings; flagged to Architect.)
    first_seen_record  uuid,
    flagged            boolean     NOT NULL DEFAULT false,    -- uncertain dedupe/merge -> curation, never silent-merge
    created            timestamptz NOT NULL DEFAULT now(),

    -- Resolve-or-create key: one Entity per (type, canonical). Dedupe is exact here
    -- (codex §9-B: start minimal); fuzzy canonicalization is a later task that writes
    -- aliases / merges under curation.
    CONSTRAINT codex_entities_type_canonical_uq UNIQUE (entity_type, canonical)
);

-- Alias lookup (resolve a surface form to an existing Entity before creating a new one).
CREATE INDEX IF NOT EXISTS idx_codex_entities_aliases
    ON context_reliquary.codex_entities USING gin (aliases);
CREATE INDEX IF NOT EXISTS idx_codex_entities_flagged
    ON context_reliquary.codex_entities (created) WHERE flagged;
