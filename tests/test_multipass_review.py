from __future__ import annotations

"""Unit test for the enriched-data review renderer (over a fake results dir, no DB)."""

import json

from reliquary_enrichment.multipass.review import render_review

C = "89503c71-5ca2-424b-9386-6698a8337dc3"


def _state(outputs):
    return {"outputs": outputs}


def test_render_review_surfaces_original_enriched_and_progression(tmp_path):
    (tmp_path / "inputs.json").write_text(json.dumps({C: {"text": "B. Smith reversed the approval.", "source": "slice"}}))
    (tmp_path / "1_prose.json").write_text(json.dumps(_state({C: {"label": "prose"}})))
    (tmp_path / "2_objecttypes.json").write_text(json.dumps(_state({C: {"object_types": ["status_change", "actor"]}})))
    (tmp_path / "2_9_consolidate.json").write_text(json.dumps(_state(
        {"final": ["status_change", "actor"], "mapping": {"status_change": "status_change", "actor": "actor"}})))
    (tmp_path / "3_fillvalues.json").write_text(json.dumps(_state(
        {C: {"grounded": True, "record_id": "r1", "attempts": 2, "confidence_trajectory": [0.7, 0.9]}})))
    (tmp_path / "4_9_cleanup.json").write_text(json.dumps(_state({"final": ["reversal"], "cleaned": {C: ["reversal"]}})))
    (tmp_path / "5_meaning.json").write_text(json.dumps(_state({C: {"claim_meaning": "the approval was reversed", "questions_answered": ["was it reversed?"]}})))
    (tmp_path / "records.jsonl").write_text(json.dumps({
        "source_chunk_id": C, "record_type": "status_change", "actor": "B. Smith",
        "event_date": "2025-02-18", "fields": {"change": "reversal"},
        "evidence_span": "B. Smith reversed the approval",
        "provenance_validation": {"verdict": "grounded"}}) + "\n")

    md = render_review(tmp_path)
    assert "Enriched-data review" in md
    assert "B. Smith reversed the approval." in md            # ORIGINAL
    assert "the approval was reversed" in md                  # meaning
    assert "status_change" in md and "reversal" in md         # types + keywords
    assert "B. Smith reversed the approval'" in md            # grounded record evidence
    assert "progression" in md                                # per-pass progression
    assert "confidence=[0.7, 0.9]" in md                      # trajectory shown


def test_render_review_handles_ungrounded_and_missing(tmp_path):
    (tmp_path / "inputs.json").write_text(json.dumps({C: {"text": "noise", "source": "pdf:x"}}))
    (tmp_path / "3_fillvalues.json").write_text(json.dumps(_state(
        {C: {"grounded": False, "reason_code": "ungrounded_fact", "attempts": 3, "confidence_trajectory": [0.4, 0.41, 0.42]}})))
    md = render_review(tmp_path)              # most pass files absent -> must not crash
    assert "_not grounded_" in md and "ungrounded_fact" in md
