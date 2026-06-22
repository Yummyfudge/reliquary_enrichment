from __future__ import annotations

"""Acceptance tests for CrossChunkLinkPass + the gold-note FLOOR (brief §8, §10.2, build step 7).

The pass where the thesis is proven: wire the safety-critical LinkEvents into the connective layer. The
scrutiny points: candidate-explosion BOUNDED (stoplist + fan-out cap), same_event PRECISION (same-actor /
different-dates negative), shared_themes CAPTURED-but-never-acted, both grounding classes, the named gold
required edge, and the entity-level floor.
"""

from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef
from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID, check_gold_floor, gold_floor_from_results
from reliquary_enrichment.multipass.pass_base import ChunkRef, PassContext, PassResult
from reliquary_enrichment.multipass.passes.pass_link import (
    CrossChunkLinkPass,
    generate_candidates,
    same_event_allowed,
)
from tests.fakes.fake_stores import FakeEntityStore, FakeRecordStore


def _ent(eid, etype, canon, theme=False):
    return Entity(entity_type=etype, canonical=canon, metadata={"is_theme": theme}, entity_id=eid)


def _rec(rid, chunk, refs, span="span", start=0, end=4, date=None):
    er = [EntityRef(*r) for r in refs]
    if date:
        er.append(EntityRef("event_date", f"d-{date}", "date", date))
    return EnrichmentRecord(
        record_type="x", tier="fact", source_chunk_id=chunk, char_start=start, char_end=end,
        evidence_span=span, provenance_validation={}, entity_refs=er, record_id=rid)


class FakeLinker:
    def __init__(self):
        self.calls = []

    def link(self, payload, *, workstream_id):
        self.calls.append(payload)
        return {"ok": True, "link_id": f"l{len(self.calls)}", "relation": payload["relation"]}


def _store_with(entities, records):
    es, rs = FakeEntityStore(), FakeRecordStore()
    for e in entities:
        es.insert(e)
    for r in records:
        rs.insert(r)
    return es, rs


def _ctx(rs, es, linker, propose):
    return PassContext(model=None, model_name="f", extras={
        "record_store": rs, "entity_store": es, "linker": linker, "link_proposer": propose})


# --- (a) candidate-gen BOUNDED + STOPLIST ------------------------------------
def test_candidate_gen_stoplists_themes_anchors_only_non_themes():
    theme = _ent("th", "event", "the claim", theme=True)
    rare = _ent("rr", "actor", "B. Smith")
    es, rs = _store_with([theme, rare], [
        _rec("r1", "c1", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "the claim")]),
        _rec("r2", "c2", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "the claim")]),
        _rec("r3", "c3", [("event", "th", "event", "the claim")]),   # ONLY the theme -> no candidate
    ])
    cands, dry = generate_candidates(rs, es, fan_out_cap=8)
    pairs = {tuple(sorted((c["record_a"], c["record_b"]))) for c in cands}
    assert pairs == {("r1", "r2")}                          # anchored on B. Smith; the theme anchors NOTHING
    assert dry["candidate_pairs"] == 1 and "the claim" in dry["stoplisted_anchors"]


def test_candidate_gen_fan_out_capped():
    e = _ent("e", "code", "F06.4")
    recs = [_rec(f"r{i}", f"c{i}", [("code", "e", "code", "F06.4")]) for i in range(6)]
    es, rs = _store_with([e], recs)
    _, dry = generate_candidates(rs, es, fan_out_cap=3)
    assert dry["per_anchor_fanout"]["F06.4"] == 3 and dry["candidate_pairs"] == 3   # not C(6,2)=15


def test_candidate_gen_global_K_ceiling():
    # many non-theme anchors -> the global K cap bounds the TOTAL (not just per-anchor F); reported, not silent.
    ents = [_ent(f"e{k}", "code", f"C{k}") for k in range(20)]
    recs = []
    for k in range(20):
        recs.append(_rec(f"r{k}a", f"c{k}a", [("code", f"e{k}", "code", f"C{k}")]))
        recs.append(_rec(f"r{k}b", f"c{k}b", [("code", f"e{k}", "code", f"C{k}")]))
    es, rs = _store_with(ents, recs)
    cands, dry = generate_candidates(rs, es, fan_out_cap=8, max_candidates=5)
    assert len(cands) == 5 and dry["candidate_pairs"] == 5 and dry["capped"] is True


