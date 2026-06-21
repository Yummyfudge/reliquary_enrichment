from __future__ import annotations

"""Gold-note FLOOR — the hard regression gate, ENTITY-LEVEL (brief §10.2, corrected by FLAG-7).

Runs FIRST, before any other acceptance. The gold chunk (89503c71) must ground, ON ITS OWN TEXT:
  (1) a B. Smith ACTOR entity, AND
  (2) the reversal content ("Mental Health limitation" / "place claim back").
These may be on SEPARATE records (record_type = entity_type). The reversal DATE is NOT a floor
requirement — the gold chunk is UNDATED in-text; the reversal date (pinned 2024-02-18, ambiguous across
2023/24/25 in the corpus) is a SOFT, linked/metadata entity, not grounded-on-this-chunk. If the floor
fails, STOP: the continuity anchor across baselines is gone.
"""

GOLD_CHUNK_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"
_REVERSAL_MARKERS = ("mental health limitation", "place claim back")


def _norm_ws(s: str | None) -> str:
    """Lowercase + collapse internal whitespace so an OCR line-wrap ('place  claim\\n back') still matches
    a single-spaced marker — the floor is the continuity anchor and must be robust to corpus spacing."""
    return " ".join((s or "").lower().split())


def check_gold_floor(records: list) -> dict:
    """Evaluate the floor over the gold chunk's grounded records. Returns the verdict + the two signals."""
    has_b_smith_actor = any(
        ref.entity_type == "actor" and "b. smith" in _norm_ws(ref.canonical)
        for r in records for ref in r.entity_refs
    )
    has_reversal = any(
        any(marker in _norm_ws(r.evidence_span) for marker in _REVERSAL_MARKERS)
        for r in records
    )
    return {
        "passed": bool(has_b_smith_actor and has_reversal),
        "has_b_smith_actor": has_b_smith_actor,
        "has_reversal": has_reversal,
        "gold_records": len(records),
    }


def gold_floor_from_results(record_store, results, *, gold_chunk_id: str = GOLD_CHUNK_ID) -> dict:
    """Resolve the gold chunk's grounded records (from Pass 3's record_ids) and check the floor."""
    p3 = results.get("3_fillvalues")
    rec_ids = (p3.outputs.get(gold_chunk_id) or {}).get("record_ids", []) if p3 else []
    records = [rec for rid in rec_ids if (rec := record_store.get(rid)) is not None]
    return check_gold_floor(records)
