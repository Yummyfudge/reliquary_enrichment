from __future__ import annotations

"""Acceptance tests for multipass/vocabulary.py — the closed taxonomy (brief §5.4 #1, §10).

vocabulary.py is the SINGLE SOURCE OF TRUTH for the entity taxonomy and the seed relation
vocabulary. ENTITY_TYPES is the 002+006 enum (7 types); SEED_RELATIONS is a literal RE-EXPORT
of link_events.SEED_RELATIONS (not a retyped copy) so the advisory link validator can never
drift from the grounding boundary it feeds. len(ENTITY_TYPES) == 7 is the sprawl-regression
bound (§10.2).
"""

from reliquary_enrichment import link_events
from reliquary_enrichment.multipass import vocabulary


def test_entity_types_is_the_closed_seven():
    assert vocabulary.ENTITY_TYPES == frozenset(
        {"actor", "date", "event", "document", "provision", "code", "location"}
    )


def test_entity_types_is_a_frozenset():
    assert isinstance(vocabulary.ENTITY_TYPES, frozenset)


def test_entity_types_sprawl_bound_is_seven():
    # §10.2 sprawl-regression bound: distinct entity types must never exceed this.
    assert len(vocabulary.ENTITY_TYPES) == 7


def test_location_is_present():
    # the 006 / probe-DDL addition — the 7th type that 002 shipped without.
    assert "location" in vocabulary.ENTITY_TYPES


def test_seed_relations_is_a_literal_reexport_not_a_copy():
    # MUST be the SAME object as link_events.SEED_RELATIONS (re-export, single source of truth),
    # so a relation added to link_events automatically reaches the advisory validator.
    assert vocabulary.SEED_RELATIONS is link_events.SEED_RELATIONS


def test_seed_relations_has_the_nine_seed_members():
    assert vocabulary.SEED_RELATIONS == frozenset({
        "precedes", "follows", "causes", "results_from",
        "corroborates", "contradicts", "elaborates", "same_event", "references",
    })
