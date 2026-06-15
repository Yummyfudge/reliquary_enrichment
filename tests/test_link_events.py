from __future__ import annotations

"""Acceptance tests for link_events — contract codex.md §8.

The Link write boundary inherits write_enrichment's discipline. Judge is faked for
deterministic verdicts; event materialization + transitive merge are the load-bearing
logic under test.
"""

import hashlib

from reliquary_enrichment.entities import EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.models import EnrichmentRecord
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge
from tests.fakes.fake_stores import FakeEntityStore, FakeLinkStore, FakeRecordStore

WS = "ws-link"
# Two Fragments on different pages; their texts ground a temporal/causal relation.
FRAG_A = Fragment("aaaa1111-0000-0000-0000-000000000000",
                  "On 2025-02-10 the initial claim was approved by the adjuster.", "f.pdf", 3)
FRAG_B = Fragment("bbbb2222-0000-0000-0000-000000000000",
                  "Supervisor B. Smith reversed the prior approval on 2025-02-18.", "f.pdf", 7)
FRAG_C = Fragment("cccc3333-0000-0000-0000-000000000000",
                  "The reversal was logged in the audit trail on 2025-02-18.", "f.pdf", 9)


def build(*, judge=None, extra_records=None):
    reader = FakeFragmentReader({f.chunk_id: f for f in (FRAG_A, FRAG_B, FRAG_C)})
    records = FakeRecordStore()
    entities = FakeEntityStore()
    links = FakeLinkStore()
    # seed two real Enrichment Records pointing at FRAG_A and FRAG_B.
    rec_a = EnrichmentRecord("status_change", "fact", FRAG_A.chunk_id, 0, 10, "On 2025-02",
                             {"v": "grounded"})
    rec_b = EnrichmentRecord("status_change", "fact", FRAG_B.chunk_id, 0, 28, "Supervisor B. Smith",
                             {"v": "grounded"})
    records.insert(rec_a)
    records.insert(rec_b)
    for r in (extra_records or []):
        records.insert(r)
    core = GroundingCore(
        fragment_reader=reader, handle_map=HandleMap(),
        judge=judge or ConstantJudge(Verdict.GROUNDED),
    )
    tool = LinkEvents(
        core=core, record_store=records, link_store=links,
        event_materializer=EventMaterializer(entities),
    )
    return tool, records, links, entities, rec_a, rec_b


def payload(rec_a, rec_b, **over):
    p = {
        "record_a": rec_a.record_id,
        "record_b": rec_b.record_id,
        "relation": "results_from",
        "tier": "interpretation",
        "evidence": {"a_span": [0, 28], "b_span": [0, 28]},
        "rationale": "the reversal follows from the earlier approval",
    }
    p.update(over)
    return p


# 1. Happy path -----------------------------------------------------------------------
def test_happy_path_writes_link_with_both_span_hashes():
    tool, _, links, _, rec_a, rec_b = build()
    out = tool.link(payload(rec_a, rec_b), workstream_id=WS)
    assert out["ok"] is True
    link = links.links[out["link_id"]]
    pv = out["provenance_validation"]
    # both evidence spans hashed, byte-exact from each Fragment.
    assert pv["a_evidence_sha256"] == hashlib.sha256(FRAG_A.text[0:28].encode()).hexdigest()
    assert pv["b_evidence_sha256"] == hashlib.sha256(FRAG_B.text[0:28].encode()).hexdigest()
    assert link.relation == "results_from"


