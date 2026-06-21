from __future__ import annotations

"""Tests for the multipass framework: Pass 1 parsing, the cross-pass 5-min heartbeat, and
glass-box state capture. No lane/DB — the model is a fake Completer."""

import json

from reliquary_enrichment.multipass.inputs import page_range_from_filename
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.passes.pass1_prose import Pass1Prose, parse_prose_label
from reliquary_enrichment.multipass.passes.pass2_objecttypes import Pass2ObjectTypes, parse_type_list
from reliquary_enrichment.multipass.passes.pass2_9_normalize import EntityNormalizationPass
from reliquary_enrichment.multipass.confidence import ConfidencePlateau
from reliquary_enrichment.multipass.passes.pass3_fillvalues import Pass3FillValues
from reliquary_enrichment.multipass.cli import all_passes
from reliquary_enrichment.multipass.gate import read_gate
from reliquary_enrichment.multipass.parsing import EntityProposal, safe_json_array, safe_json_object
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES
from reliquary_enrichment.multipass.pipeline import Pipeline


class _RaisingPass(Pass):
    name = "boom"
    per_chunk = True

    def process_chunk(self, chunk, prior, ctx):
        if chunk.chunk_id == "bad":
            raise ValueError("kaboom")
        return {"ok": True}, 1


# --- robustness: defensive parsing never raises; pipeline contains per-chunk errors ---
def test_safe_json_array_never_raises_on_bad_fallback():
    # the exact crash class: a regex-extractable [...] that is itself invalid JSON
    assert safe_json_array('["a": "b"]') == []
    assert safe_json_array("noise [not, valid, json,] tail") == []
    assert safe_json_array('["ok","good"]') == ["ok", "good"]
    assert parse_type_list('["status": "x"]') == []          # pass-2 parser stays alive


def test_safe_json_object_never_raises():
    assert safe_json_object("{bad json") is None
    assert safe_json_object('text {"k": 1} more') == {"k": 1}


def test_pipeline_contains_per_chunk_errors(tmp_path):
    chunks = [ChunkRef("good", "x"), ChunkRef("bad", "y"), ChunkRef("good2", "z")]
    ctx = PassContext(model=FakeCompleter(), model_name="m")
    lines: list[str] = []
    res = Pipeline(passes=[_RaisingPass()], chunks=chunks, ctx=ctx, out_dir=str(tmp_path),
                   emit=lines.append, status_interval_s=999).run()
    out = res["boom"].outputs
    assert out["good"] == {"ok": True} and out["good2"] == {"ok": True}   # neighbors unaffected
    assert "error" in out["bad"]                                          # bad chunk contained
    assert any("[skip]" in l for l in lines) and any("COMPLETE" in l for l in lines)


def test_page_range_from_filename():
    assert page_range_from_filename("Aflac_claim_file_400-426.pdf") == ("Aflac_claim_file_400-426", 400, 426)
    assert page_range_from_filename("Aflac_claim_file_575-580.pdf") == ("Aflac_claim_file_575-580", 575, 580)


class FakeCompleter:
    def __init__(self, reply="prose", tokens=10):
        self.reply, self.tokens, self.calls = reply, tokens, []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.reply, self.tokens


class FakeWholePass(Pass):
    name = "2_9_fake"
    per_chunk = False

    def process_all(self, chunks, prior, ctx):
        return {"n_chunks": len(chunks), "prior_passes": sorted(prior)}


class FakeProposer:
    def __init__(self, script):
        self.script = list(script)
        self.feedbacks = []

    def __call__(self, chunk, schema, feedback):
        self.feedbacks.append(feedback)
        return self.script.pop(0)


class FakeGrounder:
    def __init__(self, results):
        self.results = list(results)
        self.seen = []

    def __call__(self, proposal, chunk):
        self.seen.append(proposal)
        return self.results.pop(0)


def _pass3_ctx(proposer, grounder):
    return PassContext(model=FakeCompleter(), model_name="f",
                       extras={"proposer": proposer, "grounder": grounder})


# --- Pass 1 parsing -------------------------------------------------------------------
def test_parse_prose_label():
    assert parse_prose_label("prose") == "prose"
    assert parse_prose_label("Prose.") == "prose"
    assert parse_prose_label("non_prose") == "non_prose"
    assert parse_prose_label("non-prose") == "non_prose"
    assert parse_prose_label("Non prose") == "non_prose"
    assert parse_prose_label("gibberish") == "non_prose"   # default conservative


def test_pass1_classifies_each_chunk():
    ctx = PassContext(model=FakeCompleter("non_prose", tokens=7), model_name="fake")
    p = Pass1Prose()
    out, toks = p.process_chunk(ChunkRef("c1", "Name: Smith\nDOB: ..."), {}, ctx)
    assert out == {"label": "non_prose"} and toks == 7


