from __future__ import annotations

"""PostgresFragmentReader — loads Fragments from context_reliquary.claim_chunks.

Maps the real columns to the contract's Fragment (findings B1/B2): text is
``payload->>'chunk_text'`` (the ONLY slice source), document is ``document_name``, page is
``page_number``. A non-UUID chunk_id resolves to None (treated as not-found) — so a mangled
id never reaches a SQL error path; the 89503 discipline holds at the DB layer too.
"""

from uuid import UUID

from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.postgres.connection import connect

_SELECT = """
    SELECT claim_chunk_id, document_name, page_number, chunk_type, segment_index,
           payload->>'chunk_text' AS chunk_text
    FROM context_reliquary.claim_chunks
    WHERE claim_chunk_id = %(chunk_id)s
"""

# Neighbors: same document, adjacent by segment_index (cross-link context; §8 doc-adjacency).
# RESOLVED (read-only DB check, codex-refactor PRE-FLIGHT §4.2): segment_index IS the
# intra-document ordering key. char_start_offset is degenerate — constant (0) for every row
# (5117/5117 adjacent pairs tie; gold note 89503c71 char_start=0), so it carries no ordering
# signal and must NOT be used as the key. Caveat for §8 adjacency candidate-links:
# segment_index has ties (77 (document, segment_index) groups share a value) and 75 NULL rows
# corpus-wide, so a window may include same-segment chunks and NULL-segment chunks are absent
# from neighbor windows — bound/dedupe adjacency candidates accordingly.
_NEIGHBORS = """
    WITH anchor AS (
        SELECT document_name, segment_index
        FROM context_reliquary.claim_chunks WHERE claim_chunk_id = %(chunk_id)s
    )
    SELECT c.claim_chunk_id, c.document_name, c.page_number, c.chunk_type, c.segment_index,
           c.payload->>'chunk_text' AS chunk_text
    FROM context_reliquary.claim_chunks c, anchor a
    WHERE c.document_name = a.document_name
      AND c.segment_index BETWEEN a.segment_index - %(window)s AND a.segment_index + %(window)s
    ORDER BY c.segment_index
"""


def _row_to_fragment(row: dict) -> Fragment:
    return Fragment(
        chunk_id=str(row["claim_chunk_id"]),
        text=row["chunk_text"] or "",
        document=row["document_name"],
        page=row["page_number"],
        chunk_type=row["chunk_type"],
    )


def _valid_uuid(chunk_id: str) -> bool:
    try:
        UUID(str(chunk_id))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class PostgresFragmentReader:
    """Reads claim_chunks. Implements FragmentReader.get + a neighbors query."""

    def get(self, chunk_id: str) -> Fragment | None:
        if not _valid_uuid(chunk_id):
            return None
        with connect() as conn, conn.cursor() as cur:
            cur.execute(_SELECT, {"chunk_id": chunk_id})
            row = cur.fetchone()
        return _row_to_fragment(row) if row else None

    def neighbors(self, chunk_id: str, window: int) -> list[Fragment]:
        if not _valid_uuid(chunk_id):
            return []
        with connect() as conn, conn.cursor() as cur:
            cur.execute(_NEIGHBORS, {"chunk_id": chunk_id, "window": int(window)})
            rows = cur.fetchall()
        return [_row_to_fragment(r) for r in rows]
