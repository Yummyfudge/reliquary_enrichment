-- Migration 003 (up) — enrichment_links: the Codex's cross-record edges.
--
-- What: one row per grounded Link between two Enrichment Records, written by
--   link_events. Temporal / causal / evidential / structural relations. See
--   contracts/codex.md §4-§5.
-- Why: the gold note becomes findable only when its reversal record LINKS to the
--   approval it undid, the supervisor who drove it, the date it happened — relations
--   vector search can't bridge. Links pass the SAME point->copy->check->attest boundary
--   as records (the shared grounding core); WRITE-ONCE; both cited spans are hashed.
--
-- ADDITIVE ONLY (D3). Down-migration in 003_enrichment_links.down.sql, applied by Joe.
-- Requires 001 (records) and 002 (entities — event_entity ref).

SET search_path TO context_reliquary;

CREATE TABLE IF NOT EXISTS context_reliquary.enrichment_links (
    link_id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    record_a               uuid        NOT NULL
        CONSTRAINT enrichment_links_record_a_fk
            REFERENCES context_reliquary.enrichment_records (record_id),
    record_b               uuid        NOT NULL
        CONSTRAINT enrichment_links_record_b_fk
            REFERENCES context_reliquary.enrichment_records (record_id),
    relation               text        NOT NULL,                 -- curated vocab (seed: precedes/follows/causes/
                                                                 -- results_from/corroborates/contradicts/elaborates/
                                                                 -- same_event/references)
    tier                   text        NOT NULL
        CONSTRAINT enrichment_links_tier_chk CHECK (tier IN ('fact', 'interpretation')),
    evidence               jsonb       NOT NULL,                 -- cited spans/refs {a_span:[s,e], b_span:[s,e], ...}
    confidence             double precision
        CONSTRAINT enrichment_links_confidence_chk
            CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),

    -- Provenance Validation — verdict + judge id + SHA-256 of BOTH evidence spans + time.
    provenance_validation  jsonb       NOT NULL,

    -- Set only when relation = same_event: the Event Entity these records were merged into.
    event_entity           uuid
        CONSTRAINT enrichment_links_event_entity_fk
            REFERENCES context_reliquary.codex_entities (entity_id),

    flagged                boolean     NOT NULL DEFAULT false,   -- partial grounding -> flag, don't bounce
    created                timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT enrichment_links_no_self_chk CHECK (record_a <> record_b)
);

CREATE INDEX IF NOT EXISTS idx_enrichment_links_record_a
    ON context_reliquary.enrichment_links (record_a);
CREATE INDEX IF NOT EXISTS idx_enrichment_links_record_b
    ON context_reliquary.enrichment_links (record_b);
CREATE INDEX IF NOT EXISTS idx_enrichment_links_relation
    ON context_reliquary.enrichment_links (relation);
CREATE INDEX IF NOT EXISTS idx_enrichment_links_event_entity
    ON context_reliquary.enrichment_links (event_entity) WHERE event_entity IS NOT NULL;

-- Same write-once guard as records (defined in 001).
DROP TRIGGER IF EXISTS trg_enrichment_links_immutable
    ON context_reliquary.enrichment_links;
CREATE TRIGGER trg_enrichment_links_immutable
    BEFORE UPDATE OR DELETE ON context_reliquary.enrichment_links
    FOR EACH ROW EXECUTE FUNCTION context_reliquary.reliquary_enrichment_forbid_mutation();