# --- (d) shared_themes CAPTURED but NEVER drives candidacy -------------------
def test_shared_themes_captured_but_does_not_influence_candidacy():
    rare = _ent("rr", "actor", "B. Smith")
    theme = _ent("th", "event", "Long COVID", theme=True)
    es, rs = _store_with([rare, theme], [
        _rec("r1", "c1", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "Long COVID")]),
        _rec("r2", "c2", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "Long COVID")]),
    ])
    cands, _ = generate_candidates(rs, es, fan_out_cap=8)
    assert len(cands) == 1 and cands[0]["shared_themes"] == ["Long COVID"]

    # GUARDRAIL: drop the shared theme entirely -> the SAME candidate (same pair + anchor) still forms.
    es2, rs2 = _store_with([rare], [
        _rec("r1", "c1", [("actor", "rr", "actor", "B. Smith")]),
        _rec("r2", "c2", [("actor", "rr", "actor", "B. Smith")]),
    ])
    cands2, _ = generate_candidates(rs2, es2, fan_out_cap=8)
    assert len(cands2) == 1 and cands2[0]["shared_themes"] == []
    assert ((cands[0]["record_a"], cands[0]["record_b"], cands[0]["anchor"])
            == (cands2[0]["record_a"], cands2[0]["record_b"], cands2[0]["anchor"]))


def test_link_pass_emits_candidate_heartbeat():
    # the long process_all pass must PULSE (candidate i/N) via ctx.extras["emit"] so it never reads as a
    # hang — the 10b "wedge" was actually a silent-but-working Pass 6 (deadlines firing, no heartbeat).
    rare = _ent("rr", "actor", "B. Smith")
    es, rs = _store_with([rare], [
        _rec("r1", "c1", [("actor", "rr", "actor", "B. Smith")]),
        _rec("r2", "c2", [("actor", "rr", "actor", "B. Smith")]),
    ])
    lines: list[str] = []
    ctx = PassContext(model=None, model_name="f", extras={
        "record_store": rs, "entity_store": es, "linker": FakeLinker(),
        "link_proposer": lambda *a: {}, "emit": lines.append})
    CrossChunkLinkPass().process_all([ChunkRef("c1", "B. Smith"), ChunkRef("c2", "B. Smith")], {}, ctx)
    assert any("candidate pairs" in l for l in lines)             # start line (total + bounds)
    assert any("Link pass | candidate" in l for l in lines)       # per-candidate pulse


# --- (c) same_event PRECISION guard -----------------------------------------
def test_same_event_guard_same_actor_different_dates_blocked():
    a = _rec("ra", "c1", [("actor", "s", "actor", "B. Smith")], date="2024-02-18")
    b = _rec("rb", "c2", [("actor", "s", "actor", "B. Smith")], date="2024-03-04")
    assert same_event_allowed(a, b) is False                # different dates -> distinct occurrences
    same_date = _rec("rc", "c3", [("actor", "s", "actor", "B. Smith")], date="2024-02-18")
    undated = _rec("rd", "c4", [("actor", "s", "actor", "B. Smith")])
    assert same_event_allowed(a, same_date) is True and same_event_allowed(a, undated) is True


# --- (b) the pass: BOTH grounding classes + the guard firing through link() ---
def test_pass_grounds_temporal_and_guards_same_event():
    es = FakeEntityStore(); es.insert(_ent("s", "actor", "B. Smith"))
    rs = FakeRecordStore()
    rs.insert(_rec("ra", "c1", [("actor", "s", "actor", "B. Smith")], span="alpha", date="2024-02-18"))
    rs.insert(_rec("rb", "c2", [("actor", "s", "actor", "B. Smith")], span="beta", date="2024-03-04"))
    linker = FakeLinker()

    def propose(ra, rb, ta, tb, anchor):                    # the model proposes same_event...
        return {"record_a": ra.record_id, "record_b": rb.record_id, "relation": "same_event",
                "a_span": "alpha", "b_span": "beta", "rationale": "same"}

    out = CrossChunkLinkPass().process_all(
        [ChunkRef("c1", "alpha text"), ChunkRef("c2", "beta text")], {}, _ctx(rs, es, linker, propose))
    relations = {(link["klass"], link.get("relation"), link["ok"]) for link in out["links"]}
    assert ("temporal", "precedes", True) in relations      # 2024-02-18 precedes 2024-03-04 (code-derived)
    assert ("semantic", "same_event", False) in relations   # ...but the guard blocks it
    assert len(linker.calls) == 1 and linker.calls[0]["relation"] == "precedes"   # never linked the same_event


