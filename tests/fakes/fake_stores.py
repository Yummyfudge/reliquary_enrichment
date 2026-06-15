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
