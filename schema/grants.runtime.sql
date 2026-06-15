-- Runtime grants — HAND TO JOE, DO NOT APPLY (Decision D3: GRANT is reserved to Joe).
--
-- Why this is needed: the four enrichment tables are CREATEd by the scoped
-- `enrichment_ddl` role, so it OWNS them. The live MCP tools, however, run as the
-- runtime app role (the same role VectorSearchTool uses to read claim_chunks —
-- `context_reliquary_app`), which has NO access to enrichment_ddl-owned tables until
-- granted. Without these grants, write_enrichment / link_events / get_chunk cannot
-- read or write. Apply AFTER migrations 001-004.
--
-- Principle of least privilege, and consistent with write-once:
--   * SELECT + INSERT on all four tables (the tools read-back and append).
--   * NO UPDATE / DELETE on records/links (write-once is also enforced by trigger;
--     this makes it true at the grant layer too).
--   * UPDATE is granted ONLY on codex_entities (aliases/metadata/flagged evolve as the
--     same entity is re-observed and merged under curation) — entities are mutable;
--     records and links are not.
--   * USAGE on the sequence-less uuid defaults needs nothing extra (gen_random_uuid()).

\set app_role context_reliquary_app

GRANT SELECT, INSERT ON context_reliquary.enrichment_records  TO :app_role;
GRANT SELECT, INSERT ON context_reliquary.enrichment_links    TO :app_role;
GRANT SELECT, INSERT ON context_reliquary.enrichment_meaning  TO :app_role;
GRANT SELECT, INSERT, UPDATE ON context_reliquary.codex_entities TO :app_role;

-- Note: claim_chunks SELECT is ALREADY held by the runtime app role (VectorSearchTool
-- reads it today) — no new grant needed there.
