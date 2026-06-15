from __future__ import annotations

"""Standalone tests for the shared grounding-core — the heart, tested first (brief §3.2).

Every branch of the corruption-proof boundary is exercised with a fake judge + in-memory
Fragments (no DB, no network). These guard the invariant: the model points, code copies,
the judge checks, the row attests.
"""

import pytest

from reliquary_enrichment.grounding.core import (
    GroundingCore,
    build_record_judge_messages,
    sha256_text,
)
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import parse_judge_json
from reliquary_enrichment.grounding.types import (
    GroundingError,
    JudgeResult,
    ReasonCode,
    Tier,
    Verdict,
)
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge

GOLD_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"
GOLD_TEXT = "Supervisor B. Smith reversed the prior approval on 2025-02-18."
WS = "ws-test"


def make_core(*, judge=None, fragments=None, handle_map=None):
    reader = FakeFragmentReader(fragments or {GOLD_ID: Fragment(GOLD_ID, GOLD_TEXT, "denial.pdf", 7)})
    return (
        GroundingCore(
            fragment_reader=reader,
            handle_map=handle_map or HandleMap(),
            judge=judge or ConstantJudge(Verdict.GROUNDED),
        ),
        reader,
    )


# --- Steps 1-2: resolve + load -------------------------------------------------------

def test_resolve_via_handle():
    hm = HandleMap()
    handle = hm.mint(WS, GOLD_ID)
    core, _ = make_core(handle_map=hm)
    frag = core.resolve_fragment(WS, chunk_handle=handle)
    assert frag.chunk_id == GOLD_ID and frag.text == GOLD_TEXT


def test_resolve_per_fragment_current_mode():
    hm = HandleMap()
    hm.set_current(WS, GOLD_ID)
    core, _ = make_core(handle_map=hm)
    frag = core.resolve_fragment(WS)  # no chunk ref at all (Pass 2)
    assert frag.chunk_id == GOLD_ID


def test_resolve_raw_id_mode():
    core, _ = make_core()
    assert core.resolve_fragment(WS, chunk_id=GOLD_ID).chunk_id == GOLD_ID


def test_unknown_handle_rejects():
    core, _ = make_core()
    with pytest.raises(GroundingError) as e:
        core.resolve_fragment(WS, chunk_handle="F9")
    assert e.value.reason_code is ReasonCode.UNKNOWN_FRAGMENT


def test_no_reference_at_all_rejects():
    core, _ = make_core()
    with pytest.raises(GroundingError) as e:
        core.resolve_fragment(WS)
    assert e.value.reason_code is ReasonCode.UNKNOWN_FRAGMENT


def test_handle_resolves_but_fragment_missing():
    hm = HandleMap()
    hm.mint(WS, "deadbeef-0000-0000-0000-000000000000")  # minted but not in the reader
    core, _ = make_core(handle_map=hm)
    with pytest.raises(GroundingError) as e:
        core.resolve_fragment(WS, chunk_handle="F1")
    assert e.value.reason_code is ReasonCode.FRAGMENT_NOT_FOUND


def test_echoed_chunk_id_crosscheck_mismatch_rejects():
    # Test #2 spirit: an echoed id that disagrees with the handle signals corruption.
    hm = HandleMap()
    handle = hm.mint(WS, GOLD_ID)
    core, _ = make_core(handle_map=hm)
    with pytest.raises(GroundingError) as e:
        core.resolve_fragment(WS, chunk_handle=handle, chunk_id="89503c71-MANGLED")
    assert e.value.reason_code is ReasonCode.UNKNOWN_FRAGMENT


# --- Steps 3-4: bounds + code-slice --------------------------------------------------

def test_slice_is_byte_exact():
    core, _ = make_core()
    frag = Fragment(GOLD_ID, GOLD_TEXT)
    assert core.slice_span(frag, 0, 28) == GOLD_TEXT[0:28]


@pytest.mark.parametrize("start,end", [(-1, 5), (5, 5), (10, 5), (0, len(GOLD_TEXT) + 1)])
def test_bad_offsets_reject(start, end):
    core, _ = make_core()
    with pytest.raises(GroundingError) as e:
        core.slice_span(Fragment(GOLD_ID, GOLD_TEXT), start, end)
    assert e.value.reason_code is ReasonCode.BAD_OFFSETS


def test_whitespace_span_rejects_empty():
    core, _ = make_core()
    frag = Fragment(GOLD_ID, "abc    def")
    with pytest.raises(GroundingError) as e:
        core.slice_span(frag, 3, 6)  # "   "
    assert e.value.reason_code is ReasonCode.EMPTY_SPAN


# --- Step 5: the judge sees the code-sliced span, never model prose ------------------

