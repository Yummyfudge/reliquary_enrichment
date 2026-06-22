from __future__ import annotations

"""Defensive JSON extraction + typed proposal validators — never raise on bad model output.

`safe_json_array`/`safe_json_object` are the never-raise floor (both the direct parse AND the
regex-extracted fallback are guarded — the unguarded fallback is what crashed the first scout
run). On top of them sit two typed validators (brief §5.2) that also reject-to-None, never raise:

  - `validate_entity_proposal` — closed-vocab shape gate: type ∈ ``vocabulary.ENTITY_TYPES``, a
    verbatim ``quote``, a canonical ``surface``.
  - `validate_link_proposal` — ADVISORY ON RELATION (matches `link_events.py`'s accept-unknown
    contract): accepts ANY non-empty relation, FLAGS off-seed (``emergent=True``), and rejects
    ONLY on structural shape failure. It is strictly upstream/advisory — never stricter than the
    grounding boundary it feeds, so `link_events.py` stays untouched.

A single malformed reply degrades that one chunk, not the whole run.
"""

import json
import re
from dataclasses import dataclass, field

from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES, SEED_RELATIONS


def safe_json_array(raw: str) -> list:
    """Parse a JSON array from text; return [] on anything unparseable (incl. the fallback)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        if not m:
            return []
        try:
            value = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def safe_json_object(raw: str) -> dict | None:
    """Parse a JSON object from text; return None on anything unparseable (incl. the fallback)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not m:
            return None
        try:
            value = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


# --- typed proposal validators (brief §5.2) -------------------------------------------------

@dataclass(frozen=True, slots=True)
class EntityProposal:
    """A proposed typed-entity record: a closed-vocab type, a verbatim quote to ground, the
    canonical surface/value, plus optional asserted fields/tier/confidence carried forward."""

    type: str
    quote: str
    surface: str
    fields: dict = field(default_factory=dict)
    tier: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class LinkProposal:
    """A proposed cross-record link: two real record ids, a relation (any non-empty string),
    a verbatim span in each record, and a rationale. ``emergent`` flags an off-seed relation
    (advisory only — accepted, never rejected, per link_events.py's contract)."""

    record_a: str
    record_b: str
    relation: str
    a_span: str
    b_span: str
    rationale: str
    emergent: bool = False


def _nonempty_str(v: object) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_entity_proposal(obj: object) -> EntityProposal | None:
    """Validate a typed-entity proposal dict; reject-to-None on shape failure (never raises).

    Requires: ``type`` ∈ ``ENTITY_TYPES``, a non-empty verbatim ``quote``, a non-empty
    canonical ``surface``. Optional ``fields``/``tier``/``confidence`` pass through.
    """
    if not isinstance(obj, dict):
        return None
    t = obj.get("type")
    if not _nonempty_str(t):
        return None
    t = t.strip()
    if t not in ENTITY_TYPES:
        return None
    quote, surface = obj.get("quote"), obj.get("surface")
    if not _nonempty_str(quote) or not _nonempty_str(surface):
        return None
    raw_fields = obj.get("fields")
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    tier = obj.get("tier").strip() if _nonempty_str(obj.get("tier")) else None
    raw_conf = obj.get("confidence")
    confidence = float(raw_conf) if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool) else None
    return EntityProposal(type=t, quote=quote, surface=surface, fields=fields, tier=tier, confidence=confidence)


def validate_link_proposal(obj: object) -> LinkProposal | None:
    """Validate a cross-record link proposal; reject-to-None ONLY on structural shape failure.

    ADVISORY ON RELATION (matches link_events.py lines 26-31): any non-empty ``relation`` is
    accepted; ``emergent`` is set when it is not in ``SEED_RELATIONS``. NEVER rejects on relation
    vocabulary — that would be stricter than the grounding boundary it feeds. Never raises.
    Structural requirements: ``record_a``/``record_b``/``a_span``/``b_span``/``rationale`` non-empty
    strings, and a non-empty ``relation``. Spans are kept VERBATIM (the model points; code copies).
    """
    if not isinstance(obj, dict):
        return None
    ra, rb = obj.get("record_a"), obj.get("record_b")
    a_span, b_span = obj.get("a_span"), obj.get("b_span")
    rationale, relation = obj.get("rationale"), obj.get("relation")
    if not all(_nonempty_str(v) for v in (ra, rb, a_span, b_span, rationale, relation)):
        return None
    relation = relation.strip()
    return LinkProposal(
        record_a=ra.strip(), record_b=rb.strip(), relation=relation,
        a_span=a_span, b_span=b_span, rationale=rationale,
        emergent=relation not in SEED_RELATIONS,
    )
