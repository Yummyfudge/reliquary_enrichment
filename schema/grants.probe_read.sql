-- Probe isolation-proof read grant — HAND TO JOE, DO NOT the engineer apply (GRANT -> Joe).
--
-- Lets the `probe` role READ (count) the prod enrichment tables so each run can record its
-- own before/after isolation proof in isolation.json (Architect handoff §3.3 / F5). This is
-- SELECT-only: the WRITE wall is untouched — the probe role still has NO INSERT/UPDATE/DELETE
-- on prod enrichment, which is the actual isolation guarantee.
--
-- OPTIONAL: if you'd rather keep the probe role fully read-denied on prod enrichment, skip
-- this — the harness then records `_access: permission_denied` in isolation.json, which is a
-- STRONGER proof (the role can't even read prod enrichment). With this grant it instead
-- records concrete before==after counts. Your call; the harness handles both.

GRANT SELECT ON context_reliquary.enrichment_records TO probe;
GRANT SELECT ON context_reliquary.codex_entities     TO probe;
GRANT SELECT ON context_reliquary.enrichment_links   TO probe;

-- Verify (as the probe role): counts readable, writes still denied.
--   SET ROLE probe;
--   SELECT count(*) FROM context_reliquary.enrichment_records;          -- now works (read)
--   INSERT INTO context_reliquary.enrichment_records DEFAULT VALUES;    -- still permission denied
--   RESET ROLE;
