from __future__ import annotations

"""Pass 3 — fill-values. Ground a per-chunk BATCH of typed-entity records over the closed vocab.

Multi-record (brief §5.2): the candidate PROPOSES a LIST of typed entities (each its own verbatim
quote); code GROUNDS EACH via write_enrichment (the JUDGE gates per record). The retry loop, exactly
per Joe's rule (separation of concerns), now wraps the per-chunk BATCH:
  * the candidate PROPOSES the chunk's typed entities (each with self-reported confidence);
  * code GROUNDS each — the JUDGE gates (accept / flag / bounce) per record;
  * on bounces the judge's FEEDBACK shapes the next retry — but does NOT decide the stop;
  * the CONFIDENCE-PLATEAU owns "keep trying?" over the GROUNDED FRACTION (Joe-confirmed): stop when
    a retry fails to beat the best-so-far grounded fraction by ≥ epsilon. The per-chunk trajectory is
    captured (glass box) for ε-tuning.

DATA-FLOW (brief §5.2/§7): the "schema" is the fixed closed vocabulary (``vocabulary.ENTITY_TYPES``),
narrowed per-chunk by Pass 2's own typed-types output (``prior["2_objecttypes"]``). Pass 3 does NOT
read ``prior["2_9_consolidate"]`` — normalization runs AFTER Pass 3 (codex-first sequencing).

`proposer` and `grounder` are injected via ctx.extras so the pass is unit-testable with fakes:
  proposer(chunk, schema, feedback) -> (proposals: list[EntityProposal], tokens: int)
  grounder(proposal, chunk)          -> result: dict{ok, record_id, reason_code, detail}
"""

from typing import Any

from reliquary_enrichment.multipass.confidence import ConfidencePlateau
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES


class Pass3FillValues(Pass):
    name = "3_fillvalues"
    per_chunk = True

    def __init__(self, *, epsilon: float = 0.05, max_attempts: int = 25) -> None:
        self.epsilon = epsilon
        self.max_attempts = max_attempts   # belt-and-suspenders; the plateau is the real bound

    def _schema_for(self, chunk: ChunkRef, prior: dict[str, PassResult]) -> list[str]:
        """The closed vocabulary, narrowed by Pass 2's per-chunk types (full vocab if Pass 2 empty)."""
        present: list[str] = []
        p2 = prior.get("2_objecttypes")
        if p2 is not None:
            present = (p2.outputs.get(chunk.chunk_id) or {}).get("object_types", []) or []
        narrowed = [t for t in present if t in ENTITY_TYPES]
        return narrowed or sorted(ENTITY_TYPES)

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        schema = self._schema_for(chunk, prior)
        propose = ctx.extras["proposer"]
        ground = ctx.extras["grounder"]
        plateau = ConfidencePlateau(self.epsilon)
        feedback = None
        tokens = 0
        best = {"n_grounded": -1, "record_ids": [], "results": [], "n_proposed": 0}

        for _ in range(self.max_attempts):
            proposals, toks = propose(chunk, schema, feedback)
            tokens += toks or 0
            results = [ground(p, chunk) for p in proposals]       # judge gates each record
            ok = [r for r in results if r.get("ok")]
            n_prop = len(proposals)
            frac = len(ok) / n_prop if n_prop else 0.0
            if len(ok) > best["n_grounded"]:                       # keep the best attempt's records
                best = {"n_grounded": len(ok),
                        "record_ids": [r.get("record_id") for r in ok],
                        "results": results, "n_proposed": n_prop}
            if plateau.record(frac):
                break  # grounded fraction plateaued — more retries won't help; verdicts stand
            if n_prop and len(ok) == n_prop:
                break  # every proposed entity grounded
            bounced = [r for r in results if not r.get("ok")]
            feedback = "; ".join(
                f"{r.get('reason_code')}: {r.get('detail')}" for r in bounced[:5]
            ) or None

        results = best["results"]
        first_bounce = next((r for r in results if not r.get("ok")), None)
        n_grounded = max(0, best["n_grounded"])
        out = {
            "grounded": n_grounded > 0,
            "record_ids": best["record_ids"],
            "n_grounded": n_grounded,
            "n_proposed": best["n_proposed"],
            "reason_code": first_bounce.get("reason_code") if first_bounce else None,
            "reasons": [r.get("reason_code") for r in results],
            "attempts": len(plateau.trajectory),
            "confidence_trajectory": plateau.trajectory,   # grounded-fraction trajectory (glass box)
            "best_confidence": plateau.best_confidence,
        }
        return out, tokens