# 2. 🔴 Corrupted record ref ----------------------------------------------------------
def test_mangled_record_ref_rejected_unknown_record():
    tool, _, links, _, rec_a, rec_b = build()
    out = tool.link(payload(rec_a, rec_b, record_b="bbbb2222-MANGLED"), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "unknown_record"
    assert links.links == {}


# 3. Ungrounded relation --------------------------------------------------------------
def test_ungrounded_relation_bounced():
    tool, _, links, _, rec_a, rec_b = build(judge=ConstantJudge(Verdict.UNGROUNDED))
    out = tool.link(payload(rec_a, rec_b), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "ungrounded_relation"
    assert links.links == {}


# 4. Contradiction tiering ------------------------------------------------------------
def test_contradicts_grounded_is_written_distinct_from_corroborates():
    tool, _, links, _, rec_a, rec_b = build(judge=ConstantJudge(Verdict.GROUNDED))
    out = tool.link(payload(rec_a, rec_b, relation="contradicts", tier="fact"), workstream_id=WS)
    assert out["ok"] is True
    assert links.links[out["link_id"]].relation == "contradicts"


def test_fact_relation_partial_is_bounced():
    # strict core: a fact-tier relation that is only partial does not get written.
    tool, _, links, _, rec_a, rec_b = build(judge=ConstantJudge(Verdict.PARTIAL))
    out = tool.link(payload(rec_a, rec_b, relation="precedes", tier="fact"), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "ungrounded_relation"


# 5. same_event materialization (+ transitive merge) ----------------------------------
def test_same_event_materializes_one_event_and_merges_transitively():
    rec_c = EnrichmentRecord("status_change", "fact", FRAG_C.chunk_id, 0, 20, "The reversal",
                             {"v": "grounded"})
    tool, _, links, entities, rec_a, rec_b = build(extra_records=[rec_c])

    # A ~ B  -> one event {A, B}
    out1 = tool.link(payload(rec_a, rec_b, relation="same_event", tier="fact"), workstream_id=WS)
    # B ~ C  -> C joins the SAME event {A, B, C} (no new event)
    out2 = tool.link(payload(rec_b, rec_c, relation="same_event", tier="fact"), workstream_id=WS)

    assert out1["event_entity"] == out2["event_entity"]
    live_events = [e for e in entities.entities.values()
                   if e.entity_type == "event" and not e.metadata.get("merged_into")]
    assert len(live_events) == 1
    assert set(live_events[0].metadata["member_records"]) == {
        rec_a.record_id, rec_b.record_id, rec_c.record_id
    }


def test_two_clusters_then_bridge_merges_to_one_event():
    rec_c = EnrichmentRecord("status_change", "fact", FRAG_C.chunk_id, 0, 20, "x", {"v": "g"})
    rec_d = EnrichmentRecord("status_change", "fact", FRAG_A.chunk_id, 0, 10, "y", {"v": "g"})
    tool, _, _, entities, rec_a, rec_b = build(extra_records=[rec_c, rec_d])
    # cluster 1: A~B ; cluster 2: C~D ; then bridge B~C -> all four merge
    tool.link(payload(rec_a, rec_b, relation="same_event", tier="fact"), workstream_id=WS)
    tool.link(payload(rec_c, rec_d, relation="same_event", tier="fact"), workstream_id=WS)
    tool.link(payload(rec_b, rec_c, relation="same_event", tier="fact"), workstream_id=WS)
    live = [e for e in entities.entities.values()
            if e.entity_type == "event" and not e.metadata.get("merged_into")]
    assert len(live) == 1
    assert set(live[0].metadata["member_records"]) == {
        rec_a.record_id, rec_b.record_id, rec_c.record_id, rec_d.record_id
    }


# 6. Entity dedupe — covered by write_enrichment tests; here ensure same_event reuses, no dup
def test_repeated_same_event_pair_does_not_duplicate_event():
    tool, _, _, entities, rec_a, rec_b = build()
    tool.link(payload(rec_a, rec_b, relation="same_event", tier="fact"), workstream_id=WS)
    tool.link(payload(rec_a, rec_b, relation="same_event", tier="fact"), workstream_id=WS)
    live = [e for e in entities.entities.values()
            if e.entity_type == "event" and not e.metadata.get("merged_into")]
    assert len(live) == 1


# 7. provenance_validation integrity --------------------------------------------------
def test_tampering_either_source_is_detectable():
    tool, _, links, _, rec_a, rec_b = build()
    out = tool.link(payload(rec_a, rec_b), workstream_id=WS)
    pv = out["provenance_validation"]
    assert pv["a_source_sha256"] == hashlib.sha256(FRAG_A.text.encode()).hexdigest()
    assert pv["b_source_sha256"] == hashlib.sha256(FRAG_B.text.encode()).hexdigest()
    # mutating either source later no longer matches the frozen hash
    assert hashlib.sha256((FRAG_B.text + " x").encode()).hexdigest() != pv["b_source_sha256"]


# 8. Combinatorial guard --------------------------------------------------------------
def test_one_call_writes_exactly_one_link():
    tool, _, links, _, rec_a, rec_b = build()
    tool.link(payload(rec_a, rec_b), workstream_id=WS)
    assert len(links.links) == 1            # never an all-pairs fan-out


# bad offsets on a cited span ---------------------------------------------------------
def test_link_bad_offsets_rejected():
    tool, _, links, _, rec_a, rec_b = build()
    out = tool.link(
        payload(rec_a, rec_b, evidence={"a_span": [0, 9999], "b_span": [0, 10]}),
        workstream_id=WS,
    )
    assert out["ok"] is False and out["reason_code"] == "bad_offsets"
    assert links.links == {}
