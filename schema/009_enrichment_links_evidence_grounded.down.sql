-- 009 DOWN — drop the evidence-grounded CHECK on enrichment_links.

ALTER TABLE enrichment_links
    DROP CONSTRAINT IF EXISTS enrichment_links_evidence_grounded_chk;
