from __future__ import annotations

"""Acceptance tests for write_enrichment — contract write_enrichment.md §9.

These ARE the acceptance criteria (TDD). Each test states what it proves. The judge is a
fake so verdicts are deterministic; the invariant logic (resolve/slice/gate/attest/entity)
is what is under test. The live judge is exercised separately (test_judge_integration.py).
"""

import hashlib

import pytest

from reliquary_enrichment.entities import EntityResolver
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import JudgeResult, Verdict
from reliquary_enrichment.write_enrichment import WriteEnrichment
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge, ScriptedJudge
from tests.fakes.fake_stores import FakeEntityStore, FakeRecordStore

GOLD_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"
GOLD_TEXT = "Supervisor B. Smith reversed the prior approval on 2025-02-18."
WS = "ws-1"


def build(*, judge=None, fragments=None):
    reader = FakeFragmentReader(
        fragments or {GOLD_ID: Fragment(GOLD_ID, GOLD_TEXT, "denial.pdf", 7, "status_change")}
    )
    hm = HandleMap()
    handle = hm.mint(WS, GOLD_ID)
    records = FakeRecordStore()
    entities = FakeEntityStore()
    core = GroundingCore(
        fragment_reader=reader, handle_map=hm, judge=judge or ConstantJudge(Verdict.GROUNDED)
    )
    tool = WriteEnrichment(
        core=core, record_store=records, entity_resolver=EntityResolver(entities)
    )
    return tool, handle, records, entities, reader


def base_payload(handle, **over):
    p = {
        "chunk_handle": handle,
        "char_start": 0,
        "char_end": 28,  # "Supervisor B. Smith reversed"
        "record_type": "status_change",
        "tier": "fact",
        "fields": {"change": "approval reversed"},
        "actor": "B. Smith",
        "event_date": "2025-02-18",
    }
    p.update(over)
    return p


# 1. Happy path -----------------------------------------------------------------------
def test_happy_path_writes_byte_exact_span_and_canonical_id():
    tool, handle, records, _, _ = build()
    out = tool.write(base_payload(handle), workstream_id=WS)
    assert out["ok"] is True
    assert out["source_chunk_id"] == GOLD_ID                  # canonical, code-resolved
    assert out["evidence_span"] == GOLD_TEXT[0:28]            # byte-exact from corpus
    stored = records.records[out["record_id"]]
    assert stored.evidence_span == GOLD_TEXT[0:28]
    assert stored.page == 7 and stored.document == "denial.pdf"  # provenance code-derived


