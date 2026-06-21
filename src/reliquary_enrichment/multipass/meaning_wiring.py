from __future__ import annotations

"""Meaning proposer — the model POINTS a local-fact meaning + the verbatim span that grounds it (§5.4).

Mirrors fill_wiring / link_wiring: the candidate model proposes, CODE locates the span (locate_quote), the
gated MeaningWriter grounds + judges + stores. The model never supplies offsets or routes to a record —
it states a small standalone fact and copies the span it read it from; everything else is code/judge.
"""

from reliquary_enrichment.multipass.parsing import safe_json_object

_MEANING_SYSTEM = (
    "State the single most claim-relevant LOCAL FACT this chunk of an insurance claim file establishes — "
    "ONE short standalone sentence naming the specific actor / code / date / provision involved. NOT a "
    "generic summary, NOT a meta-description ('this chunk shows ...'). Then copy the VERBATIM span of the "
    "chunk that states it. Reply with ONLY a JSON object: "
    '{"meaning":"<one short standalone local fact>","quote":"<verbatim span copied from the chunk>"}.'
)


def make_meaning_proposer(model):
    """model -> propose(chunk_text) -> ({meaning, quote}, tokens). CODE locates the quote (grounding law)."""
    def propose(chunk_text: str):
        content, tokens = model.complete(_MEANING_SYSTEM, f"CHUNK:\n{chunk_text}")
        return (safe_json_object(content) or {}), tokens
    return propose
