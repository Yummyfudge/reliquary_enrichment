from __future__ import annotations

"""Acceptance for codex_walk — the query-time AGENTIC-ASSEMBLY walker (brief §5.4 #9, §10 (4)).

The codex (entities + records + grounded links) is the structure an agent WALKS at query time to
assemble the larger answer — NOT a vector packed with context (§3.1). The §10 acceptance: from ANY chunk
mentioning B. Smith, REACH the gold-note reversal event via GROUNDED links — even when the embedding
would not rank it top-k — and every hop is cited. §8d names the required edges: the reversal record links
to the decision record it undid, to the B. Smith actor node, and to the reversal's date node.

The fixture builds exactly that topology, and (the key discriminator) makes the decision + date records
reachable ONLY through the gold record's grounded links — they share NO entity with the seed chunk — so
reaching them PROVES link-based assembly, not a shared-entity coincidence.
"""

from reliquary_enrichment.codex_walk import CodexWalk, Hop, WalkResult
from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef, Link
from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID
from tests.fakes.fake_stores import FakeEntityStore, FakeLinkStore, FakeRecordStore

SEED_CHUNK = "11111111-1111-1111-1111-111111111111"   # some OTHER chunk that mentions B. Smith
DEC_CHUNK = "22222222-2222-2222-2222-222222222222"     # the original denial the reversal undid
DATE_CHUNK = "33333333-3333-3333-3333-333333333333"    # the reversal's date node (metadata)


def _rec(chunk, span, refs, rtype="event"):
    return EnrichmentRecord(
        record_type=rtype, tier="interpretation", source_chunk_id=chunk, char_start=0,
        char_end=len(span), evidence_span=span, provenance_validation={"verdict": "grounded"},
        entity_refs=refs,
    )


def _ref(eid, canonical, etype="actor", role="actor"):
    return EntityRef(role=role, entity_id=eid, entity_type=etype, canonical=canonical)


def _codex():
    rs, es, ls = FakeRecordStore(), FakeEntityStore(), FakeLinkStore()
    smith = Entity(entity_type="actor", canonical="B. Smith"); es.insert(smith)
    mh = Entity(entity_type="provision", canonical="Mental Health limitation"); es.insert(mh)

    r_seed = _rec(SEED_CHUNK, "Status reviewed with manager B. Smith on file",
                  [_ref(smith.entity_id, "B. Smith")])
    r_gold = _rec(GOLD_CHUNK_ID,
                  "Body Reviewed with manager B. Smith: Place claim back to a Mental Health limitation",
                  [_ref(smith.entity_id, "B. Smith"),
                   _ref(mh.entity_id, "Mental Health limitation", "provision", "provision")])
    # the decision the reversal undid + the date node — NEITHER cites B. Smith (reachable ONLY via link)
    r_dec = _rec(DEC_CHUNK, "Claim denied under the mental health exclusion", [])
    r_date = _rec(DATE_CHUNK, "Last Modified 2/18/2024",
                  [_ref("d-1", "2024-02-18", "date", "event_date")], rtype="date")
    for r in (r_seed, r_gold, r_dec, r_date):
        rs.insert(r)

    # Grounded-link evidence is the CODE-SLICED span pair the linker actually writes (link_events.py:175):
    # {a_span:[s,e], b_span:[s,e], a_source_chunk_id, b_source_chunk_id}. NOT a free-text {"span": ...}.
    ls.insert(Link(record_a=r_gold.record_id, record_b=r_dec.record_id, relation="reverses",
                   tier="interpretation",
                   evidence={"a_span": [30, 46], "b_span": [0, 12],
                             "a_source_chunk_id": GOLD_CHUNK_ID, "b_source_chunk_id": DEC_CHUNK},
                   provenance_validation={"verdict": "grounded"}))
    ls.insert(Link(record_a=r_gold.record_id, record_b=r_date.record_id, relation="occurred_on",
                   tier="fact",
                   evidence={"a_span": [0, 10], "b_span": [14, 23],
                             "a_source_chunk_id": GOLD_CHUNK_ID, "b_source_chunk_id": DATE_CHUNK},
                   provenance_validation={"verdict": "grounded"}))

    walk = CodexWalk(record_store=rs, entity_store=es, link_store=ls)
    return walk, {"smith": smith, "r_seed": r_seed, "r_gold": r_gold, "r_dec": r_dec,
                  "r_date": r_date, "rs": rs, "es": es, "ls": ls}


# --- THE §10 ACCEPTANCE -------------------------------------------------------
def test_reaches_gold_reversal_from_bsmith_chunk():
    w, f = _codex()
    res = w.assemble(target_record=f["r_gold"].record_id, seed_chunk=SEED_CHUNK)
    assert res.reached and res.target == f["r_gold"].record_id
    assert all(h.cited for h in res.path)                 # every hop cited (the grounding law)


def test_assembles_decision_via_grounded_link():
    # r_dec shares NO entity with the seed chunk — reachable ONLY by following the grounded 'reverses'
    # link off the gold record (§8d). Reaching it proves LINK-based assembly, not shared-entity.
    w, f = _codex()
    res = w.assemble(target_record=f["r_dec"].record_id, seed_chunk=SEED_CHUNK)
    assert res.reached
    assert any(h.kind == "link" and h.relation == "reverses" for h in res.path)
    assert all(h.cited for h in res.path)


def test_reaches_date_node_via_link():
    w, f = _codex()
    res = w.assemble(target_record=f["r_date"].record_id, seed_chunk=SEED_CHUNK)
    assert res.reached and any(h.kind == "link" and h.relation == "occurred_on" for h in res.path)