# --- Pass 2 object-types + 2.9 consolidate --------------------------------------------
def test_parse_type_list_keeps_only_closed_vocab():
    assert parse_type_list('["date","Actor","status_change","code"]') == ["date", "actor", "code"]
    assert parse_type_list('["Long COVID","reversal"]') == []      # off-vocab dropped
    assert parse_type_list("not json") == []


def test_pass2_lists_present_closed_vocab_types():
    ctx = PassContext(model=FakeCompleter('["date","Actor","denial_reason"]', tokens=5), model_name="f")
    out, toks = Pass2ObjectTypes().process_chunk(ChunkRef("c", "t"), {}, ctx)
    assert out == {"object_types": ["date", "actor"]} and toks == 5   # denial_reason dropped (off-vocab)


# --- §7 pass sequence: the literal run order + codex-first positioning -----------------
def test_all_passes_is_the_section7_literal_order():
    assert [p.name for p in all_passes()] == [
        "1_prose", "2_objecttypes", "3_fillvalues", "2_9_normalize",
        "discriminative_weight", "cross_chunk_link", "5_meaning"]


def test_normalization_is_positioned_after_pass3_codex_first():
    # the "2.9" SLOT must run AFTER Pass 3 (Pass 3 grounds instances; normalization resolves them).
    names = [p.name for p in all_passes()]
    assert names.index("2_9_normalize") > names.index("3_fillvalues")
    assert names.index("cross_chunk_link") > names.index("discriminative_weight")  # linker needs themes
    assert names[-1] == "5_meaning"                                                # meaning is last
    # the thrown passes are GONE from the sequence
    assert not any(n in names for n in ("4_keywords", "4_9_cleanup", "2_9_consolidate"))


class _FakeResolver:
    def resolve_or_create(self, etype, surface, *, first_seen_record=None):
        from reliquary_enrichment.models import Entity
        return Entity(entity_type=etype, canonical=surface)


def test_normalization_buildability_requires_pass3_in_prior():
    # §7 buildability guard: EntityNormalizationPass reads prior["3_fillvalues"] — positional codex-first.
    from tests.fakes.fake_stores import FakeRecordStore
    seen = {}
    class _Probe(dict):
        def get(self, k, default=None):
            seen[k] = True
            return super().get(k, default)
    prior = _Probe({"3_fillvalues": PassResult("3_fillvalues", {"c": {"record_ids": []}})})
    ctx = PassContext(model=FakeCompleter("[]"), model_name="f",
                      extras={"entity_resolver": _FakeResolver(), "record_store": FakeRecordStore()})
    EntityNormalizationPass().process_all([ChunkRef("c", "x")], prior, ctx)
    assert seen.get("3_fillvalues") is True   # it sourced Pass 3's record_ids, not an earlier slot


# --- confidence-plateau (Pass 3 retry bound) -----------------------------------------
def test_plateau_first_attempt_never_stops():
    assert ConfidencePlateau(0.05).record(0.3) is False


def test_plateau_continue_when_beats_best_then_stop():
    p = ConfidencePlateau(0.05)
    assert p.record(0.60) is False     # first
    assert p.record(0.70) is False     # beats best by >= 0.05 -> continue
    assert p.record(0.72) is True      # 0.72 < 0.70+0.05 -> plateau


def test_plateau_beats_best_so_far_not_previous():
    p = ConfidencePlateau(0.05)
    p.record(0.80)                     # best = 0.80
    assert p.record(0.50) is True      # dip; 0.50 < 0.85 -> plateau (best-so-far survives the dip)


def test_plateau_bound_emerges_from_epsilon():
    p = ConfidencePlateau(0.10)
    cont = 0
    for c in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0]:
        if p.record(c):
            break
        cont += 1
    assert cont <= 11                  # ~1/epsilon + first; bounded, no magic count


# --- Pass 3 multi-record fill-values loop ---------------------------------------------
def _P(type_, quote, confidence=0.9):
    return EntityProposal(type=type_, quote=quote, surface=quote, confidence=confidence)


def test_pass3_grounds_a_batch_of_typed_entities():
    pr = FakeProposer([([_P("actor", "B. Smith"), _P("date", "2025-02-18")], 10)])
    gr = FakeGrounder([{"ok": True, "record_id": "r-actor"}, {"ok": True, "record_id": "r-date"}])
    out, toks = Pass3FillValues().process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] and out["n_grounded"] == 2 and out["attempts"] == 1 and toks == 10
    assert set(out["record_ids"]) == {"r-actor", "r-date"}


