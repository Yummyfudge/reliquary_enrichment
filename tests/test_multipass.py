from __future__ import annotations

"""Tests for the multipass framework: Pass 1 parsing, the cross-pass 5-min heartbeat, and
glass-box state capture. No lane/DB — the model is a fake Completer."""

import json

from reliquary_enrichment.multipass.inputs import page_range_from_filename
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext
from reliquary_enrichment.multipass.passes.pass1_prose import Pass1Prose, parse_prose_label
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
