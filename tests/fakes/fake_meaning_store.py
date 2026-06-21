from __future__ import annotations

"""In-memory meaning store for unit tests — enforces one-meaning-per-chunk like the DB UNIQUE."""


class FakeMeaningStore:
    def __init__(self) -> None:
        self.meanings: dict[str, str] = {}      # source_chunk_id -> claim_meaning
        self.embedded: dict[str, list] = {}     # meaning_id -> embedding (the deferred needle's ONLY path)
        self._ids: dict[str, str] = {}          # meaning_id -> source_chunk_id

    def insert(self, *, source_chunk_id: str, claim_meaning: str) -> str:
        if source_chunk_id in self.meanings:
            raise AssertionError("one meaning per chunk (UNIQUE source_chunk_id)")
        meaning_id = f"m-{len(self.meanings)}"
        self.meanings[source_chunk_id] = claim_meaning
        self._ids[meaning_id] = source_chunk_id
        return meaning_id

    def set_embedding(self, meaning_id: str, embedding) -> None:
        self.embedded[meaning_id] = embedding
