from __future__ import annotations

"""PostgresLinkStore — append-only writes to <schema>.enrichment_links (write-once).

Write schema is configurable (default context_reliquary) for probe isolation.
"""

import json

from reliquary_enrichment.models import Link
from reliquary_enrichment.postgres.connection import DEFAULT_WRITE_SCHEMA, connect, qualified

_LINK_COLS = (
    "link_id, record_a, record_b, relation, tier, evidence, confidence, "
    "provenance_validation, event_entity, flagged"
)


def _row_to_link(row: dict) -> Link:
    return Link(
        record_a=str(row["record_a"]), record_b=str(row["record_b"]), relation=row["relation"],
        tier=row["tier"], evidence=row["evidence"] or {},
        provenance_validation=row["provenance_validation"] or {}, confidence=row["confidence"],
        event_entity=str(row["event_entity"]) if row["event_entity"] else None,
        flagged=row["flagged"], link_id=str(row["link_id"]),
    )


class PostgresLinkStore:
    def __init__(self, *, schema: str = DEFAULT_WRITE_SCHEMA) -> None:
        self._table = qualified(schema, "enrichment_links")

    def insert(self, link: Link) -> str:
        sql = f"""
            INSERT INTO {self._table} (
                link_id, record_a, record_b, relation, tier, evidence, confidence,
                provenance_validation, event_entity, flagged
            ) VALUES (
                %(link_id)s, %(record_a)s, %(record_b)s, %(relation)s, %(tier)s,
                %(evidence)s, %(confidence)s, %(provenance_validation)s, %(event_entity)s,
                %(flagged)s
            )
        """
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, {
                "link_id": link.link_id, "record_a": link.record_a, "record_b": link.record_b,
                "relation": link.relation, "tier": link.tier,
                "evidence": json.dumps(link.evidence), "confidence": link.confidence,
                "provenance_validation": json.dumps(link.provenance_validation),
                "event_entity": link.event_entity, "flagged": link.flagged,
            })
        return link.link_id

    # --- read APIs (the codex walker's edge traversal; §5.2) ---
    def links_for_record(self, record_id: str) -> list[Link]:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_LINK_COLS} FROM {self._table} "
                        "WHERE record_a = %(r)s OR record_b = %(r)s", {"r": record_id})
            rows = cur.fetchall()
        return [_row_to_link(r) for r in rows]

    def neighbors_via_links(self, record_id: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for link in self.links_for_record(record_id):
            other = link.record_b if link.record_a == record_id else link.record_a
            out.append((link.relation, other))
        return out
