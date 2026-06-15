from __future__ import annotations

"""Fragment — a raw source chunk (the context), and the reader over claim_chunks.

What: the contract's **Fragment** = one ``claim_chunks`` row. This module defines the
Fragment value object and the FragmentReader protocol the grounding-core depends on.
Why: pins the contract-vs-reality column mapping (findings B1/B2) in ONE place so the
ubiquitous term "Fragment" stays clean while the storage detail lives in an adapter.

THE TEXT THE MODEL POINTS INTO ≡ ``payload->>'chunk_text'`` (findings B2). The read
tools surface exactly this text; the grounding-core slices Evidence Spans from exactly
this text; ``source_sha256`` hashes exactly this text. No other string is ever the
slice source — otherwise the model's offsets and code's slice disagree and grounding is
meaningless.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Fragment:
    """One raw source chunk loaded from ``context_reliquary.claim_chunks``.

    Field mapping (contract term -> real column):
      chunk_id  <- claim_chunk_id (uuid, the canonical id)
      text      <- payload->>'chunk_text'  (the ONLY slice source)
      document  <- document_name
      page      <- page_number
      chunk_type<- chunk_type
    """

    chunk_id: str
    text: str
    document: str | None = None
    page: int | None = None
    chunk_type: str | None = None


class FragmentReader(Protocol):
    """Loads a Fragment by canonical chunk_id. Returns None when absent.

    Implementations read ``claim_chunks`` (Postgres) or are fakes in unit tests. The
    grounding-core depends on this protocol, never on a concrete store — so the heart is
    unit-testable with no DB.
    """

    def get(self, chunk_id: str) -> Fragment | None:
        ...