# 2. 🔴 The 89503 regression ----------------------------------------------------------
def test_89503_mangled_handle_never_stores_corrupted_id():
    tool, handle, records, _, _ = build()
    out = tool.write(base_payload(handle, chunk_handle="F7-MANGLED"), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "unknown_fragment"
    assert records.records == {}                              # nothing stored


def test_89503_echoed_chunk_id_mismatch_bounced():
    tool, handle, records, _, _ = build()
    out = tool.write(
        base_payload(handle, chunk_id="89503c71-WRONG"), workstream_id=WS
    )
    assert out["ok"] is False and out["reason_code"] == "unknown_fragment"
    assert records.records == {}


# 3. Date-drift -----------------------------------------------------------------------
def test_date_drift_rejected_ungrounded_fact():
    judge = ConstantJudge(Verdict.UNGROUNDED, failing_values=["event_date"])
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(base_payload(handle, event_date="2025-02-19"), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "ungrounded_fact"
    assert "event_date" in out["detail"]
    assert records.records == {}


# 4. Word-drift -----------------------------------------------------------------------
def test_word_drift_rejected():
    judge = ConstantJudge(Verdict.UNGROUNDED, failing_values=["change"])
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(
        base_payload(handle, fields={"change": "approval is reversible"}), workstream_id=WS
    )
    assert out["ok"] is False and out["reason_code"] == "ungrounded_fact"


# 5. Bad offsets — no judge call, no write --------------------------------------------
def test_bad_offsets_no_judge_no_write():
    judge = ConstantJudge(Verdict.GROUNDED)
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(base_payload(handle, char_end=10_000), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "bad_offsets"
    assert judge.calls == []                                  # short-circuited before the judge
    assert records.records == {}


# 6. Fabrication ----------------------------------------------------------------------
def test_fabricated_field_rejected():
    judge = ConstantJudge(Verdict.UNGROUNDED, failing_values=["denial_code"])
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(
        base_payload(handle, fields={"denial_code": "X-999"}), workstream_id=WS
    )
    assert out["ok"] is False and out["reason_code"] == "ungrounded_fact"


# 7. Interpretation tier --------------------------------------------------------------
def test_interpretation_grounded_but_not_literal_is_stored():
    judge = ConstantJudge(Verdict.GROUNDED)
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(
        base_payload(
            handle, tier="interpretation",
            claim_relevance="the reversal undercuts the stated denial rationale",
        ),
        workstream_id=WS,
    )
    assert out["ok"] is True
    assert records.records[out["record_id"]].tier == "interpretation"


def test_interpretation_contradiction_bounced():
    judge = ConstantJudge(Verdict.UNGROUNDED)
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(
        base_payload(handle, tier="interpretation", claim_relevance="the claim was never reversed"),
        workstream_id=WS,
    )
    assert out["ok"] is False and out["reason_code"] == "unsupported_interpretation"


def test_interpretation_partial_is_flagged_not_bounced():
    judge = ConstantJudge(Verdict.PARTIAL)
    tool, handle, records, _, _ = build(judge=judge)
    out = tool.write(base_payload(handle, tier="interpretation"), workstream_id=WS)
    assert out["ok"] is True and out["flagged"] is True


# 8. Span is code-sliced (payload-supplied span is refused) ---------------------------
def test_payload_evidence_span_is_refused_as_schema_invalid():
    tool, handle, records, _, _ = build()
    out = tool.write(
        base_payload(handle, evidence_span="totally different text"), workstream_id=WS
    )
    assert out["ok"] is False and out["reason_code"] == "schema_invalid"
    assert records.records == {}


# 9. 🔒 Provenance Validation integrity ----------------------------------------------
def test_provenance_validation_hashes_match_stored_bytes():
    tool, handle, records, _, _ = build()
    out = tool.write(base_payload(handle), workstream_id=WS)
    pv = out["provenance_validation"]
    assert pv["evidence_sha256"] == hashlib.sha256(out["evidence_span"].encode()).hexdigest()
    assert pv["source_sha256"] == hashlib.sha256(GOLD_TEXT.encode()).hexdigest()
    assert pv["judge_model"] == "judge" and "validated_at" in pv


def test_tampering_source_is_detectable_on_audit():
    tool, handle, records, _, reader = build()
    out = tool.write(base_payload(handle), workstream_id=WS)
    frozen = out["provenance_validation"]["source_sha256"]
    # Mutate the source Fragment AFTER the fact (simulating corpus tampering).
    reader.add(Fragment(GOLD_ID, GOLD_TEXT + " (tampered)", "denial.pdf", 7))
    now = hashlib.sha256(reader.get(GOLD_ID).text.encode()).hexdigest()
    assert now != frozen                                     # mismatch -> detectable


# 10. Entity resolution ---------------------------------------------------------------
def test_entities_created_then_deduped_across_records():
    tool, handle, records, entities, _ = build()
    out1 = tool.write(base_payload(handle), workstream_id=WS)
    out2 = tool.write(base_payload(handle, fields={"change": "again"}), workstream_id=WS)
    # Two records, but one actor Entity and one date Entity (deduped on canonical).
    assert len(records.records) == 2
    actor_entities = [e for e in entities.entities.values() if e.entity_type == "actor"]
    date_entities = [e for e in entities.entities.values() if e.entity_type == "date"]
    assert len(actor_entities) == 1 and len(date_entities) == 1
    # Both records point at the same Entity ids.
    refs1 = {r.entity_type: r.entity_id for r in records.records[out1["record_id"]].entity_refs}
    refs2 = {r.entity_type: r.entity_id for r in records.records[out2["record_id"]].entity_refs}
    assert refs1 == refs2
    assert records.records[out1["record_id"]].entity_refs[0].entity_type == "actor"


def test_entity_alias_recorded_on_variant_surface_form():
    tool, handle, records, entities, _ = build()
    tool.write(base_payload(handle), workstream_id=WS)                      # "B. Smith"
    tool.write(base_payload(handle, actor="B. Smith  "), workstream_id=WS)  # extra spaces -> same canonical
    actor = next(e for e in entities.entities.values() if e.entity_type == "actor")
    assert actor.canonical == "B. Smith"
    assert "B. Smith  " in actor.aliases


# schema validation -------------------------------------------------------------------
def test_judged_claim_excludes_record_type_includes_values():
    # Regression: record_type must NOT be in the grounded claim (it's a label, not a value
    # the span must literally contain). Surfaced by the extraction probe vs the real judge.
    from reliquary_enrichment.write_enrichment import _validate, render_record_claim
    claim = render_record_claim(_validate(base_payload("F1", actor="B. Smith", event_date="2025-02-18")))
    assert "record_type" not in claim
    assert "B. Smith" in claim and "2025-02-18" in claim


@pytest.mark.parametrize("bad", [
    {"tier": "guess"},
    {"record_type": ""},
    {"char_start": "0"},
    {"confidence": 1.5},
])
def test_schema_invalid_rejections(bad):
    tool, handle, records, _, _ = build()
    out = tool.write(base_payload(handle, **bad), workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "schema_invalid"
    assert records.records == {}
