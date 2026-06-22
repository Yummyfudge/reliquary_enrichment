from __future__ import annotations

"""Store protocols — the persistence seams the tools depend on (never a concrete DB).

Keeping these as Protocols lets write_enrichment / link_events be unit-tested against
in-memory fakes (the contract acceptance tests) while the Postgres implementations live in
``postgres/``. Records and links are WRITE-ONCE: the protocols expose ``insert`` only,
never update/delete (mirrored by the DB trigger + grants).
"""

from typing import Protocol

from reliquary_enrichment.models import EnrichmentRecord, Entity, Link


class EnrichmentRecordStore(Protocol):
    """Append-only store for Enrichment Records."""

    def insert(self, record: EnrichmentRecord) -> str:
        """Persist a record (immutable). Returns its record_id."""
        ...

    def get(self, record_id: str) -> EnrichmentRecord | None:
        """Load a record by id (used by link_events to resolve record refs)."""
        ...

    # --- read APIs: the entity->record reverse lookup (entity_refs is denormalized jsonb,
    #     so these are jsonb-containment queries, NOT FK joins). §5.2.
    def records_by_entity(self, entity_id: str) -> list[EnrichmentRecord]:
        """All records whose entity_refs include entity_id."""
        ...

    def chunks_by_entity(self, entity_id: str) -> list[str]:
        """Distinct source_chunk_ids of the records citing entity_id (the discriminative-weight count)."""
        ...

    def records_by_chunk(self, chunk_id: str) -> list[EnrichmentRecord]:
        """All records grounded on a chunk (the codex walker's `entities_of(chunk)` seed; §5.4 #9)."""
        ...

    def cooccurrence(self, entity_id: str) -> dict[str, int]:
        """For entities sharing a record with entity_id: other_entity_id -> count (excludes self)."""
        ...


class EntityStore(Protocol):
    """Resolve-or-create store for Codex Entities (dedupe key: entity_type + canonical)."""

    def find(self, entity_type: str, canonical: str) -> Entity | None:
        ...

    def insert(self, entity: Entity) -> str:
        """Create a new Entity. Returns its entity_id."""
        ...

    def add_alias(self, entity_id: str, alias: str) -> None:
        """Record an observed surface form on an existing Entity (curation-safe)."""
        ...

    def get(self, entity_id: str) -> Entity | None:
        """Load an Entity by id."""
        ...

    def entities_of_type(self, entity_type: str) -> list[Entity]:
        """All Entities of a given closed-vocab type."""
        ...

    def set_entity_flags(self, entity_id: str, *, weight: int, is_theme: bool) -> None:
        """Persist the discriminative weight + theme-flag into metadata (§9) — the ONLY post-insert
        entity-metadata mutation besides event clustering (patch, never clobber)."""
        ...

    # --- Event clustering (same_event materialization; codex §6) -------------------
    # Event membership is tracked on the Event Entity (metadata.member_records), NOT by
    # mutating the write-once records. A record's event is found by membership lookup.
    def event_for_record(self, record_id: str) -> Entity | None:
        """Return the (non-merged) Event Entity whose members include record_id, else None."""
        ...

    def set_event_members(self, entity_id: str, member_records: list[str]) -> None:
        """Replace an Event Entity's member_records (cluster growth)."""
        ...

    def mark_event_merged(self, absorbed_id: str, survivor_id: str) -> None:
        """Mark an Event Entity absorbed into survivor_id: clear members, flag for curation."""
        ...


class LinkStore(Protocol):
    """Append-only store for cross-record Links."""

    def insert(self, link: Link) -> str:
        ...

    def links_for_record(self, record_id: str) -> list[Link]:
        """All links touching record_id (as record_a or record_b)."""
        ...

    def neighbors_via_links(self, record_id: str) -> list[tuple[str, str]]:
        """(relation, other_record_id) for each link touching record_id — the codex walker's hop."""
        ...
