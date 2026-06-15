from __future__ import annotations

"""Codex Entity resolution — code materializes Entities; the model never types one.

Normalize a judge-validated surface form (actor name / event_date) to a canonical key and
resolve-or-create the Entity (dedupe key = entity_type + canonical). Used by
write_enrichment step 9 (actor/date) and link_events §6 (event, from same_event).

Normalization is MINIMAL by decision (codex §9-B): exact match on a lightly-normalized
canonical, with observed surface forms recorded as aliases. Fuzzy canonicalization
("B. Smith" vs "Bruce Smith") is a later, curation-gated task — we never silently merge.
"""

import re

from reliquary_enrichment.models import Entity, EntityRef
from reliquary_enrichment.stores import EntityStore

_WS = re.compile(r"\s+")


def normalize_actor(surface: str) -> str:
    """Collapse whitespace; keep surface casing/punctuation (minimal — codex §9-B)."""
    return _WS.sub(" ", surface).strip()


def normalize_date(surface: str) -> str:
    """Trim a normalized date string. The model already normalized + the judge verified it."""
    return surface.strip()


_NORMALIZERS = {"actor": normalize_actor, "date": normalize_date}


class EntityResolver:
    """Resolve-or-create Entities against an EntityStore, recording aliases."""

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    def resolve_or_create(
        self,
        entity_type: str,
        surface: str,
        *,
        first_seen_record: str | None = None,
    ) -> Entity:
        """Return the Entity for (type, normalized surface), creating it if new.

        On a hit, record the surface form as an alias when it differs from canonical (so
        the registry learns variants without merging). On a miss, create with
        ``first_seen_record`` set.
        """
        normalize = _NORMALIZERS.get(entity_type, lambda s: s.strip())
        canonical = normalize(surface)
        existing = self._store.find(entity_type, canonical)
        if existing is not None:
            if surface != canonical and surface not in existing.aliases:
                self._store.add_alias(existing.entity_id, surface)
            return existing
        entity = Entity(
            entity_type=entity_type,
            canonical=canonical,
            aliases=[] if surface == canonical else [surface],
            first_seen_record=first_seen_record,
        )
        self._store.insert(entity)
        return entity

    def ref_for(self, role: str, entity: Entity) -> EntityRef:
        """Build the EntityRef a record stores at this Entity."""
        return EntityRef(
            role=role,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            canonical=entity.canonical,
        )


class EventMaterializer:
    """Materialize/merge Event Entities from grounded same_event Links (codex §6).

    The ONLY way an Event Entity is born. The model asserts pairwise same_event + grounded;
    CODE maintains the cluster (union-find over record_ids), including transitive merges
    (A~B, B~C => one event). Membership is stored on the Event Entity (metadata.member_records)
    — records are write-once and are never mutated; their event is found by membership.
    """

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    @staticmethod
    def _members(event: Entity) -> list[str]:
        return list(event.metadata.get("member_records", []))

    def materialize(self, record_a: str, record_b: str) -> Entity:
        """Place record_a and record_b in one Event cluster; return the surviving Entity."""
        ea = self._store.event_for_record(record_a)
        eb = self._store.event_for_record(record_b)

        if ea is not None and eb is not None:
            if ea.entity_id == eb.entity_id:
                return ea                                   # already the same cluster
            return self._merge(ea, eb)                      # transitive merge
        if ea is not None:
            self._add_member(ea, record_b)
            return ea
        if eb is not None:
            self._add_member(eb, record_a)
            return eb
        return self._create(record_a, record_b)

    def _create(self, record_a: str, record_b: str) -> Entity:
        members = sorted({record_a, record_b})
        # canonical is a stable label; membership (metadata) is the authoritative identity.
        event = Entity(
            entity_type="event",
            canonical=f"event:{members[0]}",
            metadata={"member_records": members},
            first_seen_record=record_a,
        )
        self._store.insert(event)
        return event

    def _add_member(self, event: Entity, record_id: str) -> None:
        members = sorted(set(self._members(event)) | {record_id})
        event.metadata["member_records"] = members
        self._store.set_event_members(event.entity_id, members)

    def _merge(self, survivor: Entity, absorbed: Entity) -> Entity:
        members = sorted(set(self._members(survivor)) | set(self._members(absorbed)))
        survivor.metadata["member_records"] = members
        self._store.set_event_members(survivor.entity_id, members)
        self._store.mark_event_merged(absorbed.entity_id, survivor.entity_id)
        return survivor
