-- 009 UP — enrichment_links.evidence must carry the CODE-SLICED span pair (grounding, DB-side).
--
-- ADDITIVE ONLY (Decision D3): adds a CHECK constraint; no data rewrite. Mirrors the records table's
-- enrichment_records_span_nonblank_chk (001:40) on the LINK side, which today only has `evidence jsonb
-- NOT NULL` (003:29) with no content check. The codex walker (codex_walk.py) treats a link as walkable
-- iff its evidence carries a_span + b_span (the spans link_events.py:175 always writes); this constraint
-- makes that the DB's guarantee too, so "only cited edges are walkable" no longer leans on writer
-- discipline alone (step-9 review HIGH). Every grounded link the sanctioned writer emits already satisfies
-- it (a_span/b_span are required by link_events._validate), so no legitimate row is rejected.
--
-- ARCHITECT APPLIES. If any pre-existing enrichment_links row predates this (e.g. an early dev/probe row
-- without a_span/b_span), add the constraint NOT VALID first, remediate, then VALIDATE CONSTRAINT — so the
-- ALTER does not fail on legacy rows.

ALTER TABLE enrichment_links
    ADD CONSTRAINT enrichment_links_evidence_grounded_chk
        CHECK (evidence ? 'a_span' AND evidence ? 'b_span');
