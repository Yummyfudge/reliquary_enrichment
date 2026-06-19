from __future__ import annotations

"""GATE — per-chunk faithfulness (judge-side). One of the two SEPARATE readings.

v0: faithfulness = did Pass 3 produce a GROUNDED record for the chunk? Pass 3's fill-values are
gated by the fixed judge inside write_enrichment, so the grounding verdict IS the faithfulness
signal — no extra LLM calls. A chunk that grounded is faithful; one that bounced / plateaued
without grounding is not. (Later: layer per-pass faithfulness checks for passes 1/2/5; v0 keys on
the load-bearing fill-values gate.) This is kept strictly separate from the NEEDLE (findability).
"""

from dataclasses import asdict, dataclass, field

from reliquary_enrichment.multipass.pass_base import PassResult


@dataclass
class GateReading:
    chunks_total: int
    chunks_grounded: int
    chunks_ungrounded: int
    faithfulness_rate: float
    per_chunk: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def read_gate(results: dict[str, PassResult]) -> GateReading:
    """Read per-chunk faithfulness from Pass 3's grounding outcomes."""
    p3 = results.get("3_fillvalues")
    outputs = p3.outputs if p3 else {}
    per_chunk = {
        cid: {
            "grounded": bool(o.get("grounded")),
            "reason_code": o.get("reason_code"),
            "attempts": o.get("attempts"),
            "best_confidence": o.get("best_confidence"),
        }
        for cid, o in outputs.items()
    }
    total = len(per_chunk)
    grounded = sum(1 for o in per_chunk.values() if o["grounded"])
    return GateReading(
        chunks_total=total,
        chunks_grounded=grounded,
        chunks_ungrounded=total - grounded,
        faithfulness_rate=round(grounded / total, 4) if total else 0.0,
        per_chunk=per_chunk,
    )
