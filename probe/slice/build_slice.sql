-- build_slice.sql — derive the LOCKED probe slice (read-only; run by the Architect, P3).
--
-- The engineer writes this; the Architect runs it ONCE as the read-only `probe` role and
-- commits the resulting content-free chunk_id list to chunk_ids.txt. It only SELECTs the
-- corpus — it never writes. The crown-jewel CONTENT (chunk_text) stays out of the engineer's
-- path; only UUIDs are frozen.
--
-- Run (Architect):
--   PGOPTIONS=... psql "host=192.168.1.53 dbname=context_reliquary user=probe sslmode=verify-full" \
--     -X -A -t -f probe/slice/build_slice.sql -o probe/slice/chunk_ids.txt
--   # then sanity-check the count (target ~60-100) and `git add` the frozen fixture.
--
-- Tuning: the slice should land ~60-100 cross-linked chunks. If too small, add terms
-- (RN/claim numbers, more dates) to `web_terms`; if too large, tighten. Keep it the reversal's
-- web — every term ties to the B. Smith reversal story so the slice is cross-linked by design.

WITH seed_pages(page_number) AS (
    VALUES (742), (672)          -- CRQ-001 gold-note pages (+ extend with the eval's page-sets)
),
web_terms(term) AS (
    VALUES
        ('%B. Smith%'),
        ('%JoAnn F%'),
        ('%long COVID%'),
        ('%Mental Health limitation%'),
        ('%2025-02-18%')         -- the reversal date; add other Feb-2025 dates / RN / claim #s as needed
),
slice AS (
    -- the gold note itself (by id — the one chunk we anchor on)
    SELECT claim_chunk_id
    FROM context_reliquary.claim_chunks
    WHERE claim_chunk_id = '89503c71-5ca2-424b-9386-6698a8337dc3'

    UNION
    -- seed pages
    SELECT c.claim_chunk_id
    FROM context_reliquary.claim_chunks c
    JOIN seed_pages s USING (page_number)

    UNION
    -- the reversal's web: any chunk whose text mentions a web term
    SELECT c.claim_chunk_id
    FROM context_reliquary.claim_chunks c
    WHERE EXISTS (
        SELECT 1 FROM web_terms w
        WHERE c.payload->>'chunk_text' ILIKE w.term
    )
)
SELECT claim_chunk_id
FROM slice
ORDER BY claim_chunk_id;   -- deterministic order so the frozen fixture is stable
