-- Migration 006 (down) — restore the 6-value codex_entities entity_type enum (drop 'location').
--
-- DESTRUCTIVE. Engineer writes, Joe applies (D3). Re-adding the narrower CHECK FAILS if any
--   row already has entity_type='location' — delete or repoint those rows first.

SET search_path TO context_reliquary;

ALTER TABLE context_reliquary.codex_entities
    DROP CONSTRAINT IF EXISTS codex_entities_type_chk;

ALTER TABLE context_reliquary.codex_entities
    ADD CONSTRAINT codex_entities_type_chk
        CHECK (entity_type IN ('actor', 'date', 'event', 'document', 'provision', 'code'));
