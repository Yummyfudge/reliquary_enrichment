from __future__ import annotations

"""Domain models — the rows the tools write (== the schema, == the ubiquitous language).

EnrichmentRecord (one grounded fact), Entity (a normalized Codex noun), Link (a
cross-record Codex edge), and EntityRef (the pointer a record stores at an Entity). These
mirror schema/ 1:1 so the same names live in code, schema, and docs (SCOPE §15).
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class EntityRef:
    """A record's pointer at a Codex Entity (stored inside enrichment_records.entity_refs)."""

    role: str          # which field this resolved from: "actor" | "event_date"
    entity_id: str
    entity_type: str   # "actor" | "date" | "event" | ...
    canonical: str

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical": self.canonical,
        }


@dataclass(slots=True)
class EnrichmentRecord:
    """One grounded Enrichment Record — write-once (enrichment_records).

    Provenance + hashes are CODE-derived (never from the model payload). ``record_id`` is
    generated in code so Entities can carry ``first_seen_record`` before the row inserts.
    """

    record_type: str
    tier: str
    source_chunk_id: str
    char_start: int
    char_end: int
    evidence_span: str
    provenance_validation: dict
    fields: dict = field(default_factory=dict)
    actor: str | None = None
    event_date: str | None = None
    claim_relevance: str | None = None
    confidence: float | None = None
    page: int | None = None
    document: str | None = None
    entity_refs: list[EntityRef] = field(default_factory=list)
    flagged: bool = False
    supersedes: str | None = None
    record_id: str = field(default_factory=lambda: str(uuid4()))
    created: datetime | None = None


@dataclass(slots=True)
class Entity:
    """A normalized Codex Entity — actor / date / event / … (codex_entities)."""

    entity_type: str
    canonical: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    first_seen_record: str | None = None
    flagged: bool = False
    entity_id: str = field(default_factory=lambda: str(uuid4()))
    created: datetime | None = None


@dataclass(slots=True)
class Link:
    """One grounded cross-record Link — write-once (enrichment_links)."""

    record_a: str
    record_b: str
    relation: str
    tier: str
    evidence: dict
    provenance_validation: dict
    confidence: float | None = None
    event_entity: str | None = None
    flagged: bool = False
    link_id: str = field(default_factory=lambda: str(uuid4()))
    created: datetime | None = None
