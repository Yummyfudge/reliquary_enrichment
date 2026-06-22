from __future__ import annotations

"""Pass 2 — object-types. Per chunk, WHICH closed-vocab entity types are present (not values).

Names which of the FIXED closed entity types (``vocabulary.ENTITY_TYPES`` — actor / date / event /
document / provision / code / location) the chunk contains. This per-chunk subset NARROWS Pass 3's
multi-record extraction (Pass 3 sources its type list from the vocabulary, narrowed by this). Just
the types present; values are Pass 3's job. Off-vocabulary names are dropped (no open vocabulary).
"""

import re
from typing import Any

from reliquary_enrichment.multipass.parsing import safe_json_array
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES

_SYSTEM = (
    "Which of these entity types are PRESENT in this chunk of an insurance claim file? The FIXED "
    "vocabulary is exactly: actor, date, event, document, provision, code, location. Reply with "
    "ONLY a JSON array naming the types present (a subset of that vocabulary, lowercased); [] if "
    "the chunk holds none of them."
)

_NORM = re.compile(r"[^a-z0-9]+")


def parse_type_list(content: str) -> list[str]:
    """Parse a JSON array of type names; keep ONLY closed-vocab types; normalize + dedup (stable)."""
    arr = safe_json_array(content or "")
    out: list[str] = []
    seen: set[str] = set()
    for item in arr:
        name = item if isinstance(item, str) else (item.get("name") if isinstance(item, dict) else None)
        if not name:
            continue
        norm = _NORM.sub("_", str(name).strip().lower()).strip("_")
        if norm in ENTITY_TYPES and norm not in seen:
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
