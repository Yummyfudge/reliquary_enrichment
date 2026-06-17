from __future__ import annotations

"""Unit tests for probe scoring — smoking-gun, cross-context, rate math (no DB)."""

import pytest

from reliquary_enrichment.probe.runner import Attempt, RunLog
from reliquary_enrichment.probe.scoring import (
    GOLD_CHUNK_ID,
    cross_context_entities,
    score_from_data,
    smoking_gun,
)

OTHER = "22222222-2222-2222-2222-222222222222"


def _rec(chunk, verdict="grounded", *, actor=None, fields=None, span="", flagged=False, refs=None, rid="r"):
    return {
        "record_id": rid, "source_chunk_id": chunk, "actor": actor,
        "event_date": None, "evidence_span": span, "fields": fields or {},
        "claim_relevance": None, "flagged": flagged,
        "provenance_validation": {"verdict": verdict}, "entity_refs": refs or [],
    }


# --- smoking gun ---------------------------------------------------------------------
def test_smoking_gun_positive():
    rec = _rec(GOLD_CHUNK_ID, actor="B. Smith",
               span="B. Smith reversed the long COVID removal back to Mental Health limitation")
    hit, detail = smoking_gun([rec])
    assert hit is True and detail["signals"]["reversal_direction"] and detail["signals"]["condition_swap"]


@pytest.mark.parametrize("span", [
    "B. Smith reverted the long COVID removal to a Mental Health limitation",        # reverted
    "Smith placed the claim back to the Mental Health limitation",                   # placed...back to
    "Smith reinstated the Mental Health limitation after the long COVID removal",    # reinstated
    "Smith overturned the long COVID removal, Mental Health limitation restored",    # overturned/restored
])
def test_smoking_gun_broadened_reversal_synonyms_no_false_negative(span):
    # The decider must FIRE on a reversal phrased without the literal "revers" (no false-negative).
    hit, detail = smoking_gun([_rec(GOLD_CHUNK_ID, actor="Smith", span=span)])
    assert hit is True and detail["signals"]["reversal_direction"] is not None


def test_smoking_gun_no_reversal_term_is_negative():
    # actor + condition present but NO undo/restore direction -> not the reversal -> no hit.
    assert smoking_gun([_rec(GOLD_CHUNK_ID, actor="B. Smith",
                             span="B. Smith reviewed the long COVID Mental Health limitation")])[0] is False


def test_smoking_gun_requires_grounded():
    rec = _rec(GOLD_CHUNK_ID, verdict="partial", actor="B. Smith",
               span="B. Smith reversed long COVID to Mental Health limitation")
    assert smoking_gun([rec])[0] is False


def test_smoking_gun_wrong_chunk_or_missing_signal():
    assert smoking_gun([_rec(OTHER, actor="B. Smith", span="reversed long covid mental health")])[0] is False
    assert smoking_gun([_rec(GOLD_CHUNK_ID, actor="B. Smith", span="approved the claim")])[0] is False


# --- cross-context -------------------------------------------------------------------
def test_cross_context_counts_entities_spanning_chunks():
    e_actor = [{"entity_id": "E-smith", "role": "actor", "entity_type": "actor", "canonical": "B. Smith"}]
    e_date = [{"entity_id": "E-date", "role": "event_date", "entity_type": "date", "canonical": "2025-02-18"}]
    records = [
        _rec(GOLD_CHUNK_ID, refs=e_actor + e_date, rid="a"),
        _rec(OTHER, refs=e_actor, rid="b"),          # B. Smith appears on a 2nd chunk -> cross-context
    ]
    assert cross_context_entities(records) == 1     # only E-smith spans 2 chunks


# --- rate math + throughput ----------------------------------------------------------
def test_score_from_data_rates_and_throughput():
    log = RunLog(label="t", candidate_model="m", schema="probe_t", chunk_ids=["c1", "c2"],
                 attempts=[
                     Attempt("c1", "rt", "fact", located=True, ok=True, record_id="r1"),
                     Attempt("c1", "rt", "fact", located=True, ok=False, reason_code="ungrounded_fact"),
                     Attempt("c2", "rt", "fact", located=False, ok=False, reason_code="locate_miss"),
                 ],
                 chunks_seen=2, chunks_missing=0, started_at=0.0, finished_at=60.0)
    records = [_rec(GOLD_CHUNK_ID, rid="r1")]
    card = score_from_data(log, records)
    assert card.n_proposals == 3 and card.n_located == 2 and card.n_locate_miss == 1
    assert card.n_records == 1 and card.n_grounded == 1
    assert card.grounding_pass_rate == 0.5          # 1 grounded / 2 reached judge
    assert round(card.end_to_end_yield, 4) == round(1 / 3, 4)
    assert card.chunks_per_min == 2.0 and card.records_per_min == 1.0


def test_score_surfaces_coverage_recall():
    # F3: 5 chunks seen, but only 2 drew proposals -> 3 empty (the recall gap).
    log = RunLog(label="t", candidate_model="m", schema="probe_t", chunk_ids=["c"] * 5,
                 attempts=[
                     Attempt("c1", "rt", "fact", located=True, ok=True),
                     Attempt("c1", "rt", "fact", located=True, ok=True),
                     Attempt("c2", "rt", "fact", located=True, ok=True),
                 ],
                 chunks_seen=5, chunks_missing=0, started_at=0.0, finished_at=60.0)
    card = score_from_data(log, [_rec(GOLD_CHUNK_ID, rid=f"r{i}") for i in range(3)])
    assert card.chunks_with_proposals == 2 and card.chunks_empty == 3
