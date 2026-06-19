from __future__ import annotations

"""Tests for the multipass framework: Pass 1 parsing, the cross-pass 5-min heartbeat, and
glass-box state capture. No lane/DB — the model is a fake Completer."""

import json

from reliquary_enrichment.multipass.inputs import page_range_from_filename
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.passes.pass1_prose import Pass1Prose, parse_prose_label
from reliquary_enrichment.multipass.passes.pass2_objecttypes import Pass2ObjectTypes, parse_type_list
from reliquary_enrichment.multipass.passes.pass2_9_consolidate import Pass2_9Consolidate, parse_consolidation
from reliquary_enrichment.multipass.confidence import ConfidencePlateau
from reliquary_enrichment.multipass.passes.pass3_fillvalues import Pass3FillValues
from reliquary_enrichment.multipass.pipeline import Pipeline


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
def test_parse_type_list_normalizes_and_dedups():
    assert parse_type_list('["Status Change","status_change","date"]') == ["status_change", "date"]
    assert parse_type_list('noise ["actor",{"name":"Task Note"}] tail') == ["actor", "task_note"]
    assert parse_type_list("not json") == []


def test_pass2_process_chunk():
    ctx = PassContext(model=FakeCompleter('["date","Actor"]', tokens=5), model_name="f")
    out, toks = Pass2ObjectTypes().process_chunk(ChunkRef("c", "t"), {}, ctx)
    assert out == {"object_types": ["date", "actor"]} and toks == 5


def test_parse_consolidation_maps_every_raw_type():
    canon, mapping = parse_consolidation(
        '{"canonical":["status_change"],"mapping":{"status_update":"status_change"}}',
        ["status_update", "date"])
    assert mapping["status_update"] == "status_change"
    assert mapping["date"] == "date"               # filled by identity fallback
    canon2, map2 = parse_consolidation("junk", ["a", "b"])
    assert map2 == {"a": "a", "b": "b"} and set(canon2) == {"a", "b"}


def test_pass2_9_keeps_raw_final_mapping():
    prior = {"2_objecttypes": PassResult("2_objecttypes", {
        "c1": {"object_types": ["status_change", "date"]},
        "c2": {"object_types": ["status_update"]}})}
    ctx = PassContext(model=FakeCompleter(
        '{"canonical":["status_change","date"],"mapping":'
        '{"status_change":"status_change","status_update":"status_change","date":"date"}}'),
        model_name="f")
    state = Pass2_9Consolidate().process_all([ChunkRef("c1", "x"), ChunkRef("c2", "y")], prior, ctx)
    assert set(state) == {"raw", "raw_types", "final", "mapping"}
    assert state["mapping"]["status_update"] == "status_change"
    assert all(t in state["mapping"] for t in state["raw_types"])   # every raw type mapped


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


# --- Pass 3 fill-values loop ----------------------------------------------------------
def test_pass3_grounded_on_first_attempt():
    pr = FakeProposer([({"confidence": 0.9, "record_type": "x"}, 10)])
    gr = FakeGrounder([{"ok": True, "record_id": "r1"}])
    out, toks = Pass3FillValues().process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] and out["record_id"] == "r1" and out["attempts"] == 1 and toks == 10


def test_pass3_bounce_then_grounded_threads_judge_feedback():
    pr = FakeProposer([({"confidence": 0.6}, 5), ({"confidence": 0.8}, 6)])
    gr = FakeGrounder([{"ok": False, "detail": "date drifted", "reason_code": "ungrounded_fact"},
                       {"ok": True, "record_id": "r2"}])
    out, toks = Pass3FillValues().process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] and out["attempts"] == 2 and toks == 11
    assert pr.feedbacks == [None, "date drifted"]      # judge feedback shaped the retry


def test_pass3_plateau_gives_up_judge_verdict_stands():
    pr = FakeProposer([({"confidence": 0.6}, 5), ({"confidence": 0.61}, 5)])  # 0.61 < 0.6+0.05
    gr = FakeGrounder([{"ok": False, "detail": "no", "reason_code": "ungrounded_fact"}])
    out, _ = Pass3FillValues(epsilon=0.05).process_chunk(ChunkRef("c", "t"), {}, _pass3_ctx(pr, gr))
    assert out["grounded"] is False and out["attempts"] == 2
    assert out["confidence_trajectory"] == [0.6, 0.61]
    assert out["reason_code"] == "ungrounded_fact"      # the last judge verdict stands


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
