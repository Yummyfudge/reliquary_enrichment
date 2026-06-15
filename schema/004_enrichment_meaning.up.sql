-- Migration 004 (up) — enrichment_meaning: per-Fragment claim-meaning for embedding.
--
-- What: per-chunk `claim_meaning` + `questions_answered` — the interpreted text that
--   later gets EMBEDDED (Qwen3) and fused with claim_chunks vectors at query time.
--   See SCOPE.md §8.
-- Why: this is what makes retrieval hit on meaning, not words. The gold note lifts when
--   its claim_meaning ("supervisor reversed the prior approval ...") embeds near the
--   user's question.
--
-- EMBEDDING: `embedding vector(4096)` — the SAME space as claim_chunks.embedding_qwen3
--   (Architect ref, 2026-06-14). Requires the `vector` extension (already enabled — the
--   corpus uses it). Embedding POPULATION stays a separate track (brief §7); the column
--   is created now so the writer can fill it when that track lands.
--
-- ⚠️ INDEX DEFERRED — NOT a bug: pgvector's HNSW/IVFFlat ANN indexes cap at 2000 dims
--   for `vector` (4000 for `halfvec`); 4096 exceeds both. claim_chunks.embedding_qwen3 is
--   the same 4096-dim space, so the meaning index must mirror whatever ANN strategy the
--   corpus uses there (halfvec cast, brute-force scan, or none). Resolve WITH the embedding
--   track — see findings. A premature CREATE INDEX hnsw here would simply error.
--
-- ADDITIVE ONLY (D3). Down-migration in 004_enrichment_meaning.down.sql, applied by Architect.

CREATE EXTENSION IF NOT EXISTS vector;

-- Include public so the `vector` type (extension installed in public) resolves; the
-- enrichment table itself is created in context_reliquary (first on the path).
SET search_path TO context_reliquary, public;

CREATE TABLE IF NOT EXISTS context_reliquary.enrichment_meaning (
    meaning_id          uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    source_chunk_id     uuid          NOT NULL,                  -- the Fragment this meaning summarizes
    claim_meaning       text          NOT NULL,                  -- interpreted significance (what we embed)
    questions_answered  jsonb         NOT NULL DEFAULT '[]'::jsonb,  -- the questions this Fragment answers
    embedding           vector(4096),                            -- Qwen3 space (== claim_chunks.embedding_qwen3); populated later
    created             timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_enrichment_meaning_source_chunk
    ON context_reliquary.enrichment_meaning (source_chunk_id);
-- No ANN index on `embedding` yet — see the 4096-dim note above.
