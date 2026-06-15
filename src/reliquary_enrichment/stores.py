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
