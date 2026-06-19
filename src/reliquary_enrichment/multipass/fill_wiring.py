from __future__ import annotations

"""Real Pass-3 wiring — the candidate PROPOSES a value-fill; write_enrichment GROUNDS it.

proposer(chunk, schema, feedback) -> (proposal, tokens): the candidate ModelClient emits one
record proposal (verbatim quote + typed values + self-reported confidence); on a retry the
judge's feedback is appended so the model fixes the prior rejection.
grounder(proposal, chunk) -> result: locate the quote in the chunk (code), slice via
write_enrichment (the judge gates), write into the probe schema. A quote that can't be located
returns locate_miss feedback — never stored.

The candidate (proposer) and the judge (inside write_enrichment) are DIFFERENT models, by design:
the candidate is the variable under test; the fixed Qwen2.5-14B judge rules on grounding.
v0 simplification: one record per chunk (the loop refines it); multi-record-per-chunk is later.
"""

import json
import re

from reliquary_enrichment.multipass.pass_base import ChunkRef, ModelClient
from reliquary_enrichment.probe.extraction import locate_quote

_FILL_SYSTEM = (
    "Extract ONE grounded record from this claim-file chunk, filling the given schema types. "
    "Provide a verbatim QUOTE copied from the chunk that LITERALLY contains every value you "
    "assert (actor, event_date, each field). Reply with ONLY a JSON object: "
    '{"quote": "<verbatim>", "record_type": "<from schema if it fits>", "tier": "fact|'
    'interpretation", "fields": {..}, "actor": "<or null>", "event_date": "<YYYY-MM-DD or null>", '
    '"confidence": <0..1>}. If FEEDBACK is given, a prior attempt was rejected — fix it.'
)


def parse_fill(content: str) -> dict:
    """Defensively parse the candidate's fill proposal; confidence defaults to 0.0."""
    obj = None
    try:
        obj = json.loads(content or "")
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", content or "", re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return {"quote": "", "confidence": 0.0}
    try:
        obj["confidence"] = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        obj["confidence"] = 0.0
    return obj


def make_proposer(model: ModelClient):
    def propose(chunk: ChunkRef, schema, feedback):
        user = f"SCHEMA TYPES: {json.dumps(schema)}\nCHUNK:\n{chunk.text}"
        if feedback:
            user += f"\n\nFEEDBACK (a prior attempt was REJECTED — fix it): {feedback}"
        content, tokens = model.complete(_FILL_SYSTEM, user)
        return parse_fill(content), tokens
    return propose


def make_grounder(write_service, workstream_id: str):
    """Ground a proposal via write_enrichment over the probe schema (judge gates)."""
    def ground(proposal: dict, chunk: ChunkRef) -> dict:
        loc = locate_quote(chunk.text, proposal.get("quote", "") or "")
        if loc is None:
            return {"ok": False, "reason_code": "locate_miss",
                    "detail": "quoted span not found in the chunk — re-quote verbatim from it"}
        start, end = loc
        tier = proposal.get("tier") if proposal.get("tier") in ("fact", "interpretation") else "fact"
        payload = {
            "chunk_id": chunk.chunk_id, "char_start": start, "char_end": end,
            "record_type": (proposal.get("record_type") or "fact"), "tier": tier,
            "fields": proposal.get("fields") or {}, "actor": proposal.get("actor"),
            "event_date": proposal.get("event_date"),
            "confidence": proposal.get("confidence"),
        }
        return write_service.write(payload, workstream_id=workstream_id)
    return ground
