from __future__ import annotations

"""Acceptance tests for the typed proposal validators in multipass/parsing.py (brief §5.2, §10.1).

Two validators sit upstream of grounding and NEVER raise (reject-to-None, preserving the
degrade-one-chunk-not-the-run floor):
  - validate_entity_proposal: rejects off-closed-vocab types / missing quote / missing surface.
  - validate_link_proposal: ADVISORY ON RELATION — accepts ANY non-empty relation, FLAGS off-seed
    (emergent=True), and rejects ONLY on structural shape failure. It must never be stricter than
    link_events.py's accept-unknown-relations boundary (which stays untouched).
"""

from reliquary_enrichment.multipass.parsing import (
    EntityProposal,
    LinkProposal,
    validate_entity_proposal,
    validate_link_proposal,
)

# --- entity proposal -------------------------------------------------------

def test_entity_valid_in_vocab_accepted():
    p = validate_entity_proposal({"type": "date", "quote": "on 2025-02-18", "surface": "2025-02-18"})
    assert isinstance(p, EntityProposal)
    assert (p.type, p.quote, p.surface) == ("date", "on 2025-02-18", "2025-02-18")


def test_entity_off_vocab_type_rejected():
    assert validate_entity_proposal({"type": "frobnicate", "quote": "x", "surface": "y"}) is None


def test_entity_missing_or_empty_quote_rejected():
    assert validate_entity_proposal({"type": "actor", "surface": "B. Smith"}) is None
    assert validate_entity_proposal({"type": "actor", "quote": "", "surface": "B. Smith"}) is None


def test_entity_missing_surface_rejected():
    assert validate_entity_proposal({"type": "actor", "quote": "B. Smith said"}) is None


def test_entity_non_dict_rejected_never_raises():
    for junk in (None, [], "nope", 7, {"type": 5, "quote": "q", "surface": "s"}):
        assert validate_entity_proposal(junk) is None


def test_entity_carries_optional_fields_and_confidence():
    p = validate_entity_proposal(
        {"type": "code", "quote": "F06.4", "surface": "F06.4",
         "fields": {"system": "ICD-10"}, "tier": "fact", "confidence": 0.9}
    )
    assert p.fields == {"system": "ICD-10"} and p.tier == "fact" and p.confidence == 0.9


# --- link proposal ---------------------------------------------------------

def _link(relation):
    return {"record_a": "ra", "record_b": "rb", "relation": relation,
            "a_span": "span a", "b_span": "span b", "rationale": "because"}


def test_link_seed_relation_accepted_not_emergent():
    p = validate_link_proposal(_link("precedes"))
    assert isinstance(p, LinkProposal)
    assert p.relation == "precedes" and p.emergent is False


def test_link_off_seed_relation_FLAGGED_not_rejected():
    # the §10.1 acceptance: off-seed relation is FLAGGED (emergent=True), NOT rejected.
    p = validate_link_proposal(_link("undermines"))
    assert isinstance(p, LinkProposal)
    assert p.relation == "undermines" and p.emergent is True


def test_link_structural_shape_failure_rejected():
    for missing in ("record_a", "record_b", "a_span", "b_span", "rationale"):
        bad = _link("precedes")
        del bad[missing]
        assert validate_link_proposal(bad) is None, missing


def test_link_empty_relation_rejected_structural():
    assert validate_link_proposal(_link("")) is None
    assert validate_link_proposal(_link("   ")) is None


def test_link_non_dict_rejected_never_raises():
    for junk in (None, [], "nope", 7):
        assert validate_link_proposal(junk) is None


def test_link_spans_are_verbatim_not_stripped():
    # a_span/b_span are the verbatim quotes the model points to — must NOT be mutated.
    p = validate_link_proposal({**_link("causes"), "a_span": "  leading space"})
    assert p.a_span == "  leading space"
