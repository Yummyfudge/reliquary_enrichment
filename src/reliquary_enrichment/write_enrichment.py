from __future__ import annotations

"""write_enrichment — the validated provenance write boundary (THE safety-critical tool).

The only path by which extracted meaning reaches storage. It makes the invariant
mechanical: the model POINTS (handle + offsets + reasoning); code COPIES the exact span;
the judge CHECKS the claim against that copy; the row ATTESTS (hashes frozen) — all before
a single row is written. Pipeline = contract write_enrichment.md §5 (steps 1-11), built on
the shared grounding-core (steps 1-6). Records are write-once.
"""

import json
from dataclasses import dataclass

from reliquary_enrichment.entities import EntityResolver
from reliquary_enrichment.grounding.core import GroundingCore, sha256_text
from reliquary_enrichment.grounding.types import (
    GroundingError,
    JudgeResult,
    ReasonCode,
    Tier,
)
from reliquary_enrichment.models import EnrichmentRecord
from reliquary_enrichment.stores import EnrichmentRecordStore

_TIERS = {t.value for t in Tier}

# Typed entities carried in a record's `fields` that resolve to Codex Entities (besides the
# dedicated actor/event_date payload slots). For these, the EntityRef.role IS the entity_type.
_FIELD_ENTITY_TYPES = ("code", "location", "document", "provision")


@dataclass(frozen=True, slots=True)
class _Payload:
    """The validated model payload (only the fields the model is allowed to supply)."""

    record_type: str
    tier: Tier
    char_start: int
    char_end: int
    chunk_handle: str | None
    echoed_chunk_id: str | None
    fields: dict
    actor: str | None
    event_date: str | None
    confidence: float | None


def _validate(payload: dict) -> _Payload:
    """Validate the payload shape -> REJECT schema_invalid (names the offending field).

    Type/range checks for offsets are NOT here — out-of-range offsets are a grounding
    failure (bad_offsets, §5.3), not a schema failure. This guards presence + types of
    the model-supplied fields, and refuses the code-owned fields if the model sends them.
    """

    def fail(detail: str):
        raise GroundingError(ReasonCode.SCHEMA_INVALID, detail)

    if not isinstance(payload, dict):
        fail("payload must be an object")

    # Refuse code-owned tokens as source of truth (an echoed chunk_id is allowed as a
    # cross-check only; evidence_span/page/document/hashes are never the model's to set).
    for forbidden in ("evidence_span", "page", "document", "provenance_validation",
                      "source_sha256", "evidence_sha256", "source_chunk_id"):
        if forbidden in payload:
            fail(f"{forbidden!r} is code-derived and must not be in the payload")

    record_type = payload.get("record_type")
    if not isinstance(record_type, str) or not record_type.strip():
        fail("record_type (non-empty string) is required")

    tier_raw = payload.get("tier")
    if tier_raw not in _TIERS:
        fail(f"tier must be one of {sorted(_TIERS)}")

    for k in ("char_start", "char_end"):
        if not isinstance(payload.get(k), int) or isinstance(payload.get(k), bool):
            fail(f"{k} (integer) is required")

    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        fail("fields must be an object")

    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            fail("confidence must be a number in [0,1]")
        if not (0.0 <= float(confidence) <= 1.0):
            fail("confidence must be in [0,1]")

    for k in ("actor", "event_date", "chunk_handle", "chunk_id"):
        v = payload.get(k)
        if v is not None and not isinstance(v, str):
            fail(f"{k} must be a string when present")

    return _Payload(
        record_type=record_type.strip(),
        tier=Tier(tier_raw),
        char_start=payload["char_start"],
        char_end=payload["char_end"],
        chunk_handle=payload.get("chunk_handle"),
        echoed_chunk_id=payload.get("chunk_id"),
        fields=fields,
        actor=payload.get("actor"),
        event_date=payload.get("event_date"),
        confidence=float(confidence) if confidence is not None else None,
    )


def render_record_claim(p: _Payload) -> str:
    """Render the asserted values the judge must check against the span (§8 prompt input).

    Lists exactly what the model asserts — actor, date, each field — so the judge can
    name any value that drifts. The judge sees this PLUS the code-sliced span, never the
    model's free prose about the source.

    NOTE: ``record_type`` is DELIBERATELY excluded — it is the model's category label
    ("status_change"), not a value the span must literally contain. Including it made the
    judge bounce every fact whose record_type words weren't in the span (surfaced by the
    extraction probe against the real judge; the fake-judge unit tests couldn't catch it).
    Only real asserted values (actor / date / fields) are grounded.
    """
    parts = []
    if p.actor:
        parts.append(f"actor: {p.actor}")
    if p.event_date:
        parts.append(f"event_date: {p.event_date}")
    if p.fields:
        parts.append(f"details: {json.dumps(p.fields, ensure_ascii=False, sort_keys=True)}")
    # Degenerate case (no asserted values): describe the record type without demanding it
    # appear literally in the span.
    return "; ".join(parts) if parts else f"the span records a {p.record_type} event"


