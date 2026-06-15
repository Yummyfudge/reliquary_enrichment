from __future__ import annotations

"""link_events — the validated Link write boundary (mirrors write_enrichment).

Writes one grounded cross-record Link into the Codex. Same law as records: the model
PROPOSES a specific pair + relation + cited spans; code COPIES the spans; the judge CHECKS
the relation; the row ATTESTS (both span hashes frozen). Pipeline = codex.md §5, on the
shared grounding-core. Links are write-once. Event Entities are materialized here, and
ONLY here, from grounded same_event Links (§6).

Combinatorial guard (§4): this tool writes exactly ONE link per call — the specific pair
the model proposed. It has no all-pairs capability by construction; cross-link noise is
controlled at the proposal, not generated here.
"""

from dataclasses import dataclass

from reliquary_enrichment.entities import EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore, sha256_text
from reliquary_enrichment.grounding.types import GroundingError, ReasonCode, Tier
from reliquary_enrichment.models import Link
from reliquary_enrichment.stores import EnrichmentRecordStore, LinkStore

_TIERS = {t.value for t in Tier}

# Seed relation vocabulary (codex §4). Emergent/curated — new relations are EXPECTED in
# Pass 1/3, so unknown relations are accepted (not hard-rejected); this is the seed set.
SEED_RELATIONS = frozenset({
    "precedes", "follows", "causes", "results_from",
    "corroborates", "contradicts", "elaborates", "same_event", "references",
})
SAME_EVENT = "same_event"


@dataclass(frozen=True, slots=True)
class _LinkPayload:
    record_a: str
    record_b: str
    relation: str
    tier: Tier
    a_span: tuple[int, int]
    b_span: tuple[int, int]
    rationale: str
    confidence: float | None
    evidence: dict


def _span(evidence: dict, key: str, fail) -> tuple[int, int]:
    raw = evidence.get(key)
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 2
        or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw)
    ):
        fail(f"evidence.{key} must be a [start, end] pair of integers")
    return int(raw[0]), int(raw[1])


def _validate(payload: dict) -> _LinkPayload:
    def fail(detail: str):
        raise GroundingError(ReasonCode.SCHEMA_INVALID, detail)

    if not isinstance(payload, dict):
        fail("payload must be an object")
    for k in ("record_a", "record_b", "relation", "rationale"):
        if not isinstance(payload.get(k), str) or not payload[k].strip():
            fail(f"{k} (non-empty string) is required")
    if payload["record_a"] == payload["record_b"]:
        fail("record_a and record_b must differ (no self-links)")
    if payload.get("tier") not in _TIERS:
        fail(f"tier must be one of {sorted(_TIERS)}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        fail("evidence object with a_span and b_span is required")
    a_span = _span(evidence, "a_span", fail)
    b_span = _span(evidence, "b_span", fail)
    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            fail("confidence must be a number in [0,1]")
        if not (0.0 <= float(confidence) <= 1.0):
            fail("confidence must be in [0,1]")
    return _LinkPayload(
        record_a=payload["record_a"],
        record_b=payload["record_b"],
        relation=payload["relation"].strip(),
        tier=Tier(payload["tier"]),
        a_span=a_span,
        b_span=b_span,
        rationale=payload["rationale"],
        confidence=float(confidence) if confidence is not None else None,
        evidence=evidence,
    )


class LinkEvents:
    """Composes the grounding-core + record store + link store + event materializer."""

    def __init__(
        self,
        *,
        core: GroundingCore,
        record_store: EnrichmentRecordStore,
        link_store: LinkStore,
        event_materializer: EventMaterializer,
    ) -> None:
        self._core = core
        self._records = record_store
        self._links = link_store
        self._events = event_materializer

    def link(self, payload: dict, *, workstream_id: str) -> dict:
        """Run the full validated link pipeline. Returns success or rejection (§9)."""
        try:
            return self._link(payload, workstream_id)
        except GroundingError as exc:
            return {"ok": False, "reason_code": str(exc.reason_code), "detail": exc.detail}

    def _link(self, payload: dict, workstream_id: str) -> dict:
        p = _validate(payload)

        # Step 1: resolve BOTH records (mangled id -> unknown_record; nothing written).
        rec_a = self._records.get(p.record_a)
        rec_b = self._records.get(p.record_b)
        if rec_a is None or rec_b is None:
            missing = p.record_a if rec_a is None else p.record_b
            raise GroundingError(
                ReasonCode.UNKNOWN_RECORD,
                f"no Enrichment Record {missing!r}; re-reference an existing record id "
                "(do not retype the id from memory).",
            )

        # Step 2: load each record's underlying Fragment.
        frag_a = self._core.load_fragment(rec_a.source_chunk_id)
        frag_b = self._core.load_fragment(rec_b.source_chunk_id)

        # Step 3: CODE-slice the cited evidence spans from each Fragment.
        span_a = self._core.slice_span(frag_a, *p.a_span)
        span_b = self._core.slice_span(frag_b, *p.b_span)

        # Step 4: tier-aware judge over the relation + both spans.
        result = self._core.judge_link(p.tier, p.relation, span_a, span_b, p.rationale)

        # Step 5: tier gate (relation reason for both tiers).
        gate = self._core.gate(
            p.tier,
            result,
            fact_reason=ReasonCode.UNGROUNDED_RELATION,
            interp_reason=ReasonCode.UNGROUNDED_RELATION,
        )

        # Step 6: freeze Provenance Validation — BOTH span hashes + BOTH source hashes.
        attestation = self._core.build_attestation(
            result,
            hashes={
                "a_evidence_sha256": sha256_text(span_a),
                "b_evidence_sha256": sha256_text(span_b),
                "a_source_sha256": sha256_text(frag_a.text),
                "b_source_sha256": sha256_text(frag_b.text),
            },
        )

        # Step 7: same_event -> materialize/merge the Event Entity (code, not the model).
        event_entity_id: str | None = None
        if p.relation == SAME_EVENT:
            event = self._events.materialize(p.record_a, p.record_b)
            event_entity_id = event.entity_id

        # Step 8: write the immutable Link.
        link = Link(
            record_a=p.record_a,
            record_b=p.record_b,
            relation=p.relation,
            tier=str(p.tier),
            evidence={
                "a_span": list(p.a_span),
                "b_span": list(p.b_span),
                "a_source_chunk_id": frag_a.chunk_id,
                "b_source_chunk_id": frag_b.chunk_id,
            },
            provenance_validation=attestation,
            confidence=p.confidence,
            event_entity=event_entity_id,
            flagged=gate.flagged,
        )
        self._links.insert(link)

        # Step 9: return.
        out = {
            "ok": True,
            "link_id": link.link_id,
            "relation": p.relation,
            "provenance_validation": attestation,
            "flagged": link.flagged,
        }
        if event_entity_id is not None:
            out["event_entity"] = event_entity_id
        return out
