from __future__ import annotations

"""Pass 4 — signal-keywords. Per chunk, the claim-relevance signals worth indexing.

Terms that matter to the claim decision/denial (diagnoses, actions, statuses, conditions,
dates). Free phrases (kept lowercased; NOT snake_cased — keywords can be multi-word). 4.9
cleans/dedupes them across the file.
"""

import re
from typing import Any

from reliquary_enrichment.multipass.parsing import safe_json_array
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

_SYSTEM = (
    "Extract the claim-relevance SIGNAL keywords from this chunk of an insurance claim file — "
    "terms that bear on the claim decision/denial (diagnoses, actions, statuses, conditions, key "
    "dates, actors). Reply with ONLY a JSON array of short lowercase keyword/phrase strings; "
    "[] if the chunk carries no signal."
)

_WS = re.compile(r"\s+")


def normalize_keyword(kw: str) -> str:
    """Lowercase + collapse whitespace + strip (keeps multi-word phrases intact)."""
    return _WS.sub(" ", str(kw).strip().lower()).strip()


def parse_keyword_list(content: str) -> list[str]:
    """Defensively parse a JSON array of keyword strings; normalize + dedup (order-stable)."""
    arr = safe_json_array(content or "")
    out: list[str] = []
    seen: set[str] = set()
    for item in arr:
        kw = item if isinstance(item, str) else None
        if not kw:
            continue
        norm = normalize_keyword(kw)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


class Pass4Keywords(Pass):
    name = "4_keywords"
    per_chunk = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        content, tokens = ctx.model.complete(_SYSTEM, f"CHUNK:\n{chunk.text}")
        return {"keywords": parse_keyword_list(content)}, tokens