class WriteEnrichment:
    """Composes the grounding-core + record store + entity resolver into the write boundary."""

    def __init__(
        self,
        *,
        core: GroundingCore,
        record_store: EnrichmentRecordStore,
        entity_resolver: EntityResolver,
    ) -> None:
        self._core = core
        self._records = record_store
        self._entities = entity_resolver

    def write(self, payload: dict, *, workstream_id: str) -> dict:
        """Run the full validated pipeline. Returns the success or rejection contract (§6)."""
        try:
            return self._write(payload, workstream_id)
        except GroundingError as exc:
            # The rejection IS the feedback loop: the agent re-points, never re-transcribes.
            return {"ok": False, "reason_code": str(exc.reason_code), "detail": exc.detail}

    def _write(self, payload: dict, workstream_id: str) -> dict:
        p = _validate(payload)  # step 0: schema

        # Steps 1-2: resolve + load the Fragment (handle / current / cross-checked id).
        fragment = self._core.resolve_fragment(
            workstream_id, chunk_handle=p.chunk_handle, chunk_id=p.echoed_chunk_id
        )

        # Steps 3-4: bounds-check + CODE-slice the Evidence Span (model span text ignored).
        span = self._core.slice_span(fragment, p.char_start, p.char_end)

        # Step 5: the judge checks the asserted values against the code-sliced span.
        result: JudgeResult = self._core.judge_record(p.tier, render_record_claim(p), span)

        # Step 6: tier gate (strict-core / soft-rest). Rejection raises GroundingError.
        gate = self._core.gate(
            p.tier,
            result,
            fact_reason=ReasonCode.UNGROUNDED_FACT,
            interp_reason=ReasonCode.UNSUPPORTED_INTERPRETATION,
        )

        # Steps 7-8: derive provenance from the Fragment + freeze Provenance Validation.
        attestation = self._core.build_attestation(
            result,
            hashes={
                "evidence_sha256": sha256_text(span),
                "source_sha256": sha256_text(fragment.text),
            },
        )

        # Step 9: resolve EVERY judge-validated typed entity to Codex Entities
        # (actor/date from slots; code/location/document/provision from fields).
        record = EnrichmentRecord(
            record_type=p.record_type,
            tier=str(p.tier),
            source_chunk_id=fragment.chunk_id,
            char_start=p.char_start,
            char_end=p.char_end,
            evidence_span=span,
            provenance_validation=attestation,
            fields=p.fields,
            actor=p.actor,
            event_date=p.event_date,
            confidence=p.confidence,
            page=fragment.page,
            document=fragment.document,
            flagged=gate.flagged,
        )
        record.entity_refs = self._resolve_entities(p, record.record_id)

        # Step 10: write the immutable record.
        self._records.insert(record)

        # Step 11: return the success contract.
        return {
            "ok": True,
            "record_id": record.record_id,
            "source_chunk_id": fragment.chunk_id,
            "evidence_span": span,
            "provenance_validation": attestation,
            "flagged": record.flagged,
        }

    def _resolve_entities(self, p: _Payload, record_id: str) -> list:
        """Resolve every judge-validated typed entity to a Codex Entity + return its EntityRefs
        (brief §5.2): actor + date from the dedicated slots, code/location/document/provision from
        `fields`. resolve_or_create's alias-not-merge contract is unchanged."""
        refs = []
        if p.actor:
            entity = self._entities.resolve_or_create(
                "actor", p.actor, first_seen_record=record_id
            )
            refs.append(self._entities.ref_for("actor", entity))
        if p.event_date:
            entity = self._entities.resolve_or_create(
                "date", p.event_date, first_seen_record=record_id
            )
            refs.append(self._entities.ref_for("event_date", entity))
        for etype in _FIELD_ENTITY_TYPES:
            value = p.fields.get(etype)
            if isinstance(value, str) and value.strip():
                entity = self._entities.resolve_or_create(
                    etype, value, first_seen_record=record_id
                )
                refs.append(self._entities.ref_for(etype, entity))
        return refs
