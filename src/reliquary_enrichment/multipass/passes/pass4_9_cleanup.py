from __future__ import annotations

"""Pass 4.9 — cleanup. Dedupe/normalize the Pass-4 keywords across the file (mechanical).

Unlike 2.9 (an LLM schema-merge), keyword cleanup is rule-based for v0: normalize, drop trivial
tokens (too short / stopwords), dedupe. Keeps raw + final + mapping + the per-chunk cleaned set
(glass box). An LLM near-synonym merge can layer on later behind the same output shape.
"""

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.passes.pass4_keywords import normalize_keyword

_STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "n/a", "none", "-"}


def clean_keyword(kw: str) -> str:
    """Normalize; return '' to DROP trivial tokens (too short / stopword)."""
    norm = normalize_keyword(kw)
    if len(norm) < 2 or norm in _STOPWORDS:
        return ""
    return norm


class Pass4_9Cleanup(Pass):
    name = "4_9_cleanup"
    per_chunk = False

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> dict:
        per_chunk = {
            cid: out.get("keywords", []) for cid, out in prior["4_keywords"].outputs.items()
        }
        raw = sorted({k for ks in per_chunk.values() for k in ks})
        mapping = {k: clean_keyword(k) for k in raw}            # raw -> cleaned ('' = dropped)
        cleaned = {
            cid: sorted({mapping[k] for k in ks if mapping.get(k)})
            for cid, ks in per_chunk.items()
        }
        vocab = sorted({v for v in mapping.values() if v})
        return {"raw": per_chunk, "mapping": mapping, "final": vocab, "cleaned": cleaned}
