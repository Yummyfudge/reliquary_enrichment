from __future__ import annotations

"""PostgresEntityStore — resolve-or-create Codex Entities; event-cluster maintenance.

Dedupe key is UNIQUE(entity_type, canonical). Entities are mutable (aliases grow, event
members merge). The write schema is configurable (default context_reliquary) so the probe
can target a throwaway probe_<label> schema.
"""

import json
from uuid import UUID

from reliquary_enrichment.models import Entity
from reliquary_enrichment.postgres.connection import DEFAULT_WRITE_SCHEMA, connect, qualified


def _row_to_entity(row: dict) -> Entity:
    return Entity(
        entity_type=row["entity_type"], canonical=row["canonical"],
        aliases=list(row["aliases"] or []), metadata=dict(row["metadata"] or {}),
        first_seen_record=str(row["first_seen_record"]) if row["first_seen_record"] else None,
        flagged=row["flagged"], entity_id=str(row["entity_id"]),
    )


_COLS = "entity_id, entity_type, canonical, aliases, metadata, first_seen_record, flagged"


class PostgresEntityStore:
    def __init__(self, *, schema: str = DEFAULT_WRITE_SCHEMA) -> None:
        self._table = qualified(schema, "codex_entities")

    def find(self, entity_type: str, canonical: str) -> Entity | None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM {self._table} "
                "WHERE entity_type = %(t)s AND canonical = %(c)s",
                {"t": entity_type, "c": canonical},
            )
            row = cur.fetchone()
        return _row_to_entity(row) if row else None

    def insert(self, entity: Entity) -> str:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._table} "
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
                f"UPDATE {self._table} SET aliases = aliases || %(a)s::jsonb "
                "WHERE entity_id = %(id)s",
                {"a": json.dumps([alias]), "id": entity_id},
            )

    # --- read APIs + the discriminative-weight write path (§5.2/§9) ---
    def get(self, entity_id: str) -> Entity | None:
        try:
            UUID(str(entity_id))
        except (ValueError, TypeError):
            return None
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM {self._table} WHERE entity_id = %(id)s", {"id": entity_id})
            row = cur.fetchone()
        return _row_to_entity(row) if row else None

    def entities_of_type(self, entity_type: str) -> list[Entity]:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM {self._table} WHERE entity_type = %(t)s", {"t": entity_type})
            rows = cur.fetchall()
        return [_row_to_entity(r) for r in rows]

    def set_entity_flags(self, entity_id: str, *, weight: int, is_theme: bool) -> None:
        # PATCH weight + is_theme into metadata (preserve member_records/merged_into) — the only
        # post-insert entity-metadata mutation besides event clustering (§9).
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._table} "
                "SET metadata = jsonb_set("
                "      jsonb_set(metadata, '{weight}', %(w)s::jsonb), "
                "      '{is_theme}', %(t)s::jsonb) "
                "WHERE entity_id = %(id)s",
                {"w": json.dumps(weight), "t": json.dumps(is_theme), "id": entity_id},
            )

    def event_for_record(self, record_id: str) -> Entity | None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM {self._table} "
                "WHERE entity_type = 'event' AND NOT (metadata ? 'merged_into') "
                "  AND metadata->'member_records' @> %(rid)s::jsonb LIMIT 1",
                {"rid": json.dumps([record_id])},
            )
            row = cur.fetchone()
        return _row_to_entity(row) if row else None

    def set_event_members(self, entity_id: str, member_records: list[str]) -> None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._table} "
                "SET metadata = jsonb_set(metadata, '{member_records}', %(m)s::jsonb) "
                "WHERE entity_id = %(id)s",
                {"m": json.dumps(member_records), "id": entity_id},
            )

    def mark_event_merged(self, absorbed_id: str, survivor_id: str) -> None:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._table} "
                "SET metadata = jsonb_set("
                "      jsonb_set(metadata, '{member_records}', '[]'::jsonb), "
                "      '{merged_into}', %(s)s::jsonb), flagged = true "
                "WHERE entity_id = %(id)s",
                {"s": json.dumps(survivor_id), "id": absorbed_id},
            )
