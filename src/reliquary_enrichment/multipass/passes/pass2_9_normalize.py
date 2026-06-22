from __future__ import annotations

"""Pass 2.9 (slot) — EntityNormalizationPass: deterministic entity normalization, AFTER Pass 3.

Codex-first sequencing (§7): Pass 3 grounded typed-entity records; this whole-state pass
canonicalizes/resolves what 3 grounded into the codex's shared nouns. The deterministic
canonicalizers (entities.normalize_*) run FIRST via resolve_or_create — surface variants of the
SAME entity collapse to ONE node (idempotent: Pass 3 already resolved inline; this re-resolves to
build the glass-box surface->entity_id map). The LLM is used ONLY for residual ambiguity — same-type
entities whose canonicals DIFFER but might be aliases — and it FLAGS, never merges
(flag-don't-silent-merge; route to curation). Over-merge corrupts a shared node and provenance is the
mission, so this pass NEVER collapses on uncertainty.

Glass-box output (replaces the old open-vocab type-merge), now over surface -> entity_id:
  raw            : per chunk, the [type, surface] pairs grounded
  mapping        : surface -> entity_id (the resolution map)
  final          : entity_id -> {type, canonical, surfaces}
  flagged_merges : residual same-type candidates the LLM flagged for curation (NEVER merged)

Injected via ctx.extras (entity_resolver, record_store) + ctx.model, so it is unit-testable with fakes.
"""

import json

from reliquary_enrichment.multipass.parsing import safe_json_array
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

# Typed entities carried in `fields` (mirrors write_enrichment._FIELD_ENTITY_TYPES). 'event' is NOT
# resolved here — Events are materialized from same_event links, never from a surface.
_FIELD_ENTITY_TYPES = ("code", "location", "document", "provision")

_MERGE_SYSTEM = (
    "These are distinct canonical {type} values extracted from ONE claim file; some MAY be variants "
    "of the SAME real-world entity (aliases). Reply with ONLY a JSON array of the pairs that are the "
    "same entity: [[\"A\",\"B\"], ...]; [] if all are distinct. Do NOT pair anything you are unsure "
    "about — uncertain pairs are left separate for human curation."
)


def typed_surfaces(record) -> list[tuple[str, str]]:
    """The (entity_type, surface) pairs a grounded record carries (mirrors _resolve_entities)."""
    out: list[tuple[str, str]] = []
    if getattr(record, "actor", None):
        out.append(("actor", record.actor))
    if getattr(record, "event_date", None):
        out.append(("date", record.event_date))
    fields = getattr(record, "fields", None) or {}
    for etype in _FIELD_ENTITY_TYPES:
        value = fields.get(etype)
        if isinstance(value, str) and value.strip():
            out.append((etype, value))
    return out


class EntityNormalizationPass(Pass):
    name = "2_9_normalize"
    per_chunk = False

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> dict:
        resolver = ctx.extras["entity_resolver"]
        record_store = ctx.extras["record_store"]
        p3 = prior.get("3_fillvalues")     # §7 buildability: normalization runs AFTER Pass 3

        raw: dict[str, list] = {}
        mapping: dict[str, str] = {}
        final: dict[str, dict] = {}

        for chunk in chunks:
            cid = chunk.chunk_id
            rec_ids = (p3.outputs.get(cid) or {}).get("record_ids", []) if p3 else []
            pairs: list[list[str]] = []
            for rid in rec_ids:
                record = record_store.get(rid)
                if record is None:
                    continue
                for etype, surface in typed_surfaces(record):
                    entity = resolver.resolve_or_create(etype, surface, first_seen_record=rid)
                    pairs.append([etype, surface])
                    mapping[surface] = entity.entity_id
                    slot = final.setdefault(
                        entity.entity_id,
                        {"type": etype, "canonical": entity.canonical, "surfaces": []},
                    )
                    if surface not in slot["surfaces"]:
                        slot["surfaces"].append(surface)
            raw[cid] = pairs

        flagged = self._flag_residual(final, ctx)
        return {"raw": raw, "mapping": mapping, "final": final, "flagged_merges": flagged}

    def _flag_residual(self, final: dict[str, dict], ctx: PassContext) -> list[dict]:
        """The LLM proposes same-entity candidates among same-type entities with DIFFERENT canonicals;
        we FLAG them for curation, NEVER merge. Bounded: at most one model call per type with >= 2
        distinct canonicals. The deterministic canonicalizers already collapsed exact matches, so this
        only ever sees genuinely-residual ambiguity."""
        by_type: dict[str, list[str]] = {}
        for info in final.values():
            by_type.setdefault(info["type"], []).append(info["canonical"])

        flagged: list[dict] = []
        seen: set = set()
        for etype, canons in by_type.items():
            uniq = sorted(set(canons))
            if len(uniq) < 2:
                continue
            content, _ = ctx.model.complete(_MERGE_SYSTEM.replace("{type}", etype), json.dumps(uniq))
            for pair in safe_json_array(content):
                if (isinstance(pair, list) and len(pair) == 2
                        and all(isinstance(x, str) for x in pair)):
                    a, b = pair[0], pair[1]
                    if a in uniq and b in uniq and a != b:
                        key = (etype, *sorted([a, b]))   # dedup: a spammy reply can't bloat the list
                        if key in seen:
                            continue
                        seen.add(key)
                        flagged.append({"type": etype, "candidates": sorted([a, b]),
                                        "action": "flag-for-curation"})
        return flagged
