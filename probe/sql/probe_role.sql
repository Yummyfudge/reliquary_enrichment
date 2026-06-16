-- Probe role — HAND TO JOE, DO NOT the engineer apply (standing DB split: role/GRANT -> Joe).
--
-- The scoped role the extraction probe runs as. Its ceiling IS the isolation guarantee:
--   * READ-ONLY on the corpus: SELECT on context_reliquary.claim_chunks (+ USAGE on schema).
--   * CREATE on the database: so it can make/drop its OWN throwaway probe_<label> schemas
--     (created fresh per run, dropped after scoring) and has full rights inside them as owner.
--   * NO grant on context_reliquary.enrichment_records / codex_entities / enrichment_links —
--     so the harness STRUCTURALLY cannot write prod enrichment (not just "by policy").
--
-- This is why "no prod-write credential in the harness" holds: the only credential the harness
-- ever holds is this role, and this role physically cannot touch prod enrichment tables.
--
-- Auth: Joe sets the login method (cert or password) per the key/cert standard. The probe
-- connects with RELIQUARY_ENRICHMENT_PG* env (user=probe) — never the app role, never joe_dba.

-- 1) the role (Joe picks the auth; LOGIN required).
CREATE ROLE probe LOGIN;   -- + PASSWORD '...' or a client cert mapping, per Joe's standard

-- 2) read-only on the corpus.
GRANT USAGE  ON SCHEMA context_reliquary           TO probe;
GRANT SELECT ON context_reliquary.claim_chunks     TO probe;

-- 3) let it own throwaway probe_<label> schemas (make + drop its own).
GRANT CREATE ON DATABASE context_reliquary         TO probe;

-- 4) DELIBERATELY NOT GRANTED (the wall): any privilege on the prod enrichment tables.
--    Do NOT add SELECT/INSERT/UPDATE on context_reliquary.{enrichment_records,
--    codex_entities,enrichment_links} — the harness must never be able to write them.
--
-- Verify after applying:
--   SET ROLE probe;
--   SELECT count(*) FROM context_reliquary.claim_chunks;             -- works (read corpus)
--   CREATE SCHEMA probe_smoketest;  DROP SCHEMA probe_smoketest;     -- works (own schemas)
--   INSERT INTO context_reliquary.enrichment_records DEFAULT VALUES; -- MUST be permission denied
--   RESET ROLE;
