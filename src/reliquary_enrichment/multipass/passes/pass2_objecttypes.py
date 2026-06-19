from __future__ import annotations

"""Pass 2 — object-types. Per chunk, what TYPES of records it holds (not the values).

The model names the record/object types it SEES (e.g. status_change, medical_opinion, date,
actor, question). Just the types — values are Pass 3's job. Output feeds 2.9's consolidation
into one emergent schema.
"""

import re
from typing import Any

from reliquary_enrichment.multipass.parsing import safe_json_array
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

_SYSTEM = (
    "List the TYPES of records/objects present in this chunk of an insurance claim file — NOT "
    "their values. Each type is a short snake_case name (e.g. status_change, medical_opinion, "
    "date, actor, question, task, denial_reason). Reply with ONLY a JSON array of type-name "
    "strings; [] if the chunk holds nothing structured."
)

_SNAKE = re.compile(r"[^a-z0-9]+")


def normalize_type(name: str) -> str:
    """Lowercase + snake_case a type name so synonyms collide for 2.9 (e.g. 'Status Change')."""
    return _SNAKE.sub("_", str(name).strip().lower()).strip("_")


def parse_type_list(content: str) -> list[str]:
    """Defensively parse a JSON array of type-name strings; normalize + dedup (order-stable)."""
    arr = safe_json_array(content or "")
    out: list[str] = []
    seen: set[str] = set()
    for item in arr:
        name = item if isinstance(item, str) else (item.get("name") if isinstance(item, dict) else None)
        if not name:
            continue
        norm = normalize_type(name)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


class Pass2ObjectTypes(Pass):
    name = "2_objecttypes"
    per_chunk = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        content, tokens = ctx.model.complete(_SYSTEM, f"CHUNK:\n{chunk.text}")
        return {"object_types": parse_type_list(content)}, tokens
