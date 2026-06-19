from __future__ import annotations

"""Pass 2.9 — consolidate. Merge the per-chunk object-types into ONE emergent schema.

A whole-state pass: gather every raw type Pass 2 found, ask the model to merge synonyms/dupes
into a canonical vocabulary, and KEEP **raw + final + mapping** (the glass-box requirement) so
the curation is inspectable. Defensive: if the model's consolidation can't be read, fall back to
an identity mapping over the normalized raw set — never crash the pipeline. Every raw type is
guaranteed a mapping target.
"""

import json
import re

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

_SYSTEM = (
    "You are given object-type names discovered across one claim file; some are synonyms or "
    "near-duplicates. Merge them into a canonical schema. Reply with ONLY a JSON object: "
    '{"canonical": ["<type>", ...], "mapping": {"<raw_type>": "<canonical_type>", ...}}. '
    "Every input type must appear as a key in mapping."
)


def parse_consolidation(content: str, raw_types: list[str]) -> tuple[list[str], dict[str, str]]:
    """Parse {canonical, mapping}; fall back to identity so every raw type maps to something."""
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
    mapping: dict[str, str] = {}
    canonical: list[str] = []
    if isinstance(obj, dict):
        raw_map = obj.get("mapping") if isinstance(obj.get("mapping"), dict) else {}
        mapping = {str(k): str(v) for k, v in raw_map.items()}
        canon = obj.get("canonical")
        if isinstance(canon, list):
            canonical = [str(c) for c in canon]
    # guarantee every raw type maps (identity fallback for any the model dropped)
    for t in raw_types:
        mapping.setdefault(t, t)
    if not canonical:
        canonical = sorted(set(mapping.values()))
    return canonical, mapping


class Pass2_9Consolidate(Pass):
    name = "2_9_consolidate"
    per_chunk = False

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> dict:
        per_chunk = {
            cid: out.get("object_types", [])
            for cid, out in prior["2_objecttypes"].outputs.items()
        }
        raw_types = sorted({t for types in per_chunk.values() for t in types})
        content, _ = ctx.model.complete(_SYSTEM, "TYPES:\n" + json.dumps(raw_types))
        canonical, mapping = parse_consolidation(content, raw_types)
        return {
            "raw": per_chunk,          # per-chunk raw types (glass box)
            "raw_types": raw_types,    # the flat raw vocabulary
            "final": canonical,        # the consolidated canonical schema
            "mapping": mapping,        # raw_type -> canonical_type
        }
