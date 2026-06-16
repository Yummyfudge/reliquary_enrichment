from __future__ import annotations

"""PostgresLinkStore — append-only writes to <schema>.enrichment_links (write-once).

Write schema is configurable (default context_reliquary) for probe isolation.
"""

import json

from reliquary_enrichment.models import Link
from reliquary_enrichment.postgres.connection import DEFAULT_WRITE_SCHEMA, connect, qualified


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
