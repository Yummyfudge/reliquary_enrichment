from __future__ import annotations

"""Acceptance tests for EntityResolver canonicalizers (brief §5.2, §10.1, build step 3).

The 2.9-slot normalization needs REAL per-type canonicalizers (date->ISO-8601, code, location,
document, stronger actor) so surface variants of the SAME entity collapse to ONE node — the
CRQ-001 dedupe the old minimal normalization missed. But the alias-not-merge contract is
inviolable: genuinely-ambiguous identities (B. Smith vs Bruce Smith; an ambiguous all-numeric
date) must NEVER silently collapse. resolve_or_create's body stays verbatim; only what
`canonical = normalize(surface)` produces changes.
"""

from reliquary_enrichment.entities import (
    EntityResolver,
    normalize_code,
    normalize_date,
    _NORMALIZERS,
)
from tests.fakes.fake_stores import FakeEntityStore


# --- date -> ISO-8601 ------------------------------------------------------

def test_date_canonicalizes_known_variants_to_iso():
    for surface in ("2025-02-18", "02/18/2025", "Feb 18 2025", "February 18, 2025", "Feb 18, 2025"):
        assert normalize_date(surface) == "2025-02-18", surface


def test_date_ambiguous_numeric_is_not_guessed():
    # both components <= 12 -> genuinely ambiguous (M/D vs D/M) -> NO silent guess.
    out = normalize_date("03/02/2025")
    assert out != "2025-03-02" and out != "2025-02-03"
    assert out == "03/02/2025"  # conservative: surface kept, flagged for curation downstream


def test_date_unparseable_returns_surface_never_raises():
    assert normalize_date("sometime last spring") == "sometime last spring"


# --- code ------------------------------------------------------------------

def test_code_canonicalizes_case_and_whitespace():
    assert normalize_code("f06.4") == "F06.4"
    assert normalize_code("  f06.4 ") == "F06.4"
    assert normalize_code("F 06.4") == "F06.4"


def test_normalizers_cover_the_new_types():
    for t in ("actor", "date", "code", "location", "document"):
        assert t in _NORMALIZERS


# --- resolve_or_create: dedup the SAME entity, never merge DISTINCT ones ----

def test_date_variants_resolve_to_one_node_with_alias():
    r = EntityResolver(FakeEntityStore())
    e1 = r.resolve_or_create("date", "Feb 18 2025", first_seen_record="rec-1")
    e2 = r.resolve_or_create("date", "2025-02-18", first_seen_record="rec-2")
    assert e1.entity_id == e2.entity_id            # ONE node
    assert e1.canonical == "2025-02-18"
    assert "Feb 18 2025" in e1.aliases             # variant learned, not merged-away


def test_code_variants_resolve_to_one_node():
    r = EntityResolver(FakeEntityStore())
    a = r.resolve_or_create("code", "f06.4", first_seen_record="rec-1")
    b = r.resolve_or_create("code", "F06.4", first_seen_record="rec-2")
    assert a.entity_id == b.entity_id and a.canonical == "F06.4"


def test_actor_distinct_names_are_NOT_merged():
    # alias-not-merge: a short form and a full name are DIFFERENT nodes (curation, never collapse).
    r = EntityResolver(FakeEntityStore())
    a = r.resolve_or_create("actor", "B. Smith", first_seen_record="rec-1")
    b = r.resolve_or_create("actor", "Bruce Smith", first_seen_record="rec-2")
    assert a.entity_id != b.entity_id


def test_actor_whitespace_variants_collapse():
    r = EntityResolver(FakeEntityStore())
    a = r.resolve_or_create("actor", "B.  Smith", first_seen_record="rec-1")
    b = r.resolve_or_create("actor", "B. Smith", first_seen_record="rec-2")
    assert a.entity_id == b.entity_id


# --- adversarial-review regressions (codex-steps1-3 review) -----------------

def test_date_non_month_word_is_not_parsed_as_date():
    # 'Marbles' starts with 'Mar' but is NOT a month -> must NOT become a date (silent over-merge).
    assert normalize_date("Marbles 5 2025") == "Marbles 5 2025"
    r = EntityResolver(FakeEntityStore())
    real = r.resolve_or_create("date", "March 5 2025", first_seen_record="r1")
    junk = r.resolve_or_create("date", "Marbles 5 2025", first_seen_record="r2")
    assert real.entity_id != junk.entity_id  # distinct nodes — no silent merge


def test_date_year_first_nondash_separators_canonicalize():
    # year-first, 4-digit year, only the separator differs -> unambiguous, must reach ISO.
    assert normalize_date("2025/02/18") == "2025-02-18"
    assert normalize_date("2025.02.18") == "2025-02-18"


def test_date_mdy_dot_separator_canonicalizes():
    assert normalize_date("02.18.2025") == "2025-02-18"


def test_full_month_names_still_canonicalize():
    # the strict month-token fix must not regress real month names/abbreviations.
    for surface in ("March 5 2025", "Mar 5 2025", "Sept 9 2025", "September 9 2025"):
        assert normalize_date(surface).startswith("2025-"), surface
