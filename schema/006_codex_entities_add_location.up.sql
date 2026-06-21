-- Migration 006 (up) — add 'location' to the codex_entities entity_type enum.
--
-- What: extends codex_entities_type_chk to admit entity_type 'location' alongside
--   actor/date/event/document/provision/code — the 7th closed-vocab type the codex refactor
--   (meaning<->codex architecture) requires (vocabulary.ENTITY_TYPES). 002 shipped with 6.
-- Why: typed entity extraction over the FIXED closed vocabulary needs 'location' as a
--   first-class node type (a place that bears on the claim); without it write_enrichment's
--   resolve_or_create for a location entity would violate the CHECK.
--
-- ADDITIVE ONLY (D3) — does NOT rewrite 002 (already applied to prod). Drops and re-adds the
--   SAME named constraint (codex_entities_type_chk) with the wider enum. Applied by Joe.
--   Down in 006_codex_entities_add_location.down.sql. Requires 002.

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.codex_entities
    DROP CONSTRAINT IF EXISTS codex_entities_type_chk;

ALTER TABLE context_reliquary.codex_entities
    ADD CONSTRAINT codex_entities_type_chk
        CHECK (entity_type IN ('actor', 'date', 'event', 'document', 'provision', 'code', 'location'));
