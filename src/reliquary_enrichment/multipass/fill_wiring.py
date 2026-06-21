from __future__ import annotations

"""Real Pass-3 wiring — the candidate PROPOSES a LIST of typed-entity records; write_enrichment
GROUNDS each one.

proposer(chunk, schema, feedback) -> (list[EntityProposal], tokens): the candidate ModelClient
emits EVERY typed entity it sees over the FIXED closed vocabulary, each with its OWN verbatim quote
and self-reported confidence; bad/off-vocab items are dropped by ``validate_entity_proposal`` (never
raises). On a retry the judge's feedback is appended so the model fixes the prior rejections.

grounder(proposal, chunk) -> result: route the typed entity into a write_enrichment payload
(actor -> actor, date -> event_date, code/location/document/provision/event -> fields[type]; the
record_type IS the entity type), locate the quote in the chunk (code), and write it (the judge
gates inside write_enrichment). A quote that can't be located returns locate_miss feedback — never
stored. write_enrichment._resolve_entities then resolves each typed entity to a Codex Entity.

The candidate (proposer) and the judge (inside write_enrichment) are DIFFERENT models, by design:
the candidate is the variable under test; the fixed Qwen2.5-14B judge rules on grounding.
"""

import json

from reliquary_enrichment.multipass.pass_base import ChunkRef, ModelClient
from reliquary_enrichment.multipass.parsing import EntityProposal, validate_entity_proposal
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES
from reliquary_enrichment.probe.extraction import locate_quote

_FILL_SYSTEM = (
    "Extract EVERY typed entity present in this claim-file chunk, over this FIXED type vocabulary: "
    + ", ".join(sorted(ENTITY_TYPES)) + ". Each entity is its OWN record with its OWN verbatim QUOTE "
    "copied from the chunk that LITERALLY contains the entity's value. Reply with ONLY a JSON ARRAY "
    'of objects: [{"type":"<one vocabulary type>","surface":"<the entity value>","quote":"<verbatim '
    'span from the chunk containing surface>","tier":"fact|interpretation","fields":{..optional..},'
    '"confidence":<0..1>}, ...]. Use [] if the chunk holds no typed entity. If FEEDBACK is given, '
    "prior proposals were REJECTED — fix them and re-quote verbatim."
)


def parse_fill_list(content: str) -> list[EntityProposal]:
    """Defensively parse the candidate's JSON array into validated EntityProposals (never raises).

    Off-vocab / shape-bad items are dropped by ``validate_entity_proposal`` (reject-to-None floor).
    """
    from reliquary_enrichment.multipass.parsing import safe_json_array

    out: list[EntityProposal] = []
    for item in safe_json_array(content or ""):
        p = validate_entity_proposal(item)
        if p is not None:
            out.append(p)
    return out


def make_proposer(model: ModelClient):
    def propose(chunk: ChunkRef, schema, feedback):
        user = f"PRESENT TYPES (focus on these): {json.dumps(schema)}\nCHUNK:\n{chunk.text}"
        if feedback:
            user += f"\n\nFEEDBACK (prior proposals were REJECTED — fix them): {feedback}"
        content, tokens = model.complete(_FILL_SYSTEM, user)
        return parse_fill_list(content), tokens
    return propose


def make_grounder(write_service, workstream_id: str):
    """Ground ONE typed-entity proposal via write_enrichment over the probe schema (judge gates)."""
    def ground(proposal: EntityProposal, chunk: ChunkRef) -> dict:
        loc = locate_quote(chunk.text, proposal.quote or "")
        if loc is None:
            return {"ok": False, "reason_code": "locate_miss",
                    "detail": "quoted span not found in the chunk — re-quote verbatim from it"}
        start, end = loc
        tier = proposal.tier if proposal.tier in ("fact", "interpretation") else "fact"
        fields = dict(proposal.fields)
        actor = event_date = None
        t = proposal.type
        if t == "actor":
            actor = proposal.surface
        elif t == "date":
            event_date = proposal.surface
        else:                                  # code/location/document/provision/event
            fields[t] = proposal.surface       # surface is the authoritative entity value
        payload = {
            "chunk_id": chunk.chunk_id, "char_start": start, "char_end": end,
            "record_type": t, "tier": tier,
            "fields": fields, "actor": actor, "event_date": event_date,
            "confidence": proposal.confidence,
        }
        return write_service.write(payload, workstream_id=workstream_id)
    return ground
