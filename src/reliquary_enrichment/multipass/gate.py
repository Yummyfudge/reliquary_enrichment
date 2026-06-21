from __future__ import annotations

"""GATE — per-chunk coverage (judge-side). One of the two SEPARATE readings; MEASURES, never rejects.

Coverage = DISCRIMINATIVE SUBSTANCE (brief §5.2): a chunk counts only when a grounded record carries a
NON-THEME typed entity (a date/actor/code/etc. that isn't a ubiquitous theme). A grounded-but-trivial
record — e.g. a grounded "Cheers, Joe" sign-off, or a record carrying only the theme "the claim" — does
NOT count. Pass 3's records are judge-gated inside write_enrichment, so this adds no LLM calls; it just
intersects the grounded records with the theme-flag (step 6). When the entity/record stores aren't wired
yet it falls back to v0 (grounded-anything). Kept strictly separate from the NEEDLE (findability) and
from MeaningWriter's HARD discriminativeness gate (§5.4 #7, which REJECTS — this only measures).
"""

from dataclasses import asdict, dataclass, field

from reliquary_enrichment.multipass.pass_base import PassResult


def _has_discriminative_substance(out: dict, record_store, entity_store) -> bool:
    """True iff a grounded record of the chunk carries a NON-THEME typed entity (discriminative
    substance) — not just ubiquitous themes / a trivial grounded span."""
    for rid in out.get("record_ids", []):
        record = record_store.get(rid)
        if record is None:
            continue
        for ref in record.entity_refs:
            entity = entity_store.get(ref.entity_id)
            if entity is not None and not entity.metadata.get("is_theme", False):
                return True
    return False


@dataclass
class GateReading:
    chunks_total: int
    chunks_grounded: int
    chunks_ungrounded: int
    faithfulness_rate: float
    per_chunk: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def read_gate(results: dict[str, PassResult], *, record_store=None, entity_store=None) -> GateReading:
    """Read per-chunk coverage from Pass 3's grounding outcomes.

    When ``record_store`` and ``entity_store`` are both provided (post step-9 wiring), coverage is
    DISCRIMINATIVE SUBSTANCE (a grounded record carrying a non-theme typed entity); otherwise it falls
    back to v0 grounded-anything. ``chunks_grounded`` is the covered count (GateReading shape kept).
    """
    p3 = results.get("3_fillvalues")
    outputs = p3.outputs if p3 else {}
    discriminative = record_store is not None and entity_store is not None
    per_chunk = {}
    for cid, o in outputs.items():
        o = o or {}                              # measure, never crash on a missing/None output
        grounded = bool(o.get("grounded"))
        covered = _has_discriminative_substance(o, record_store, entity_store) if discriminative else grounded
        per_chunk[cid] = {
            "grounded": grounded,
            "covered": covered,
            "reason_code": o.get("reason_code"),
            "attempts": o.get("attempts"),
            "best_confidence": o.get("best_confidence"),
        }
    total = len(per_chunk)
    covered = sum(1 for o in per_chunk.values() if o["covered"])
    return GateReading(
        chunks_total=total,
        chunks_grounded=covered,                 # covered count (discriminative substance when wired)
        chunks_ungrounded=total - covered,
        faithfulness_rate=round(covered / total, 4) if total else 0.0,
        per_chunk=per_chunk,
    )
