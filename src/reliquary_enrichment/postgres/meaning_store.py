from __future__ import annotations

"""PostgresEnrichmentMeaningStore — the ONLY writer of enrichment_meaning (brief §5.4 #6, the bright line).

enrichment_meaning.embedding is the ONLY embedded column anywhere, and ``set_embedding`` here is the ONLY
code path that writes it (the DEFERRED needle step §5.4 #11 — nothing embeds today). The MeaningWriter
persists the local-fact TEXT via ``insert`` (no embedding); the embedding is added later, against a schema
where the vector extension exists (NOT the probe schema). UNIQUE(source_chunk_id) = one meaning per chunk.
The write schema is configurable so the harness can target a throwaway probe_<label> schema.
"""

import uuid

from reliquary_enrichment.postgres.connection import DEFAULT_WRITE_SCHEMA, connect, qualified


class PostgresEnrichmentMeaningStore:
    def __init__(self, *, schema: str = DEFAULT_WRITE_SCHEMA) -> None:
        self._table = qualified(schema, "enrichment_meaning")

    def insert(self, *, source_chunk_id: str, claim_meaning: str) -> str:
        """Persist the chunk's local-fact meaning (text only — NO embedding). Returns the meaning_id."""
        meaning_id = str(uuid.uuid4())
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._table} (meaning_id, source_chunk_id, claim_meaning) "
                "VALUES (%(id)s, %(chunk)s, %(meaning)s)",
                {"id": meaning_id, "chunk": source_chunk_id, "meaning": claim_meaning},
            )
        return meaning_id

    def set_embedding(self, meaning_id: str, embedding) -> None:
        """The EXCLUSIVE embedding-write path (deferred needle, §5.4 #11). enrichment_meaning.embedding is
        the only embedded artifact anywhere; this is the only code that ever writes it. Targets a schema
        with the vector extension (prod), never the extension-free probe schema."""
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._table} SET embedding = %(e)s::vector WHERE meaning_id = %(id)s",
                {"e": embedding, "id": meaning_id},
            )