def test_pass3_bounce_then_grounded_threads_judge_feedback():
    pr = FakeProposer([([_P("date", "bad", 0.6)], 5), ([_P("date", "2025-02-18", 0.8)], 6)])
    gr = FakeGrounder([{"ok": False, "detail": "date drifted", "reason_code": "ungrounded_fact"},
                       {"ok": True, "record_id": "r2"}])
    out, toks = Pass3FillValues().process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] and out["n_grounded"] == 1 and out["record_ids"] == ["r2"]
    assert out["attempts"] == 2 and toks == 11
    assert pr.feedbacks == [None, "ungrounded_fact: date drifted"]   # judge feedback shaped the retry


def test_pass3_plateau_gives_up_on_grounded_fraction():
    pr = FakeProposer([([_P("date", "x", 0.6)], 5), ([_P("date", "x", 0.61)], 5)])
    gr = FakeGrounder([{"ok": False, "detail": "no", "reason_code": "ungrounded_fact"},
                       {"ok": False, "detail": "no", "reason_code": "ungrounded_fact"}])
    out, _ = Pass3FillValues(epsilon=0.05).process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] is False and out["n_grounded"] == 0 and out["attempts"] == 2
    assert out["confidence_trajectory"] == [0.0, 0.0]      # grounded-FRACTION trajectory
    assert out["reason_code"] == "ungrounded_fact"


def test_pass3_schema_from_vocabulary_narrowed_by_pass2_not_consolidate():
    seen: list = []
    def proposer(chunk, schema, feedback):
        seen.append(list(schema)); return [], 1
    prior = {"2_objecttypes": PassResult("2_objecttypes", {"c": {"object_types": ["actor", "date"]}})}
    Pass3FillValues().process_chunk(ChunkRef("c", "t"), prior, _pass3_ctx(proposer, FakeGrounder([])))
    assert seen[0] == ["actor", "date"]      # narrowed by Pass 2, NOT read from 2_9_consolidate


def test_pass3_schema_falls_back_to_full_vocab_when_pass2_absent():
    seen: list = []
    def proposer(chunk, schema, feedback):
        seen.append(set(schema)); return [], 1
    Pass3FillValues().process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(proposer, FakeGrounder([])))
    assert seen[0] == ENTITY_TYPES           # no Pass 2 -> the full closed vocabulary


# --- Pass 4 (keywords/cleanup) is GONE; Pass 5 (MeaningWriterPass) lives in test_meaning_pass.py ---


# --- GATE (per-chunk faithfulness) ----------------------------------------------------
def test_read_gate_faithfulness_from_pass3():
    results = {"3_fillvalues": PassResult("3_fillvalues", {
        "c1": {"grounded": True, "reason_code": None, "attempts": 1},
        "c2": {"grounded": False, "reason_code": "ungrounded_fact", "attempts": 3},
        "c3": {"grounded": True, "attempts": 2}})}
    g = read_gate(results)
    assert g.chunks_total == 3 and g.chunks_grounded == 2 and g.chunks_ungrounded == 1
    assert g.faithfulness_rate == round(2 / 3, 4)
    assert g.per_chunk["c2"]["reason_code"] == "ungrounded_fact"


# --- pipeline heartbeat (cross-pass) + glass-box persistence -------------------------
def test_pipeline_heartbeat_and_state_capture(tmp_path):
    chunks = [ChunkRef("c1", "x"), ChunkRef("c2", "y")]
    ctx = PassContext(model=FakeCompleter("prose", tokens=100), model_name="big-thinker")
    lines: list[str] = []
    t = [0.0]
    def clk():
        t[0] += 1.0
        return t[0]
    pipe = Pipeline(passes=[Pass1Prose(), FakeWholePass()], chunks=chunks, ctx=ctx,
                    out_dir=str(tmp_path), emit=lines.append, clock=clk, status_interval_s=0.0)
    results = pipe.run()

    # heartbeat: cross-pass format + overall pct (Pass 1 of 2 passes, chunk 1 of 2 -> 25%)
    hb = [l for l in lines if l.startswith("Test running |")]
    assert hb, "expected a 'Test running' heartbeat"
    first = next(l for l in hb if "Chunk 1/2" in l)
    assert "Pass 1/2" in first and "tok/s" in first and "% total" in first
    assert "25% total" in first        # (0*2 + 1) / (2*2) = 25%

    # both passes produced state + persisted (glass box)
    assert set(results) == {"1_prose", "2_9_fake"}
    assert results["1_prose"].outputs["c1"] == {"label": "prose"}
    assert results["2_9_fake"].outputs == {"n_chunks": 2, "prior_passes": ["1_prose"]}
    saved = json.loads((tmp_path / "1_prose.json").read_text())
    assert saved["pass"] == "1_prose" and saved["outputs"]["c2"] == {"label": "prose"}