def test_seed_entity_also_works():
    w, f = _codex()
    res = w.assemble(target_record=f["r_dec"].record_id, seed_entity=f["smith"].entity_id)
    assert res.reached and any(h.kind == "link" for h in res.path)


# --- grounding-faithfulness: only cited edges are walkable --------------------
def _link_to_isolated(f, evidence):
    """Wire an isolated record reachable from the gold record ONLY through one link with `evidence`."""
    isolated = _rec("44444444-4444-4444-4444-444444444444", "Some unrelated note", [])
    f["rs"].insert(isolated)
    f["ls"].insert(Link(record_a=f["r_gold"].record_id, record_b=isolated.record_id, relation="related",
                        tier="interpretation", evidence=evidence, provenance_validation={}))
    return isolated


def test_empty_evidence_link_is_not_walkable():
    w, f = _codex()
    iso = _link_to_isolated(f, {})                          # empty dict — falsy, caught
    assert w.assemble(target_record=iso.record_id, seed_chunk=SEED_CHUNK).reached is False


def test_spanless_nonempty_evidence_link_is_not_walkable():
    # THE STEP-9 REVIEW HIGH: a non-empty but SPAN-LESS evidence dict ({"note": ...}) must NOT be walkable —
    # truthiness is not grounding; only the code-sliced a_span/b_span pair is. It cannot smuggle a path.
    w, f = _codex()
    iso = _link_to_isolated(f, {"note": "adjudicator hunch, no span"})
    assert w.assemble(target_record=iso.record_id, seed_chunk=SEED_CHUNK).reached is False


def test_whitespace_evidence_span_is_not_a_citation():
    # THE STEP-9 REVIEW MED: a whitespace-only evidence_span is blank, not grounded — it seeds no hop.
    rs, es, ls = FakeRecordStore(), FakeEntityStore(), FakeLinkStore()
    e = Entity(entity_type="actor", canonical="Ghost"); es.insert(e)
    rs.insert(_rec("55555555-5555-5555-5555-555555555555", "   ", [_ref(e.entity_id, "Ghost")]))
    w = CodexWalk(record_store=rs, entity_store=es, link_store=ls)
    assert w.entities_of_chunk("55555555-5555-5555-5555-555555555555") == []
    assert w.records_for_entity(e.entity_id) == []


def test_hop_cited_is_kind_specific_and_span_aware():
    # link hop: needs the a_span/b_span pair; record hop: needs a non-blank span; no cross-kind smuggling.
    assert Hop("link", "reverses", "a", "b", {"evidence": {"a_span": [0, 1], "b_span": [2, 3]}}).cited is True
    assert Hop("link", "reverses", "a", "b", {"evidence": {"note": "x"}}).cited is False
    assert Hop("link", "reverses", "a", "b", {"evidence": {}, "evidence_span": "smuggled"}).cited is False
    assert Hop("mentions", None, "c", "e", {"evidence_span": "B. Smith"}).cited is True
    assert Hop("mentions", None, "c", "e", {"evidence_span": "   "}).cited is False


def test_unreachable_target_not_reached():
    w, f = _codex()
    res = w.assemble(target_record="99999999-9999-9999-9999-999999999999", seed_chunk=SEED_CHUNK)
    assert res.reached is False and res.path == []


def test_max_hops_bounds_walk():
    # r_dec is a 3-hop path (mentions -> cites -> link). A tight bound stops short; a wider one reaches.
    w, f = _codex()
    assert w.assemble(target_record=f["r_dec"].record_id, seed_chunk=SEED_CHUNK, max_hops=2).reached is False
    assert w.assemble(target_record=f["r_dec"].record_id, seed_chunk=SEED_CHUNK, max_hops=3).reached is True


# --- cited primitive hops -----------------------------------------------------
def test_entities_of_chunk_hops_are_cited():
    w, f = _codex()
    hops = w.entities_of_chunk(SEED_CHUNK)
    assert hops and all(h.kind == "mentions" and h.cited for h in hops)
    assert any(h.dst == f["smith"].entity_id for h in hops)


def test_neighbors_only_returns_grounded_links():
    w, f = _codex()
    # add a span-less link off the gold record — neighbors() must exclude it (not just empty ones)
    f["ls"].insert(Link(record_a=f["r_gold"].record_id, record_b=f["r_seed"].record_id, relation="hunch",
                        tier="interpretation", evidence={"note": "x"}, provenance_validation={}))
    hops = w.neighbors(f["r_gold"].record_id)
    assert {h.relation for h in hops} == {"reverses", "occurred_on"} and all(h.cited for h in hops)


def test_records_by_chunk_store_api():
    _, f = _codex()
    recs = f["rs"].records_by_chunk(SEED_CHUNK)
    assert [r.record_id for r in recs] == [f["r_seed"].record_id]


def test_link_hop_surfaces_flagged_for_provenance():
    # a judge-FLAGGED link is grounded + walkable, but the assembled path must SHOW it was flagged
    # (provenance-first per-hop confidence) — step-9 review LOW.
    w, f = _codex()
    f["ls"].insert(Link(record_a=f["r_gold"].record_id, record_b=f["r_seed"].record_id, relation="cf",
                        tier="interpretation", evidence={"a_span": [0, 4], "b_span": [0, 4]},
                        provenance_validation={"verdict": "partial"}, flagged=True))
    flags = {h.relation: h.citation["flagged"] for h in w.neighbors(f["r_gold"].record_id)}
    assert flags["cf"] is True and flags["reverses"] is False


def test_links_for_record_is_deterministic_by_link_id():
    # link reads are ordered by link_id (fake==prod), so neighbors() / the walked path are reproducible.
    _, f = _codex()
    ids = [l.link_id for l in f["ls"].links_for_record(f["r_gold"].record_id)]
    assert ids == sorted(ids)
