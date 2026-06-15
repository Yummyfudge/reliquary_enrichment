# Scratch Postgres for integration tests (never prod)

The DB-backed integration tests (`test_postgres_integration.py`) and DDL validation run
against an **ephemeral local Postgres** — never the live corpus (Decision D3). It refuses to
run unless the target is a local, password-auth DB.

## Spin it up (pgvector, faithful to the real claim_chunks)
```bash
docker run -d --name relenrich-pg \
  -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=scratch \
  -p 55432:5432 pgvector/pgvector:pg16

docker exec -i relenrich-pg psql -U postgres -d scratch <<'SQL'
CREATE SCHEMA IF NOT EXISTS context_reliquary;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE context_reliquary.claim_chunks (        -- mirrors prod columns (no claim content)
    claim_chunk_id uuid PRIMARY KEY, claim_id text NOT NULL DEFAULT 'claim-x',
    document_name text NOT NULL, chunk_type text NOT NULL,
    char_start_offset integer, char_end_offset integer, page_number integer,
    segment_index integer, created_at_utc timestamptz DEFAULT now(),
    payload jsonb NOT NULL, embedding vector(1024), embedding_qwen3 vector(4096));
CREATE ROLE context_reliquary_app LOGIN PASSWORD 'app';
SQL
```

## Apply the schema
```bash
for f in 001_enrichment_records 002_codex_entities 003_enrichment_links \
         004_enrichment_meaning 005_enrichment_records_fragment_fk; do
  docker exec -i relenrich-pg psql -U postgres -d scratch -v ON_ERROR_STOP=1 < schema/$f.up.sql
done
docker exec -i relenrich-pg psql -U postgres -d scratch < schema/grants.runtime.sql
```

## Run the integration tests
```bash
RELIQUARY_ENRICHMENT_PGHOST=127.0.0.1 RELIQUARY_ENRICHMENT_PGPORT=55432 \
RELIQUARY_ENRICHMENT_PGDATABASE=scratch RELIQUARY_ENRICHMENT_PGUSER=postgres \
RELIQUARY_ENRICHMENT_PGPASSWORD=scratch RELIQUARY_ENRICHMENT_PGSSLMODE=disable \
pytest -m integration
```
The judge integration tests additionally need the live LiteLLM `judge` alias reachable.

## Tear down
```bash
docker rm -f relenrich-pg
```
