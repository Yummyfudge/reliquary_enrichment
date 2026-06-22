from __future__ import annotations

"""Unit tests for the store READ-API layer (brief §5.2 / build step 5.5), against the fakes.

These go green BEFORE the discriminative-weight pass (step 6) and the codex walker (step 9) depend
on them. The Postgres impls mirror these EXACT semantics (jsonb-containment for the entity reverse
lookup, since entity_refs is denormalized jsonb — no join table); fake parity IS the contract (§10.1).
"""

from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef, Link
from tests.fakes.fake_stores import FakeEntityStore, FakeLinkStore, FakeRecordStore


def _rec(rid, chunk, refs):
    return EnrichmentRecord(
        record_type="x", tier="fact", source_chunk_id=chunk, char_start=0, char_end=1,
        evidence_span="x", provenance_validation={},
        entity_refs=[EntityRef(*r) for r in refs], record_id=rid,
    )


def _ent(eid, etype, canon, **md):
    return Entity(entity_type=etype, canonical=canon, metadata=dict(md), entity_id=eid)


def _link(lid, a, b, rel):
    return Link(record_a=a, record_b=b, relation=rel, tier="fact", evidence={},
                provenance_validation={}, link_id=lid)


# --- EntityStore read APIs --------------------------------------------------
def test_entity_get_and_entities_of_type():
    s = FakeEntityStore()
    for e in (_ent("e1", "actor", "B. Smith"), _ent("e2", "actor", "JoAnn F."), _ent("e3", "date", "2024-02-18")):
        s.insert(e)
    assert s.get("e1").canonical == "B. Smith"
    assert s.get("nope") is None
    assert {e.entity_id for e in s.entities_of_type("actor")} == {"e1", "e2"}
    assert [e.entity_id for e in s.entities_of_type("date")] == ["e3"]


def test_set_entity_flags_patches_metadata_preserving_existing():
    s = FakeEntityStore()
    s.insert(_ent("e1", "event", "ev", member_records=["r1", "r2"]))
    s.set_entity_flags("e1", weight=7, is_theme=True)
    md = s.get("e1").metadata
    assert md["weight"] == 7 and md["is_theme"] is True
    assert md["member_records"] == ["r1", "r2"]      # existing metadata NOT clobbered


# --- EnrichmentRecordStore read APIs ----------------------------------------
def test_records_and_chunks_by_entity():
    s = FakeRecordStore()
    s.insert(_rec("r1", "c1", [("actor", "e1", "actor", "B. Smith")]))
    s.insert(_rec("r2", "c1", [("actor", "e1", "actor", "B. Smith"), ("date", "e2", "date", "2024-02-18")]))
    s.insert(_rec("r3", "c2", [("actor", "e1", "actor", "B. Smith")]))
    s.insert(_rec("r4", "c3", [("date", "e2", "date", "2024-02-18")]))
    assert {r.record_id for r in s.records_by_entity("e1")} == {"r1", "r2", "r3"}
    assert s.chunks_by_entity("e1") == ["c1", "c2"]   # DISTINCT chunks (c1 cited twice -> once)
    assert s.chunks_by_entity("e2") == ["c1", "c3"]


def test_cooccurrence_counts_other_entities_in_shared_records():
    s = FakeRecordStore()
    s.insert(_rec("r1", "c1", [("actor", "e1", "actor", "A"), ("date", "e2", "date", "D")]))
    s.insert(_rec("r2", "c2", [("actor", "e1", "actor", "A"), ("code", "e3", "code", "F06.4")]))
    assert s.cooccurrence("e1") == {"e2": 1, "e3": 1}   # e1 with e2 (r1), e3 (r2); excludes self


# --- LinkStore read APIs ----------------------------------------------------
def test_links_for_record_and_neighbors():
    s = FakeLinkStore()
    s.insert(_link("l1", "rA", "rB", "precedes"))
    s.insert(_link("l2", "rC", "rA", "causes"))
    s.insert(_link("l3", "rX", "rY", "elaborates"))
    assert {l.link_id for l in s.links_for_record("rA")} == {"l1", "l2"}
    assert set(s.neighbors_via_links("rA")) == {("precedes", "rB"), ("causes", "rC")}
