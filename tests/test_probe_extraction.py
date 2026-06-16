from __future__ import annotations

"""Unit tests for the extraction driver — proposal parsing + quote location (no network)."""

from reliquary_enrichment.probe.extraction import locate_quote, parse_proposals

TEXT = "Supervisor B. Smith reversed the prior approval on 2025-02-18."


def test_parse_plain_array():
    p = parse_proposals('[{"quote":"B. Smith reversed","record_type":"status_change",'
                        '"tier":"fact","fields":{"x":1},"actor":"B. Smith","event_date":"2025-02-18"}]')
    assert len(p) == 1 and p[0].quote == "B. Smith reversed"
    assert p[0].actor == "B. Smith" and p[0].tier == "fact"


def test_parse_embedded_and_records_wrapper():
    assert parse_proposals('here: {"records":[{"quote":"x","record_type":"t"}]} ok')[0].quote == "x"
    assert parse_proposals('noise [{"quote":"y","record_type":"t"}] tail')[0].quote == "y"


def test_parse_drops_items_without_quote_and_junk():
    p = parse_proposals('[{"record_type":"t"},{"quote":"  ","record_type":"t"},'
                        '{"quote":"keep","record_type":"t"}]')
    assert [x.quote for x in p] == ["keep"]
    assert parse_proposals("not json at all") == []


def test_parse_null_actor_becomes_none_and_bad_tier_defaults():
    p = parse_proposals('[{"quote":"q","record_type":"t","actor":"null","tier":"guess"}]')
    assert p[0].actor is None and p[0].tier == "fact"


def test_locate_exact():
    assert locate_quote(TEXT, "B. Smith reversed") == (11, 28)
    assert TEXT[11:28] == "B. Smith reversed"


def test_locate_whitespace_tolerant():
    # quote with collapsed/odd spacing still locates a real span in the original text
    s, e = locate_quote(TEXT, "B. Smith    reversed")
    assert TEXT[s:e] == "B. Smith reversed"


def test_locate_miss_returns_none():
    assert locate_quote(TEXT, "B. Smith APPROVED") is None
    assert locate_quote(TEXT, "") is None
