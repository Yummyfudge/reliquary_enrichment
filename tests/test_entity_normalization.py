from __future__ import annotations

"""Acceptance tests for EntityNormalizationPass (brief §5.2/§5.4 #2, build step 5).

Driven by REAL surface variants mined from the frozen 131-chunk slice (NOT invented strings) — the
only way to catch the over/under-merge the messy corpus actually contains. The contract:
  * surface variants of the SAME entity collapse to ONE node (deterministic canonicalizers);
  * genuinely-ambiguous same-type entities are FLAGGED, NEVER merged (over-merge is the
    highest-severity failure — a wrong merge corrupts a shared codex node, and provenance is the
    mission).
"""

from types import SimpleNamespace

from reliquary_enrichment.entities import EntityResolver
from reliquary_enrichment.multipass.pass_base import ChunkRef, PassContext, PassResult
from reliquary_enrichment.multipass.passes.pass2_9_normalize import EntityNormalizationPass
from tests.fakes.fake_stores import FakeEntityStore


class _RecStore:
    def __init__(self, recs):
        self._r = recs

    def get(self, rid):
        return self._r.get(rid)


class _FakeModel:
    def __init__(self, reply="[]"):
        self.reply, self.calls = reply, []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.reply, 1


def _rec(**kw):
    kw.setdefault("actor", None)
    kw.setdefault("event_date", None)
    kw.setdefault("fields", {})
    return SimpleNamespace(**kw)


def _run(records, model=None):
    store = _RecStore(records)
    p3 = PassResult("3_fillvalues", {"c": {"record_ids": list(records)}})
    ctx = PassContext(
        model=model or _FakeModel(), model_name="f",
        extras={"entity_resolver": EntityResolver(FakeEntityStore()), "record_store": store},
    )
    return EntityNormalizationPass().process_all([ChunkRef("c", "t")], {"3_fillvalues": p3}, ctx)


# --- REAL date variants collapse (US M/D/Y; 2-digit + zero-pad differences) -------------
def test_real_date_variants_resolve_to_one_node():
    recs = {f"r{i}": _rec(event_date=s) for i, s in enumerate(("12/04/2023", "12/4/23", "12/04/23"))}
    out = _run(recs)
    ids = set(out["mapping"].values())
    assert len(ids) == 1                                      # ONE date node for all three forms
    (eid,) = ids
    assert out["final"][eid]["canonical"] == "2023-12-04"
    assert set(out["final"][eid]["surfaces"]) == {"12/04/2023", "12/4/23", "12/04/23"}


# --- REAL diagnosis codes: full-width OCR collapses; distinct codes do NOT ---------------
def test_real_code_fullwidth_collapses_distinct_stays_distinct():
    recs = {
        "r1": _rec(fields={"code": "F06.4"}),
        "r2": _rec(fields={"code": "F0６.４"}),   # full-width OCR digits (U+FF16/U+FF14)
        "r3": _rec(fields={"code": "f06.4"}),
        "r4": _rec(fields={"code": "F07.4"}),     # genuinely distinct code
    }
    out = _run(recs)
    canon_to_ids: dict[str, set] = {}
    for eid, info in out["final"].items():
        canon_to_ids.setdefault(info["canonical"], set()).add(eid)
    assert len(canon_to_ids["F06.4"]) == 1                   # F06.4 / full-width / f06.4 -> ONE node
    assert "F07.4" in canon_to_ids
    assert len(canon_to_ids) == 2                            # exactly two code nodes (no over-merge)


# --- REAL JoAnn variants: whitespace collapses; residuals FLAGGED, never merged ----------
def test_joann_whitespace_collapses_residuals_flagged_not_merged():
    recs = {f"r{i}": _rec(actor=s) for i, s in enumerate(("JoAnn F.", "JoAnn\nF.", "Jo Ann F.", "JoAnn"))}
    model = _FakeModel('[["JoAnn F.","Jo Ann F."],["JoAnn F.","JoAnn"]]')
    out = _run(recs, model=model)
    # "JoAnn F." and "JoAnn\nF." -> ONE node (whitespace/newline collapse)
    assert out["mapping"]["JoAnn F."] == out["mapping"]["JoAnn\nF."]
    # but "Jo Ann F." (internal space) and "JoAnn" (no surname) stay DISTINCT — never silently merged
    assert len({out["mapping"][s] for s in ("JoAnn F.", "Jo Ann F.", "JoAnn")}) == 3
    flagged = {tuple(f["candidates"]) for f in out["flagged_merges"]}
    assert ("Jo Ann F.", "JoAnn F.") in flagged              # LLM candidate, FLAGGED for curation
    assert all(f["action"] == "flag-for-curation" for f in out["flagged_merges"])


def test_residual_flag_never_merges_even_when_llm_says_same():
    # over-merge guard: even if the LLM pairs them, the entities are NOT collapsed.
    recs = {"r1": _rec(actor="B. Smith"), "r2": _rec(actor="Bruce Smith")}
    out = _run(recs, model=_FakeModel('[["B. Smith","Bruce Smith"]]'))
    assert out["mapping"]["B. Smith"] != out["mapping"]["Bruce Smith"]   # TWO nodes, never merged
    assert {tuple(f["candidates"]) for f in out["flagged_merges"]} == {("B. Smith", "Bruce Smith")}


def test_flagged_merges_deduped_against_spammy_model():
    # a model that repeats the same pair (any order) must not bloat flagged_merges — and never merges.
    recs = {"r1": _rec(actor="B. Smith"), "r2": _rec(actor="Bruce Smith")}
    model = _FakeModel('[["B. Smith","Bruce Smith"],["B. Smith","Bruce Smith"],["Bruce Smith","B. Smith"]]')
    out = _run(recs, model=model)
    assert out["mapping"]["B. Smith"] != out["mapping"]["Bruce Smith"]   # still distinct
    assert len(out["flagged_merges"]) == 1                              # deduped


# --- REAL provision variants ------------------------------------------------------------
def test_real_provision_variants_distinct_and_flaggable():
    recs = {
        "r1": _rec(fields={"provision": "Mental Health limitation"}),
        "r2": _rec(fields={"provision": "24 month limitation"}),
        "r3": _rec(fields={"provision": "24 months"}),
    }
    out = _run(recs, model=_FakeModel('[["24 month limitation","24 months"]]'))
    assert len(set(out["mapping"].values())) == 3            # three distinct provision nodes
    assert ("24 month limitation", "24 months") in {tuple(f["candidates"]) for f in out["flagged_merges"]}


# --- buildability + glass box -----------------------------------------------------------
def test_normalization_consumes_pass3_record_ids():
    out = _run({"r1": _rec(actor="manager B. Smith")})
    assert out["raw"]["c"] == [["actor", "manager B. Smith"]]          # §7: reads prior["3_fillvalues"]
    assert set(out) == {"raw", "mapping", "final", "flagged_merges"}   # glass-box shape
