from __future__ import annotations

"""PostgresEnrichmentRecordStore — append-only writes to enrichment_records.

INSERT only (write-once; the DB trigger + grants forbid UPDATE/DELETE). entity_refs,
fields, and provenance_validation are jsonb. ``get`` reconstructs enough of the record for
link_events to resolve a record ref to its source Fragment.
"""

import json

from reliquary_enrichment.models import EnrichmentRecord, EntityRef
from reliquary_enrichment.postgres.connection import connect

_INSERT = """
    INSERT INTO context_reliquary.enrichment_records (
        record_id, record_type, tier, fields, actor, event_date, claim_relevance,
        confidence, source_chunk_id, char_start, char_end, page, document, evidence_span,
        provenance_validation, entity_refs, flagged, supersedes
    ) VALUES (
        %(record_id)s, %(record_type)s, %(tier)s, %(fields)s, %(actor)s, %(event_date)s,
        %(claim_relevance)s, %(confidence)s, %(source_chunk_id)s, %(char_start)s,
        %(char_end)s, %(page)s, %(document)s, %(evidence_span)s, %(provenance_validation)s,
        %(entity_refs)s, %(flagged)s, %(supersedes)s
    )
"""

_SELECT = """
    SELECT record_id, record_type, tier, fields, actor, event_date, claim_relevance,
           confidence, source_chunk_id, char_start, char_end, page, document, evidence_span,
           provenance_validation, entity_refs, flagged, supersedes
    FROM context_reliquary.enrichment_records WHERE record_id = %(record_id)s
"""


class PostgresEnrichmentRecordStore:
    def insert(self, record: EnrichmentRecord) -> str:
        params = {
            "record_id": record.record_id,
            "record_type": record.record_type,
            "tier": record.tier,
            "fields": json.dumps(record.fields),
            "actor": record.actor,
            "event_date": record.event_date,
            "claim_relevance": record.claim_relevance,
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
            cur.execute(_INSERT, params)
        return record.record_id

    def get(self, record_id: str) -> EnrichmentRecord | None:
        from uuid import UUID
        try:
            UUID(str(record_id))
        except (ValueError, TypeError):
            return None
        with connect() as conn, conn.cursor() as cur:
            cur.execute(_SELECT, {"record_id": record_id})
            row = cur.fetchone()
        if not row:
            return None
        refs = [
            EntityRef(r["role"], r["entity_id"], r["entity_type"], r["canonical"])
            for r in (row["entity_refs"] or [])
        ]
        return EnrichmentRecord(
            record_type=row["record_type"], tier=row["tier"],
            source_chunk_id=str(row["source_chunk_id"]), char_start=row["char_start"],
            char_end=row["char_end"], evidence_span=row["evidence_span"],
            provenance_validation=row["provenance_validation"], fields=row["fields"] or {},
            actor=row["actor"], event_date=row["event_date"],
            claim_relevance=row["claim_relevance"], confidence=row["confidence"],
            page=row["page"], document=row["document"], entity_refs=refs,
            flagged=row["flagged"], supersedes=str(row["supersedes"]) if row["supersedes"] else None,
            record_id=str(row["record_id"]),
        )