def test_same_event_guard_is_case_insensitive():
    es = FakeEntityStore(); es.insert(_ent("s", "actor", "B. Smith"))
    rs = FakeRecordStore()
    rs.insert(_rec("ra", "c1", [("actor", "s", "actor", "B. Smith")], span="x", date="2024-02-18"))
    rs.insert(_rec("rb", "c2", [("actor", "s", "actor", "B. Smith")], span="x", date="2024-03-04"))
    linker = FakeLinker()

    def propose(ra, rb, ta, tb, anchor):                    # an UPPERCASE same_event variant...
        return {"record_a": ra.record_id, "record_b": rb.record_id, "relation": "SAME_EVENT",
                "a_span": "x", "b_span": "x", "rationale": "same"}

    out = CrossChunkLinkPass().process_all(
        [ChunkRef("c1", "x text"), ChunkRef("c2", "x text")], {}, _ctx(rs, es, linker, propose))
    sem = [link for link in out["links"] if link["klass"] == "semantic"][0]
    assert sem["ok"] is False and sem["reason_code"] == "same_event_guard"   # ...caught despite case
    assert all(call["relation"] == "precedes" for call in linker.calls)      # only the temporal grounded


def test_pass_grounds_semantic_link_no_dates():
    es = FakeEntityStore(); es.insert(_ent("e", "code", "F06.4"))
    rs = FakeRecordStore()
    rs.insert(_rec("ra", "c1", [("code", "e", "code", "F06.4")], span="F06.4"))
    rs.insert(_rec("rb", "c2", [("code", "e", "code", "F06.4")], span="F06.4"))
    linker = FakeLinker()

    def propose(ra, rb, ta, tb, anchor):
        return {"record_a": ra.record_id, "record_b": rb.record_id, "relation": "corroborates",
                "a_span": "F06.4", "b_span": "F06.4", "rationale": "both cite F06.4"}

    out = CrossChunkLinkPass().process_all(
        [ChunkRef("c1", "diag F06.4 here"), ChunkRef("c2", "also F06.4 present")], {},
        _ctx(rs, es, linker, propose))
    semantic = [link for link in out["links"] if link["klass"] == "semantic"]
    assert semantic and semantic[0]["ok"] and semantic[0]["relation"] == "corroborates"
    assert not any(link["klass"] == "temporal" for link in out["links"])     # no dates -> no temporal


# --- named gold REQUIRED EDGE (§8d) -----------------------------------------
def test_named_required_edge_reversal_to_decision_via_b_smith():
    es = FakeEntityStore(); es.insert(_ent("s", "actor", "B. Smith"))
    rs = FakeRecordStore()
    rs.insert(_rec("rev", GOLD_CHUNK_ID, [("actor", "s", "actor", "B. Smith")], span="reversed"))
    rs.insert(_rec("dec", "c-decision", [("actor", "s", "actor", "B. Smith")], span="approved"))
    linker = FakeLinker()

    def propose(ra, rb, ta, tb, anchor):
        # order-aware (candidate-gen sorts a/b by id): cite a span present in EACH record's chunk.
        return {"record_a": ra.record_id, "record_b": rb.record_id, "relation": "contradicts",
                "a_span": "B. Smith", "b_span": "B. Smith", "rationale": "the reversal undid the approval"}

    out = CrossChunkLinkPass().process_all(
        [ChunkRef(GOLD_CHUNK_ID, "reversed by B. Smith"), ChunkRef("c-decision", "approved by B. Smith")],
        {}, _ctx(rs, es, linker, propose))
    edge = [link for link in out["links"] if link["ok"] and link["klass"] == "semantic"]
    assert edge and edge[0]["anchor"] == "B. Smith" and edge[0]["relation"] == "contradicts"
    assert {edge[0]["record_a"], edge[0]["record_b"]} == {"rev", "dec"}


# --- the gold-note FLOOR -----------------------------------------------------
def test_gold_floor_passes_with_actor_and_reversal_content():
    recs = [
        _rec("r1", GOLD_CHUNK_ID, [("actor", "s", "actor", "B. Smith")], span="manager B. Smith"),
        _rec("r2", GOLD_CHUNK_ID, [], span="Place claim back to a Mental Health limitation"),
    ]
    v = check_gold_floor(recs)
    assert v["passed"] and v["has_b_smith_actor"] and v["has_reversal"]


