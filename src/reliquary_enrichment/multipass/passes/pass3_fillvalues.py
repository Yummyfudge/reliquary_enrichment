from __future__ import annotations

"""Pass 3 — fill-values. Fill the 2.9 schema's types with grounded values, per chunk.

The retry loop, exactly per Joe's rule (separation of concerns):
  * the candidate PROPOSES a value-fill for the chunk (with self-reported confidence);
  * code GROUNDS it via write_enrichment — the JUDGE gates (accept / flag / bounce);
  * on a bounce the judge's FEEDBACK shapes the next retry — but does NOT decide the stop;
  * the CONFIDENCE-PLATEAU owns "keep trying?": stop when a retry fails to beat best-so-far by
    ≥ epsilon. The full per-chunk confidence trajectory is captured (glass box) for ε-tuning.

`proposer` and `grounder` are injected via ctx.extras so the pass is unit-testable with fakes;
the real wiring is ModelClient (propose) + WriteEnrichment over a probe schema (ground).
  proposer(chunk, schema, feedback) -> (proposal: dict{confidence, ...payload}, tokens: int)
  grounder(proposal, chunk)          -> result: dict{ok, record_id, reason_code, detail}
"""

from typing import Any

from reliquary_enrichment.multipass.confidence import ConfidencePlateau
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult


class Pass3FillValues(Pass):
    name = "3_fillvalues"
    per_chunk = True

    def __init__(self, *, epsilon: float = 0.05, max_attempts: int = 25) -> None:
        self.epsilon = epsilon
        self.max_attempts = max_attempts   # belt-and-suspenders; the plateau is the real bound

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        schema = (
            prior["2_9_consolidate"].outputs.get("final", [])
            if "2_9_consolidate" in prior else []
        )
        propose = ctx.extras["proposer"]
        ground = ctx.extras["grounder"]
        plateau = ConfidencePlateau(self.epsilon)
        feedback = None
        tokens = 0
        last: dict | None = None
        grounded = False

        for _ in range(self.max_attempts):
            proposal, toks = propose(chunk, schema, feedback)
            tokens += toks or 0
            if plateau.record(float(proposal.get("confidence", 0.0))):
                break  # plateau — more retries won't help; the last judge verdict stands
            last = ground(proposal, chunk)          # judge gates this attempt
            if last.get("ok"):
                grounded = True
                break
            feedback = last.get("detail")           # judge feedback shapes the next retry

        out = {
            "grounded": grounded,
            "record_id": (last or {}).get("record_id"),
            "reason_code": (last or {}).get("reason_code"),
            "attempts": len(plateau.trajectory),
            "confidence_trajectory": plateau.trajectory,   # glass box — tune epsilon from this
            "best_confidence": plateau.best_confidence,
        }
        return out, tokens
