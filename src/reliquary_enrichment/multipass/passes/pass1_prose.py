from __future__ import annotations

"""Pass 1 — prose vs non-prose. Classify each chunk so downstream passes route handling.

A focused, cheap per-chunk call: narrative sentences/paragraphs => "prose"; key-value, lists,
forms, tables, codes => "non_prose". One-word answer, defensively parsed (default conservative
to non_prose). The candidate's classification is itself gate-checked later for faithfulness.
"""

from typing import Any

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

PROSE = "prose"
NON_PROSE = "non_prose"

_SYSTEM = (
    "You classify one chunk of an insurance claim file. Answer 'prose' if it is mostly "
    "narrative sentences/paragraphs; answer 'non_prose' if it is mostly key-value pairs, lists, "
    "form fields, tables, codes, or headers. Reply with ONLY one word: prose or non_prose."
)


def parse_prose_label(content: str) -> str:
    """Defensively map the model's reply to 'prose' | 'non_prose' (default non_prose)."""
    c = (content or "").strip().lower()
    if "non_prose" in c or "non-prose" in c or "non prose" in c or c.startswith("non"):
        return NON_PROSE
    if "prose" in c:
        return PROSE
    return NON_PROSE


class Pass1Prose(Pass):
    name = "1_prose"
    per_chunk = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        content, tokens = ctx.model.complete(_SYSTEM, f"CHUNK:\n{chunk.text}")
        return {"label": parse_prose_label(content)}, tokens
