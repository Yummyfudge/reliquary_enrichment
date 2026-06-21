from __future__ import annotations

"""Closed vocabulary — the SINGLE SOURCE OF TRUTH for the codex taxonomy (brief §5.4 #1).

`ENTITY_TYPES` is the fixed closed entity taxonomy (the 002 + 006 enum, 7 types). Every pass
and validator imports it from here; `len(ENTITY_TYPES) == 7` is the sprawl-regression bound
(§10.2) that replaces the old open-vocabulary type-merge.

`SEED_RELATIONS` is a literal RE-EXPORT of `link_events.SEED_RELATIONS` (the only definition
site) — NOT a retyped copy. The advisory link validator flags relations not in this set; binding
it to the same object link_events validates against guarantees the advisory layer can never be
stricter than, or drift from, the grounding boundary it feeds (link_events.py stays untouched).
"""

from reliquary_enrichment.link_events import SEED_RELATIONS

# The fixed closed entity taxonomy (codex_entities entity_type enum, 002 + 006 +location).
ENTITY_TYPES: frozenset[str] = frozenset({
    "actor", "date", "event", "document", "provision", "code", "location",
})

__all__ = ["ENTITY_TYPES", "SEED_RELATIONS"]
