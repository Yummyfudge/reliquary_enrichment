from __future__ import annotations

"""locate_quote — find a candidate's verbatim quote in the source text (code, not the model).

Rehomed into `multipass/` from the retired `probe/` (codex refactor §13). Pass 3's grounder uses this
to turn the model's pointed quote into (char_start, char_end) offsets into the ORIGINAL text — the
"code COPIES" half of the grounding law. A quote that can't be located returns None and that proposal
is dropped, never stored.
"""

import re


def _ws_regex(q: str) -> str:
    """Build a regex matching the quote with any run of whitespace between non-space tokens."""
    parts = [re.escape(tok) for tok in q.split()]
    return r"\s+".join(parts)


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find the candidate's verbatim quote in the source text -> (char_start, char_end).

    Exact match first (the model is asked to copy verbatim). Falls back to a whitespace-normalized
    search so trivial spacing differences still locate a real span (offsets always index the ORIGINAL
    text; the stored span stays byte-exact from source). Returns None if the quote can't be located —
    that proposal is dropped, never stored.
    """
    q = quote.strip()
    if not q:
        return None
    idx = text.find(q)
    if idx != -1:
        return idx, idx + len(q)
    # whitespace-tolerant fallback: match the quote's tokens with any whitespace between.
    m = re.search(_ws_regex(q), text)
    if m:
        return m.start(), m.end()
    return None
