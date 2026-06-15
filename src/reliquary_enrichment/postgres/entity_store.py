from __future__ import annotations

"""PostgresEntityStore — resolve-or-create Codex Entities; event-cluster maintenance.

Dedupe key is UNIQUE(entity_type, canonical). Entities are mutable (aliases grow, event
members merge) — the runtime app role holds UPDATE on codex_entities (but not on records/
links). Event membership lives in metadata.member_records; a merged event carries
metadata.merged_into and is flagged for curation.
"""

import json

from reliquary_enrichment.models import Entity
from reliquary_enrichment.postgres.connection import connect


def _row_to_entity(row: dict) -> Entity:
    return Entity(
        entity_type=row["entity_type"], canonical=row["canonical"],
        aliases=list(row["aliases"] or []), metadata=dict(row["metadata"] or {}),
        first_seen_record=str(row["first_seen_record"]) if row["first_seen_record"] else None,
        flagged=row["flagged"], entity_id=str(row["entity_id"]),
    )


class PostgresEntityStore:
    def find(self, entity_type: str, canonical: str) -> Entity | None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT entity_id, entity_type, canonical, aliases, metadata, "
                "first_seen_record, flagged FROM context_reliquary.codex_entities "
                "WHERE entity_type = %(t)s AND canonical = %(c)s",
                {"t": entity_type, "c": canonical},
            )
            row = cur.fetchone()
        return _row_to_entity(row) if row else None

    def insert(self, entity: Entity) -> str:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO context_reliquary.codex_entities "
                "(entity_id, entity_type, canonical, aliases, metadata, first_seen_record, flagged) "
                "VALUES (%(id)s, %(t)s, %(c)s, %(a)s, %(m)s, %(f)s, %(flag)s)",
                {
                    "id": entity.entity_id, "t": entity.entity_type, "c": entity.canonical,
                    "a": json.dumps(entity.aliases), "m": json.dumps(entity.metadata),
                    "f": entity.first_seen_record, "flag": entity.flagged,
                },
            )
        return entity.entity_id

    def add_alias(self, entity_id: str, alias: str) -> None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE context_reliquary.codex_entities "
                "SET aliases = aliases || %(a)s::jsonb WHERE entity_id = %(id)s",
                {"a": json.dumps([alias]), "id": entity_id},
            )

    def event_for_record(self, record_id: str) -> Entity | None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT entity_id, entity_type, canonical, aliases, metadata, "
                "first_seen_record, flagged FROM context_reliquary.codex_entities "
                "WHERE entity_type = 'event' "
                "  AND NOT (metadata ? 'merged_into') "
                "  AND metadata->'member_records' @> %(rid)s::jsonb LIMIT 1",
                {"rid": json.dumps([record_id])},
            )
            row = cur.fetchone()
        return _row_to_entity(row) if row else None

    def set_event_members(self, entity_id: str, member_records: list[str]) -> None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE context_reliquary.codex_entities "
                "SET metadata = jsonb_set(metadata, '{member_records}', %(m)s::jsonb) "
                "WHERE entity_id = %(id)s",
                {"m": json.dumps(member_records), "id": entity_id},
            )

    def mark_event_merged(self, absorbed_id: str, survivor_id: str) -> None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE context_reliquary.codex_entities "
                "SET metadata = jsonb_set("
                "      jsonb_set(metadata, '{member_records}', '[]'::jsonb), "
                "      '{merged_into}', %(s)s::jsonb), "
                "    flagged = true "
                "WHERE entity_id = %(id)s",
                {"s": json.dumps(survivor_id), "id": absorbed_id},
            )
