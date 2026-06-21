from __future__ import annotations

"""PostgresEnrichmentRecordStore — append-only writes to <schema>.enrichment_records.

INSERT only (write-once; the DB trigger + grants forbid UPDATE/DELETE). The write schema
is configurable (default context_reliquary) so the extraction probe can target a throwaway
``probe_<label>`` schema in isolation; prod behavior is unchanged at the default.
"""

import json
from uuid import UUID

from reliquary_enrichment.models import EnrichmentRecord, EntityRef
from reliquary_enrichment.postgres.connection import DEFAULT_WRITE_SCHEMA, connect, qualified

# claim_relevance is gone (codex refactor §5.3 — whole-claim significance relocated). The prod
# column is retained (additive discipline) but never written; refactored-run rows are NULL there,
# and the probe records table drops the column entirely (isolation_schema).
_REC_COLS = (
    "record_id, record_type, tier, fields, actor, event_date, "
    "confidence, source_chunk_id, char_start, char_end, page, document, "
    "evidence_span, provenance_validation, entity_refs, flagged, supersedes"
)


def _row_to_record(row: dict) -> EnrichmentRecord:
    refs = [
        EntityRef(r["role"], r["entity_id"], r["entity_type"], r["canonical"])
        for r in (row["entity_refs"] or [])
    ]
    return EnrichmentRecord(
        record_type=row["record_type"], tier=row["tier"],
        source_chunk_id=str(row["source_chunk_id"]), char_start=row["char_start"],
        char_end=row["char_end"], evidence_span=row["evidence_span"],
        provenance_validation=row["provenance_validation"], fields=row["fields"] or {},
        actor=row["actor"], event_date=row["event_date"], confidence=row["confidence"],
        page=row["page"], document=row["document"], entity_refs=refs,
        flagged=row["flagged"], supersedes=str(row["supersedes"]) if row["supersedes"] else None,
        record_id=str(row["record_id"]),
    )


class PostgresEnrichmentRecordStore:
    def __init__(self, *, schema: str = DEFAULT_WRITE_SCHEMA) -> None:
        self._table = qualified(schema, "enrichment_records")

    def insert(self, record: EnrichmentRecord) -> str:
        sql = f"""
            INSERT INTO {self._table} (
                record_id, record_type, tier, fields, actor, event_date,
                confidence, source_chunk_id, char_start, char_end, page, document,
                evidence_span, provenance_validation, entity_refs, flagged, supersedes
            ) VALUES (
                %(record_id)s, %(record_type)s, %(tier)s, %(fields)s, %(actor)s,
                %(event_date)s, %(confidence)s, %(source_chunk_id)s,
                %(char_start)s, %(char_end)s, %(page)s, %(document)s, %(evidence_span)s,
                %(provenance_validation)s, %(entity_refs)s, %(flagged)s, %(supersedes)s
            )
        """
        params = {
            "record_id": record.record_id,
            "record_type": record.record_type,
            "tier": record.tier,
            "fields": json.dumps(record.fields),
            "actor": record.actor,
            "event_date": record.event_date,
            "confidence": record.confidence,
            "source_chunk_id": record.source_chunk_id,
            "char_start": record.char_start,
            "char_end": record.char_end,
            "page": record.page,
            "document": record.document,
            "evidence_span": record.evidence_span,
            "provenance_validation": json.dumps(record.provenance_validation),
            "entity_refs": json.dumps([r.as_dict() for r in record.entity_refs]),
            "flagged": record.flagged,
            "supersedes": record.supersedes,
        }
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
        return record.record_id

    def get(self, record_id: str) -> EnrichmentRecord | None:
        try:
            UUID(str(record_id))
        except (ValueError, TypeError):
            return None
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_REC_COLS} FROM {self._table} WHERE record_id = %(record_id)s",
                        {"record_id": record_id})
            row = cur.fetchone()
        return _row_to_record(row) if row else None

    # --- read APIs: entity -> record reverse lookup via jsonb-containment (no join table) ---
    def records_by_entity(self, entity_id: str) -> list[EnrichmentRecord]:
        probe = json.dumps([{"entity_id": entity_id}])
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_REC_COLS} FROM {self._table} "
                        "WHERE entity_refs @> %(probe)s::jsonb", {"probe": probe})
            rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    def chunks_by_entity(self, entity_id: str) -> list[str]:
        probe = json.dumps([{"entity_id": entity_id}])
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT source_chunk_id FROM {self._table} "
                        "WHERE entity_refs @> %(probe)s::jsonb", {"probe": probe})
            rows = cur.fetchall()
        return [str(r["source_chunk_id"]) for r in rows]

    def cooccurrence(self, entity_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records_by_entity(entity_id):       # Python-side for fake parity
            for ref in record.entity_refs:
                if ref.entity_id != entity_id:
                    counts[ref.entity_id] = counts.get(ref.entity_id, 0) + 1
        return counts
