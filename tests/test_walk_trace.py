from __future__ import annotations

"""Gold-target walk trace over EXPORTED codex jsonl (build 10b artifact generator)."""

import json
from pathlib import Path

from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID
from reliquary_enrichment.multipass.walk_trace import build_codex_from_exports, gold_walk_trace

SEED_CHUNK = "11111111-1111-1111-1111-111111111111"
DEC_CHUNK = "33333333-3333-3333-3333-333333333333"
SMITH = "e-smith"


def _write_exports(tmp: Path):
    def rec(rid, chunk, span, refs, actor=None):
        return {"record_id": rid, "source_chunk_id": chunk, "record_type": "actor", "tier": "interpretation",
                "char_start": 0, "char_end": len(span), "evidence_span": span, "actor": actor,
                "event_date": None, "fields": {}, "provenance_validation": {"verdict": "grounded"},
                "verdict": "grounded", "entity_refs": refs, "page": 1, "document": "c.pdf"}
    smith_ref = [{"role": "actor", "entity_id": SMITH, "entity_type": "actor", "canonical": "B. Smith"}]
    records = [
        rec("r-gold", GOLD_CHUNK_ID, "manager B. Smith: place claim back to a Mental Health limitation", smith_ref, "B. Smith"),
        rec("r-seed", SEED_CHUNK, "reviewed with B. Smith", smith_ref, "B. Smith"),
        rec("r-dec", DEC_CHUNK, "claim denied under the exclusion", []),
    ]
    entities = [{"entity_id": SMITH, "entity_type": "actor", "canonical": "B. Smith", "aliases": [],
                 "metadata": {"is_theme": False}, "first_seen_record": "r-gold", "flagged": False}]
    links = [{"link_id": "l-1", "record_a": "r-gold", "record_b": "r-dec", "relation": "reverses",
              "tier": "interpretation", "evidence": {"a_span": [0, 7], "b_span": [0, 5]}, "confidence": None,
              "provenance_validation": {"verdict": "grounded"}, "event_entity": None, "flagged": False}]
    (tmp / "records.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    (tmp / "entities.jsonl").write_text("\n".join(json.dumps(e) for e in entities) + "\n")
    (tmp / "links.jsonl").write_text("\n".join(json.dumps(l) for l in links) + "\n")


def test_build_codex_from_exports_round_trips(tmp_path):
    _write_exports(tmp_path)
    rs, es, ls = build_codex_from_exports(tmp_path)
    assert {r.record_id for r in rs.records_by_chunk(GOLD_CHUNK_ID)} == {"r-gold"}
    assert {r.record_id for r in rs.records_by_entity(SMITH)} == {"r-gold", "r-seed"}
    assert ls.links_for_record("r-gold")[0].relation == "reverses"
    assert es.get(SMITH).canonical == "B. Smith"


def test_gold_walk_trace_reaches_and_reports_link_neighbours(tmp_path):
    _write_exports(tmp_path)
    trace = gold_walk_trace(tmp_path)
    assert trace["target_record"] == "r-gold" and trace["seed_chunk"] == SEED_CHUNK
    assert trace["reached"] is True and trace["every_hop_cited"] is True
    # the §8d required edge formed and is a grounded, cited, walkable neighbour of the gold record
    neigh = trace["gold_link_neighbours"]
    assert any(h["relation"] == "reverses" and h["cited"] for h in neigh)


def test_gold_walk_trace_handles_missing_gold(tmp_path):
    (tmp_path / "records.jsonl").write_text("")     # empty codex -> no crash, reached False
    (tmp_path / "entities.jsonl").write_text("")
    (tmp_path / "links.jsonl").write_text("")
    trace = gold_walk_trace(tmp_path)
    assert trace["reached"] is False and "reason" in trace
