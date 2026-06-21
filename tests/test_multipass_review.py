from __future__ import annotations

"""Unit test for the codex enriched-data review renderer (over a fake results dir, no DB)."""

import json

from reliquary_enrichment.multipass.review import render_review

C = "89503c71-5ca2-424b-9386-6698a8337dc3"


def _state(outputs):
    return {"outputs": outputs}


def test_render_review_surfaces_original_codex_meaning_and_progression(tmp_path):
    (tmp_path / "inputs.json").write_text(json.dumps({C: {"text": "B. Smith reversed the approval.", "source": "slice"}}))
    (tmp_path / "1_prose.json").write_text(json.dumps(_state({C: {"label": "prose"}})))
    (tmp_path / "2_objecttypes.json").write_text(json.dumps(_state({C: {"object_types": ["actor", "date"]}})))
    (tmp_path / "3_fillvalues.json").write_text(json.dumps(_state(
        {C: {"grounded": True, "record_ids": ["r1"], "attempts": 2, "confidence_trajectory": [0.7, 0.9]}})))
    (tmp_path / "2_9_normalize.json").write_text(json.dumps(_state(
        {"final": {"e-smith": {"type": "actor", "canonical": "B. Smith", "surfaces": ["B. Smith"]}},
         "mapping": {"B. Smith": "e-smith"}})))
    (tmp_path / "discriminative_weight.json").write_text(json.dumps(_state(
        {"themes": ["the claim"], "weights": {}, "theme_cutoff": 2})))
    (tmp_path / "cross_chunk_link.json").write_text(json.dumps(_state({"n_links": 1, "links": []})))
    (tmp_path / "5_meaning.json").write_text(json.dumps(_state({C: {"ok": True, "flagged": False, "reason_code": None}})))
    (tmp_path / "records.jsonl").write_text(json.dumps({
        "source_chunk_id": C, "record_type": "actor", "actor": "B. Smith",
        "event_date": "2025-02-18", "fields": {},
        "evidence_span": "B. Smith reversed the approval",
        "entity_refs": [{"entity_type": "actor", "canonical": "B. Smith"}],
        "provenance_validation": {"verdict": "grounded"}}) + "\n")
    (tmp_path / "meaning.jsonl").write_text(json.dumps({
        "source_chunk_id": C, "claim_meaning": "B. Smith reversed the prior approval"}) + "\n")

    md = render_review(tmp_path)
    assert "Enriched-data review (codex)" in md
    assert "B. Smith reversed the approval." in md            # ORIGINAL
    assert "B. Smith reversed the prior approval" in md       # stored meaning
    assert "themes:** 1" in md and "the claim" in md          # codex themes summary
    assert "cross-chunk links:** 1" in md                     # links summary
    assert "B. Smith reversed the approval'" in md            # grounded record evidence
    assert "actor:B. Smith" in md                             # entity ref surfaced on the record
    assert "progression" in md and "confidence=[0.7, 0.9]" in md


def test_render_review_handles_ungrounded_and_unstored_meaning(tmp_path):
    (tmp_path / "inputs.json").write_text(json.dumps({C: {"text": "noise", "source": "pdf:x"}}))
    (tmp_path / "3_fillvalues.json").write_text(json.dumps(_state(
        {C: {"grounded": False, "reason_code": "ungrounded_fact", "attempts": 3, "confidence_trajectory": [0.4, 0.41]}})))
    (tmp_path / "5_meaning.json").write_text(json.dumps(_state({C: {"ok": False, "reason_code": "non_discriminative"}})))
    md = render_review(tmp_path)              # most pass files absent -> must not crash
    assert "_not grounded_" in md and "ungrounded_fact" in md
    assert "_not stored_" in md and "non_discriminative" in md
