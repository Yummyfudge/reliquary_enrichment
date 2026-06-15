-- Migration 002 (down) — rollback codex_entities.
--
-- DESTRUCTIVE. Engineer writes, Joe applies (D3). Run AFTER 003 down if links exist
-- (enrichment_links.event_entity references this table).

SET search_path TO context_reliquary;

DROP TABLE IF EXISTS context_reliquary.codex_entities;
