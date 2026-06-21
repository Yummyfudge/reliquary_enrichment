from __future__ import annotations

"""Acceptance tests for the discriminative-weight + theme-flag pass (brief §9, build step 6).

THIS IS THE LOAD-BEARING CALIBRATION (Joe): the theme-cutoff must classify the KNOWN entities right,
against their REAL chunk-degrees mined from the frozen 131-chunk slice. The discriminators
(B. Smith 2/131, the gold/reversal date 3/131, F06.4 28/131) must land BELOW the cutoff; the themes
("the claim" 76/131, the claimant 82/131, Long COVID 90/131) must land ABOVE. If the cutoff ever
mis-flagged B. Smith as a theme, the whole CRQ-001 lever would INVERT — so this test guards that.
"""

from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef
from reliquary_enrichment.multipass.discriminative import DiscriminativeWeightPass
from reliquary_enrichment.multipass.gate import read_gate
from reliquary_enrichment.multipass.pass_base import ChunkRef, PassContext, PassResult
from tests.fakes.fake_stores import FakeEntityStore, FakeRecordStore

SLICE_TOTAL = 131
# (canonical -> (entity_type, REAL distinct-chunk degree over the slice))
KNOWN = {
    "B. Smith":   ("actor", 2),     # discriminator
    "2024-02-18": ("date", 3),      # discriminator — the reversal/gold date
    "F06.4":      ("code", 28),     # discriminator (top of the cluster)
    "the claim":  ("event", 76),    # theme (bottom of the cluster)
    "claimant":   ("actor", 82),    # theme
    "Long COVID": ("event", 90),    # theme
}
DISCRIMINATORS = ["B. Smith", "2024-02-18", "F06.4"]
THEMES = ["the claim", "claimant", "Long COVID"]


def _build(degrees):
    es, rs = FakeEntityStore(), FakeRecordStore()
    eid_of = {}
    for canon, (etype, degree) in degrees.items():
        e = Entity(entity_type=etype, canonical=canon)
        es.insert(e)
        eid_of[canon] = e.entity_id
        for i in range(degree):       # `degree` records in `degree` distinct chunks
            rs.insert(EnrichmentRecord(
                record_type=etype, tier="fact", source_chunk_id=f"c{i}", char_start=0, char_end=1,
                evidence_span="x", provenance_validation={},
                entity_refs=[EntityRef(etype, e.entity_id, etype, canon)],
                record_id=f"r-{canon}-{i}"))
    return es, rs, eid_of


def _run(degrees=KNOWN, total=SLICE_TOTAL, fraction=None):
    es, rs, eid_of = _build(degrees)
    chunks = [ChunkRef(f"c{i}", "t") for i in range(total)]
    kw = {} if fraction is None else {"theme_fraction": fraction}
    ctx = PassContext(model=None, model_name="f", extras={"entity_store": es, "record_store": rs})
    out = DiscriminativeWeightPass(**kw).process_all(chunks, {}, ctx)
    return out, es, eid_of


def test_theme_cutoff_calibration_classifies_known_entities():
    out, _, _ = _run()
    cutoff = out["theme_cutoff"]
    assert 28 < cutoff <= 76, f"cutoff {cutoff} must separate F06.4(28) from 'the claim'(76)"
    flags = {w["canonical"]: w["is_theme"] for w in out["weights"].values()}
    for c in DISCRIMINATORS:
        assert flags[c] is False, f"{c} must be a DISCRIMINATOR (below cutoff)"
    for c in THEMES:
        assert flags[c] is True, f"{c} must be a THEME (above cutoff)"
    assert set(out["stoplist"]) == set(THEMES)        # themes form the linking stoplist (§8)


def test_weight_is_distinct_chunk_count():
    out, _, _ = _run()
    w = {x["canonical"]: x["weight"] for x in out["weights"].values()}
    assert w["B. Smith"] == 2 and w["F06.4"] == 28 and w["Long COVID"] == 90


def test_set_entity_flags_persists_weight_and_theme():
    out, es, eid_of = _run()
    smith = es.get(eid_of["B. Smith"])
    assert smith.metadata["weight"] == 2 and smith.metadata["is_theme"] is False
    covid = es.get(eid_of["Long COVID"])
    assert covid.metadata["is_theme"] is True


def test_b_smith_never_inverts_to_theme():
    # the inversion guard: B. Smith (2 chunks) stays a discriminator for any sane theme_fraction.
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.8):
        out, _, _ = _run(fraction=frac)
        flags = {w["canonical"]: w["is_theme"] for w in out["weights"].values()}
        assert flags["B. Smith"] is False, f"B. Smith mis-flagged as theme at fraction {frac}"


def test_calibration_robust_to_low_grounding_rate():
    # The fraction-of-MAX fix: weight is the GROUNDED degree (<= text degree), and the audition grounding
    # rate is ~34-54%. Scaled to ~44% of the text degrees, themes must STILL be themes — a fraction-of-
    # TOTAL cutoff (0.4*131=52) would mis-flag all three themes as discriminators (the inversion the fix
    # prevents); fraction-of-max (0.4*40=16) keeps the classification correct.
    grounded = {
        "B. Smith":   ("actor", 1),
        "2024-02-18": ("date", 1),
        "F06.4":      ("code", 12),
        "the claim":  ("event", 33),
        "claimant":   ("actor", 36),
        "Long COVID": ("event", 40),
    }
    out, _, _ = _run(grounded)
    flags = {w["canonical"]: w["is_theme"] for w in out["weights"].values()}
    for c in DISCRIMINATORS:
        assert flags[c] is False, f"{c} must stay a discriminator at a low grounding rate"
    for c in THEMES:
        assert flags[c] is True, f"{c} must stay a theme at a low grounding rate"


# --- step 6.5: gate = discriminative substance, not grounded-anything ---------

def _rec(rid, chunk, refs):
    return EnrichmentRecord(
        record_type="x", tier="fact", source_chunk_id=chunk, char_start=0, char_end=1,
        evidence_span="x", provenance_validation={},
        entity_refs=[EntityRef(*r) for r in refs], record_id=rid)


def test_gate_counts_discriminative_substance_not_theme_only():
    es = FakeEntityStore()
    theme = Entity(entity_type="event", canonical="the claim", metadata={"is_theme": True})
    rare = Entity(entity_type="actor", canonical="B. Smith", metadata={"is_theme": False})
    es.insert(theme)
    es.insert(rare)
    rs = FakeRecordStore()
    rs.insert(_rec("rA", "cA", [("event", theme.entity_id, "event", "the claim")]))   # theme-only
    rs.insert(_rec("rB", "cB", [("actor", rare.entity_id, "actor", "B. Smith")]))      # rare entity
    results = {"3_fillvalues": PassResult("3_fillvalues", {
        "cA": {"grounded": True, "record_ids": ["rA"]},
        "cB": {"grounded": True, "record_ids": ["rB"]},
    })}
    g = read_gate(results, record_store=rs, entity_store=es)
    assert g.per_chunk["cA"]["covered"] is False      # grounded but theme-only -> NOT substance
    assert g.per_chunk["cB"]["covered"] is True
    assert g.chunks_grounded == 1 and g.faithfulness_rate == 0.5


def test_gate_backcompat_without_stores_is_grounded_anything():
    results = {"3_fillvalues": PassResult("3_fillvalues",
                                          {"c1": {"grounded": True}, "c2": {"grounded": False}})}
    g = read_gate(results)                              # no stores -> v0 behavior preserved
    assert g.chunks_grounded == 1 and g.per_chunk["c1"]["covered"] is True
