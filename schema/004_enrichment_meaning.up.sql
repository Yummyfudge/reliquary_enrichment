-- Migration 004 (up) — enrichment_meaning: per-Fragment claim-meaning for embedding.
--
-- What: per-chunk `claim_meaning` + `questions_answered` — the interpreted text that
--   later gets EMBEDDED (Qwen3) and fused with claim_chunks vectors at query time.
--   See SCOPE.md §8.
-- Why: this is what makes retrieval hit on meaning, not words. The gold note lifts when
--   its claim_meaning ("supervisor reversed the prior approval ...") embeds near the
--   user's question.
--
-- SCOPE NOTE — the embedding column is intentionally DEFERRED. The Qwen3 cutover is not
--   yet deployed to the RAG MCP (still BGE-1024 there) and the target vector dimension
--   is unsettled (brief §4, §7: "do not block on embedding"). Baking in a wrong
--   dimension would be costly to undo. The `embedding` column + its HNSW index land in a
--   SEPARATE migration once the dimension is pinned — see 004b_enrichment_meaning_embedding.up.sql.
--
-- ADDITIVE ONLY (D3). Down-migration in 004_enrichment_meaning.down.sql, applied by Joe.

SET search_path TO context_reliquary;

CREATE TABLE IF NOT EXISTS context_reliquary.enrichment_meaning (
    meaning_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_chunk_id     uuid        NOT NULL,                  -- the Fragment this meaning summarizes
    claim_meaning       text        NOT NULL,                  -- interpreted significance (what we embed)
    questions_answered  jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- the questions this Fragment answers
    -- embedding        vector(N)   -- DEFERRED: added in 004b once the Qwen3 dimension is pinned.
    created             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_enrichment_meaning_source_chunk
    ON context_reliquary.enrichment_meaning (source_chunk_id);