def test_judge_record_prompt_carries_the_slice():
    judge = ConstantJudge(Verdict.GROUNDED)
    core, _ = make_core(judge=judge)
    span = "Supervisor B. Smith reversed"
    core.judge_record(Tier.FACT, "B. Smith reversed the approval", span)
    system, user = judge.calls[-1]
    assert span in user and "TIER=fact" in user


def test_record_prompt_builder_tier_aware():
    _, user_fact = build_record_judge_messages(Tier.FACT, "c", "s")
    _, user_interp = build_record_judge_messages(Tier.INTERPRETATION, "c", "s")
    assert "every asserted value" in user_fact.lower()
    assert "reasonable inference" in user_interp.lower()


# --- Step 6: the strict-core / soft-rest tier gate -----------------------------------

REC = dict(fact_reason=ReasonCode.UNGROUNDED_FACT, interp_reason=ReasonCode.UNSUPPORTED_INTERPRETATION)


def test_gate_grounded_accepts_unflagged():
    out = GroundingCore.gate(Tier.FACT, JudgeResult(Verdict.GROUNDED), **REC)
    assert out.flagged is False


def test_gate_fact_partial_rejects():
    with pytest.raises(GroundingError) as e:
        GroundingCore.gate(Tier.FACT, JudgeResult(Verdict.PARTIAL, ["event_date"]), **REC)
    assert e.value.reason_code is ReasonCode.UNGROUNDED_FACT


def test_gate_interpretation_partial_flags_not_rejects():
    out = GroundingCore.gate(Tier.INTERPRETATION, JudgeResult(Verdict.PARTIAL), **REC)
    assert out.flagged is True


def test_gate_fact_ungrounded_rejects_ungrounded_fact():
    with pytest.raises(GroundingError) as e:
        GroundingCore.gate(Tier.FACT, JudgeResult(Verdict.UNGROUNDED, ["event_date"]), **REC)
    assert e.value.reason_code is ReasonCode.UNGROUNDED_FACT
    assert "event_date" in e.value.detail


def test_gate_interpretation_ungrounded_rejects_unsupported():
    with pytest.raises(GroundingError) as e:
        GroundingCore.gate(Tier.INTERPRETATION, JudgeResult(Verdict.UNGROUNDED), **REC)
    assert e.value.reason_code is ReasonCode.UNSUPPORTED_INTERPRETATION


def test_gate_link_uses_relation_reason_for_both_tiers():
    LINK = dict(fact_reason=ReasonCode.UNGROUNDED_RELATION, interp_reason=ReasonCode.UNGROUNDED_RELATION)
    with pytest.raises(GroundingError) as e:
        GroundingCore.gate(Tier.FACT, JudgeResult(Verdict.UNGROUNDED), **LINK)
    assert e.value.reason_code is ReasonCode.UNGROUNDED_RELATION


# --- Attestation + hashing -----------------------------------------------------------

def test_sha256_matches_hashlib():
    import hashlib
    assert sha256_text(GOLD_TEXT) == hashlib.sha256(GOLD_TEXT.encode()).hexdigest()


def test_build_attestation_freezes_identity_and_hashes():
    judge = ConstantJudge(Verdict.PARTIAL, failing_values=["x"])
    core, _ = make_core(judge=judge)
    att = core.build_attestation(
        JudgeResult(Verdict.PARTIAL, ["x"]),
        hashes={"evidence_sha256": "a", "source_sha256": "b"},
    )
    assert att["verdict"] == "partial"
    assert att["judge_model"] == "judge" and att["judge_version"] == "fake-1"
    assert att["evidence_sha256"] == "a" and att["source_sha256"] == "b"
    assert att["failing_values"] == ["x"]
    assert "validated_at" in att


# --- Defensive judge parsing: fail CLOSED --------------------------------------------

def test_parse_bare_json():
    r = parse_judge_json('{"verdict":"grounded","failing_values":[],"reason":"ok"}')
    assert r.verdict is Verdict.GROUNDED


def test_parse_embedded_json():
    r = parse_judge_json('Sure! {"verdict":"ungrounded","failing_values":["d"]} done')
    assert r.verdict is Verdict.UNGROUNDED and r.failing_values == ["d"]


def test_parse_garbage_fails_closed():
    with pytest.raises(GroundingError) as e:
        parse_judge_json("the span looks fine to me")
    assert e.value.reason_code is ReasonCode.JUDGE_UNAVAILABLE


def test_parse_unknown_verdict_fails_closed():
    with pytest.raises(GroundingError) as e:
        parse_judge_json('{"verdict":"probably"}')
    assert e.value.reason_code is ReasonCode.JUDGE_UNAVAILABLE


def test_parse_coerces_nonlist_failing_values():
    r = parse_judge_json('{"verdict":"partial","failing_values":"event_date"}')
    assert r.failing_values == ["event_date"]
