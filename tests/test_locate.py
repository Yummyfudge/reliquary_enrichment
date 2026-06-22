from __future__ import annotations

"""Unit tests for multipass/locate.py (rehomed from the deleted probe/ in §13).

locate_quote is the "code COPIES" half of the grounding law: it turns the model's pointed quote into
offsets into the ORIGINAL text. Offsets must index the original bytes so the stored span stays
byte-exact; an unlocatable quote returns None (the proposal is dropped, never stored).
"""

from reliquary_enrichment.multipass.locate import locate_quote


def test_locate_exact_match_returns_original_offsets():
    text = "Supervisor B. Smith reversed the approval on 2025-02-18."
    s, e = locate_quote(text, "B. Smith reversed")
    assert text[s:e] == "B. Smith reversed"


def test_locate_whitespace_tolerant_indexes_original_bytes():
    text = "manager  B.  Smith\nreviewed the claim"
    s, e = locate_quote(text, "manager B. Smith reviewed")
    assert text[s:e] == "manager  B.  Smith\nreviewed"   # spans the ORIGINAL whitespace/newline


def test_locate_not_found_returns_none():
    assert locate_quote("hello world", "goodbye") is None


def test_locate_empty_or_blank_quote_returns_none():
    assert locate_quote("anything", "") is None
    assert locate_quote("anything", "   ") is None
