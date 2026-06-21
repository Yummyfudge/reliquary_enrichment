from __future__ import annotations

"""In-memory stores for unit tests — enforce write-once + dedupe like the DB does."""

from reliquary_enrichment.models import EnrichmentRecord, Entity, Link


class FakeRecordStore:
    def __init__(self) -> None:
        self.records: dict[str, EnrichmentRecord] = {}

    def insert(self, record: EnrichmentRecord) -> str:
        if record.record_id in self.records:
            raise AssertionError("write-once violated: record_id already exists")
        self.records[record.record_id] = record
        return record.record_id

    def get(self, record_id: str) -> EnrichmentRecord | None:
        return self.records.get(record_id)

    # --- read APIs (mirror the Postgres jsonb-containment semantics; §5.2) ---
    def records_by_entity(self, entity_id: str) -> list[EnrichmentRecord]:
        return [r for r in self.records.values()
                if any(ref.entity_id == entity_id for ref in r.entity_refs)]

    def chunks_by_entity(self, entity_id: str) -> list[str]:
        # DISTINCT source_chunk_ids (an entity cited by 2 records in one chunk counts once).
        return list(dict.fromkeys(r.source_chunk_id for r in self.records_by_entity(entity_id)))

    def cooccurrence(self, entity_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.records_by_entity(entity_id):
            for ref in r.entity_refs:
                if ref.entity_id != entity_id:
                    counts[ref.entity_id] = counts.get(ref.entity_id, 0) + 1
        return counts


class FakeEntityStore:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}              # entity_id -> Entity
        self._by_key: dict[tuple[str, str], str] = {}      # (type, canonical) -> entity_id

    def find(self, entity_type: str, canonical: str) -> Entity | None:
        eid = self._by_key.get((entity_type, canonical))
        return self.entities.get(eid) if eid else None

    def insert(self, entity: Entity) -> str:
        key = (entity.entity_type, entity.canonical)
        if key in self._by_key:
            raise AssertionError("dedupe violated: (type, canonical) already exists")
        self.entities[entity.entity_id] = entity
        self._by_key[key] = entity.entity_id
        return entity.entity_id

    def add_alias(self, entity_id: str, alias: str) -> None:
        self.entities[entity_id].aliases.append(alias)

    # --- read APIs + the discriminative-weight write path (§5.2/§9) ---
    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def entities_of_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.entity_type == entity_type]

    def set_entity_flags(self, entity_id: str, *, weight: int, is_theme: bool) -> None:
        # the ONLY post-insert entity-metadata mutation besides event clustering; PATCH (don't
        # clobber member_records/merged_into) — mirrors the Postgres jsonb_set.
        meta = self.entities[entity_id].metadata
        meta["weight"] = weight
        meta["is_theme"] = is_theme

    # --- event clustering ---
    def event_for_record(self, record_id: str) -> Entity | None:
        for e in self.entities.values():
            if e.entity_type != "event" or e.metadata.get("merged_into"):
                continue
            if record_id in e.metadata.get("member_records", []):
                return e
        return None

    def set_event_members(self, entity_id: str, member_records: list[str]) -> None:
        self.entities[entity_id].metadata["member_records"] = list(member_records)

    def mark_event_merged(self, absorbed_id: str, survivor_id: str) -> None:
        e = self.entities[absorbed_id]
        e.metadata["member_records"] = []
        e.metadata["merged_into"] = survivor_id
        e.flagged = True


class FakeLinkStore:
    def __init__(self) -> None:
        self.links: dict[str, Link] = {}

    def insert(self, link: Link) -> str:
        self.links[link.link_id] = link
        return link.link_id

    # --- read APIs (the codex walker's edge traversal; §5.2) ---
    def links_for_record(self, record_id: str) -> list[Link]:
        return [l for l in self.links.values()
                if l.record_a == record_id or l.record_b == record_id]

    def neighbors_via_links(self, record_id: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for l in self.links.values():
            if l.record_a == record_id:
                out.append((l.relation, l.record_b))
            elif l.record_b == record_id:
                out.append((l.relation, l.record_a))
        return out