def test_floor_reversal_marker_is_whitespace_tolerant():
    # OCR line-wrap / extra internal whitespace must NOT false-fail the continuity anchor.
    recs = [
        _rec("r1", GOLD_CHUNK_ID, [("actor", "s", "actor", "B. Smith")], span="manager B. Smith"),
        _rec("r2", GOLD_CHUNK_ID, [], span="Place  claim\n  back  to a  Mental  Health  limitation"),
    ]
    assert check_gold_floor(recs)["passed"] is True


def test_gold_floor_fails_missing_b_smith_or_reversal():
    no_smith = check_gold_floor([_rec("r2", GOLD_CHUNK_ID, [], span="Place claim back to a Mental Health limitation")])
    assert no_smith["passed"] is False and no_smith["has_reversal"] is True and no_smith["has_b_smith_actor"] is False
    no_rev = check_gold_floor([_rec("r1", GOLD_CHUNK_ID, [("actor", "s", "actor", "B. Smith")], span="unrelated text")])
    assert no_rev["passed"] is False and no_rev["has_reversal"] is False


def test_shared_themes_is_PER_LINK_keyed_for_offline_measurement():
    # #9-answerability: each LINK entry carries its OWN record_a/record_b/link_id/shared_themes, so the
    # offline measurement can correlate THIS link's shared themes with THIS link's quality. NOT a global
    # run-level "themes seen" list (which would have the signal but no per-link join).
    rare = _ent("rr", "actor", "B. Smith")
    theme = _ent("th", "event", "Long COVID", theme=True)
    es, rs = _store_with([rare, theme], [
        _rec("r1", "c1", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "Long COVID")]),
        _rec("r2", "c2", [("actor", "rr", "actor", "B. Smith"), ("event", "th", "event", "Long COVID")]),
    ])
    linker = FakeLinker()

    def propose(ra, rb, ta, tb, anchor):
        return {"record_a": ra.record_id, "record_b": rb.record_id, "relation": "corroborates",
                "a_span": "B. Smith", "b_span": "B. Smith", "rationale": "r"}

    out = CrossChunkLinkPass().process_all(
        [ChunkRef("c1", "B. Smith here"), ChunkRef("c2", "B. Smith too")], {}, _ctx(rs, es, linker, propose))
    link = next(link for link in out["links"] if link["ok"])
    assert link["record_a"] and link["record_b"] and link["link_id"]    # per-link join keys
    assert link["shared_themes"] == ["Long COVID"]                       # THIS link's themes
    assert "shared_themes" not in out and "shared_themes" in link        # per-link, NOT a global field


def test_link_proposer_injects_ids_and_parses_defensively():
    from reliquary_enrichment.multipass.link_wiring import make_link_proposer

    class M:
        def complete(self, s, u):
            return '{"relation":"causes","a_span":"x","b_span":"y","rationale":"r"}', 1

    ra, rb = _rec("ra", "c1", []), _rec("rb", "c2", [])
    p = make_link_proposer(M())(ra, rb, "ta", "tb", "F06.4")
    assert p["record_a"] == "ra" and p["record_b"] == "rb"   # CODE owns the ids (model never supplies)
    assert p["relation"] == "causes" and p["a_span"] == "x"

    class Junk:
        def complete(self, s, u):
            return "not json at all", 1

    p2 = make_link_proposer(Junk())(ra, rb, "ta", "tb", "F06.4")
    assert p2["record_a"] == "ra"                            # ids still injected; the empty proposal
    from reliquary_enrichment.multipass.parsing import validate_link_proposal
    assert validate_link_proposal(p2) is None                # ...is then rejected by the validator


def test_gold_floor_from_results_resolves_records():
    rs = FakeRecordStore()
    rs.insert(_rec("r1", GOLD_CHUNK_ID, [("actor", "s", "actor", "B. Smith")], span="manager B. Smith"))
    rs.insert(_rec("r2", GOLD_CHUNK_ID, [], span="place claim back to a mental health limitation"))
    results = {"3_fillvalues": PassResult("3_fillvalues", {GOLD_CHUNK_ID: {"record_ids": ["r1", "r2"]}})}
    assert gold_floor_from_results(rs, results)["passed"]
