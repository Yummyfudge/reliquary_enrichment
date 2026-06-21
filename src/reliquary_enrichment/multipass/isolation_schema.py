from __future__ import annotations

"""Throwaway isolation schema — create fresh per run, drop after export (the §5 isolation core).

Rehomed into `multipass/` from the retired `probe/` (codex refactor §13 — no cross-context deps; the
multipass harness owns its isolation). A `probe_<label>` schema holds the run's enrichment_records /
codex_entities / enrichment_links / enrichment_meaning — NEVER prod. Same table shape + CHECK
constraints as prod (fidelity), but WITHOUT the claim_chunks FK (cross-schema/REFERENCES friction; the
corpus is read-only and the grounding core already guards) and WITHOUT the write-once trigger (a
throwaway schema is dropped wholesale; the grounding invariant lives in write_enrichment, unchanged).
claim_chunks is read from context_reliquary, never copied here.

Carries the §6 DDL deltas: NO `claim_relevance` column (relocated out of enrichment_records); a GIN
index on `entity_refs` (the entity->record reverse lookup); and an `enrichment_meaning` table WITHOUT
the `vector` extension (structural runs only — the deferred needle step targets a schema where the
extension exists, keeping the probe role free of CREATE EXTENSION).
"""

import re

from reliquary_enrichment.postgres.connection import connect, qualified

_LABEL = re.compile(r"^[a-z0-9_]{1,40}$")


def probe_schema_name(label: str) -> str:
    """Return the validated probe schema name for a label (e.g. 'qwen3_14b' -> 'probe_qwen3_14b')."""
    if not _LABEL.match(label):
        raise ValueError(f"invalid probe label {label!r} (expected ^[a-z0-9_]{{1,40}}$)")
    return f"probe_{label}"


def _tables_ddl(schema: str) -> str:
    """Schema-parametrized DDL for the four enrichment tables (FK/trigger-free)."""
    records = qualified(schema, "enrichment_records")
    entities = qualified(schema, "codex_entities")
    links = qualified(schema, "enrichment_links")
    meaning = qualified(schema, "enrichment_meaning")
    return f"""
        CREATE TABLE IF NOT EXISTS {records} (
            record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            record_type text NOT NULL,
            tier text NOT NULL CHECK (tier IN ('fact','interpretation')),
            fields jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            actor text, event_date text,
            confidence double precision CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
            source_chunk_id uuid NOT NULL,
            char_start integer NOT NULL CHECK (char_start >= 0),
            char_end integer NOT NULL,
            page integer, document text,
            evidence_span text NOT NULL,
            CHECK (char_end > char_start),
            CHECK (evidence_span ~ '[^[:space:]]'),
            provenance_validation jsonb NOT NULL,
            entity_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
            flagged boolean NOT NULL DEFAULT false,
            created timestamptz NOT NULL DEFAULT now(),
            supersedes uuid
        );
        CREATE INDEX IF NOT EXISTS idx_{schema}_rec_chunk ON {records} (source_chunk_id);
        CREATE INDEX IF NOT EXISTS idx_{schema}_rec_entity_refs ON {records} USING gin (entity_refs);

        CREATE TABLE IF NOT EXISTS {entities} (
            entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type text NOT NULL
                CHECK (entity_type IN ('actor','date','event','document','provision','code','location')),
            canonical text NOT NULL,
            aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            first_seen_record uuid,
            flagged boolean NOT NULL DEFAULT false,
            created timestamptz NOT NULL DEFAULT now(),
            UNIQUE (entity_type, canonical)
        );

        CREATE TABLE IF NOT EXISTS {links} (
            link_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            record_a uuid NOT NULL REFERENCES {records} (record_id),
            record_b uuid NOT NULL REFERENCES {records} (record_id),
            relation text NOT NULL,
            tier text NOT NULL CHECK (tier IN ('fact','interpretation')),
            evidence jsonb NOT NULL,
            confidence double precision CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
            provenance_validation jsonb NOT NULL,
            event_entity uuid REFERENCES {entities} (entity_id),
            flagged boolean NOT NULL DEFAULT false,
            created timestamptz NOT NULL DEFAULT now(),
            CHECK (record_a <> record_b)
        );

        CREATE TABLE IF NOT EXISTS {meaning} (
            meaning_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_chunk_id uuid NOT NULL,
            claim_meaning text NOT NULL,
            created timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_{schema}_meaning_chunk ON {meaning} (source_chunk_id);
    """


def create_probe_schema(label: str) -> str:
    """Create a fresh probe_<label> schema with the enrichment tables. Returns the schema name."""
    schema = probe_schema_name(label)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        # No `vector` extension: the probe enrichment_meaning table omits the embedding column
        # (structural runs only) — keeps the probe role free of CREATE EXTENSION privilege.
        cur.execute(_tables_ddl(schema))
    return schema


def drop_probe_schema(label: str) -> None:
    """Drop the probe_<label> schema and everything in it (teardown after export)."""
    schema = probe_schema_name(label)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
