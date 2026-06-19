from __future__ import annotations

"""Pass 5 — meaning. Per chunk, the claim-relevance significance (what the needle would embed).

A short interpreted meaning + the questions the chunk answers — the interpretation tier
(enrichment_meaning concept). Pass 5's output is what a later NEEDLE iteration embeds + ranks;
for v0 it is produced + captured, the needle reading itself deferred.
"""

import json
import re
from typing import Any

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

_SYSTEM = (
    "In 1-2 sentences, state the claim-relevance MEANING of this chunk of an insurance claim "
    "file — its significance to the claim decision/denial. Then list the questions it answers. "
    'Reply with ONLY a JSON object: {"claim_meaning": "<1-2 sentences>", '
    '"questions_answered": ["<question>", ...]}.'
)


def parse_meaning(content: str) -> tuple[str, list[str]]:
    """Parse {claim_meaning, questions_answered}; fall back to raw text as the meaning."""
    raw = (content or "").strip()
    obj = None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict):
        meaning = str(obj.get("claim_meaning", "")).strip()
        qs = obj.get("questions_answered")
        questions = [str(q) for q in qs] if isinstance(qs, list) else []
        if meaning:
            return meaning, questions
    return raw, []   # defensive: keep the model's prose as the meaning rather than lose it


class Pass5Meaning(Pass):
    name = "5_meaning"
    per_chunk = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        content, tokens = ctx.model.complete(_SYSTEM, f"CHUNK:\n{chunk.text}")
        meaning, questions = parse_meaning(content)
        return {"claim_meaning": meaning, "questions_answered": questions}, tokens
