from __future__ import annotations

"""Full codex-refactor pipeline over FAKES (no lane/DB) — the §7 chain end to end (brief §10, build 10).

Drives all_passes() through the real Pipeline with a prompt-routing fake model + a GROUNDED fake judge,
every service wired to in-memory fakes. Proves the integration the real run will exercise:
  * all seven §7 passes run and capture state;
  * Pass 3 grounds typed-entity records -> normalization resolves the codex entities;
  * the discriminative pass keeps B. Smith a DISCRIMINATOR (the fixture is sized so max grounded degree is
    7 -> cutoff 3 > B. Smith's degree 2) and flags the ubiquitous date a THEME;
  * the cross-chunk linker forms the gold edge between the two B. Smith records (the theme is stoplisted);
  * the gold-note FLOOR passes; the gated MeaningWriter stores the discriminative local fact;
  * the produced codex is WALKABLE — CodexWalk reaches the gold record and the formed link is a grounded,
    cited, walkable edge.
The REAL-CORPUS version of this (gold edge from the real linker, walk-reach-via-links) is build 10b.
"""

import json

from reliquary_enrichment.codex_walk import CodexWalk
from reliquary_enrichment.entities import EntityResolver, EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.meaning_writer import MeaningWriter
from reliquary_enrichment.multipass.cli import all_passes
from reliquary_enrichment.multipass.fill_wiring import make_grounder, make_proposer
from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID, gold_floor_from_results
from reliquary_enrichment.multipass.gate import read_gate
from reliquary_enrichment.multipass.link_wiring import make_link_proposer
from reliquary_enrichment.multipass.meaning_wiring import make_meaning_proposer
from reliquary_enrichment.multipass.pass_base import ChunkRef, PassContext
from reliquary_enrichment.multipass.pipeline import Pipeline
from reliquary_enrichment.write_enrichment import WriteEnrichment
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge
from tests.fakes.fake_meaning_store import FakeMeaningStore
from tests.fakes.fake_stores import FakeEntityStore, FakeLinkStore, FakeRecordStore

GOLD_TEXT = "Body Reviewed with manager B. Smith: Place claim back to a Mental Health limitation"
C2 = "22222222-2222-2222-2222-222222222222"
C2_TEXT = "Follow-up: manager B. Smith reviewed the claim file status."
GOLD_MEANING = "Manager B. Smith placed the claim back under the Mental Health limitation"
# 12 filler chunks share ONE date -> max grounded degree 12 -> theme cutoff 5, leaving B. Smith (degree 2)
# a discriminator with MARGIN 3 (not a knife-edge: +/-1 filler keeps cutoff 4-5, still > 2). The robust
# real-corpus calibration (max degree ~40, cutoff stable across fractions 0.1-0.8) lives in
# test_discriminative.py; here the count just has to clear the theme-cutoff floor of 2 with room to spare.
FILLERS = [(f"filler-chunk-{i}", f"Status note dated 2025-01-01, reference item number {i}.")
           for i in range(1, 13)]
ALL = [(GOLD_CHUNK_ID, GOLD_TEXT), (C2, C2_TEXT), *FILLERS]


class _RoutingFake:
    """One fake model answering each pass by its system prompt; routes Pass 3 by chunk content."""

    def complete(self, system: str, user: str):
        s = system.lower()
        chunk = user.split("CHUNK:\n", 1)[-1].split("\n\nFEEDBACK")[0].strip() if "CHUNK:\n" in user else ""
        has_smith = "B. Smith" in chunk
        if "prose or non_prose" in s:
            return "prose", 1
        if "which of these entity types are present" in s:
            return ('["actor"]' if has_smith else '["date"]'), 1
        if "extract every typed entity" in s:
            if has_smith:
                return json.dumps([{"type": "actor", "surface": "B. Smith", "quote": chunk,
                                    "tier": "fact", "confidence": 0.9}]), 1
            return json.dumps([{"type": "date", "surface": "2025-01-01", "quote": chunk,
                                "tier": "fact", "confidence": 0.9}]), 1
        if "same real-world entity" in s:                          # normalization residual merge
            return "[]", 1
        if "cross-record relation" in s:                           # link proposer
            return json.dumps({"relation": "corroborates", "a_span": "B. Smith", "b_span": "B. Smith",
                               "rationale": "the same manager across two chunks"}), 1
        if "local fact" in s:                                      # meaning proposer
            return json.dumps({"meaning": GOLD_MEANING, "quote": chunk}), 1
        return "prose", 1


def _services(model, fragments):
    rs, es, ls, ms = FakeRecordStore(), FakeEntityStore(), FakeLinkStore(), FakeMeaningStore()
    core = GroundingCore(fragment_reader=fragments, handle_map=HandleMap(), judge=ConstantJudge(Verdict.GROUNDED))
    resolver = EntityResolver(es)
    write_service = WriteEnrichment(core=core, record_store=rs, entity_resolver=resolver)
    extras = {
        "proposer": make_proposer(model), "grounder": make_grounder(write_service, "mp-test"),
        "entity_resolver": resolver, "record_store": rs, "entity_store": es, "link_store": ls,
        "linker": LinkEvents(core=core, record_store=rs, link_store=ls,
                             event_materializer=EventMaterializer(es)),
        "link_proposer": make_link_proposer(model),
        "meaning_writer": MeaningWriter(core=core, meaning_store=ms),
        "meaning_proposer": make_meaning_proposer(model),
        "workstream_id": "mp-test", "meaning_workstream_id": "mp-test-meaning",
    }
    return extras, rs, es, ls, ms


def _run(tmp_path):
    fragments = FakeFragmentReader({cid: Fragment(cid, text, "claim.pdf", 1, "note") for cid, text in ALL})
    model = _RoutingFake()
    extras, rs, es, ls, ms = _services(model, fragments)
    ctx = PassContext(model=model, model_name="fake", extras=extras)
    chunks = [ChunkRef(cid, text) for cid, text in ALL]
    results = Pipeline(passes=all_passes(), chunks=chunks, ctx=ctx, out_dir=str(tmp_path),
                       emit=lambda _l: None).run()
    return results, rs, es, ls, ms


def test_pipeline_builds_codex_floor_passes_meaning_stored_and_walkable(tmp_path):
    results, rs, es, ls, ms = _run(tmp_path)

    # all seven §7 passes captured state
    assert set(results) >= {"1_prose", "2_objecttypes", "3_fillvalues", "2_9_normalize",
                            "discriminative_weight", "cross_chunk_link", "5_meaning"}

    # discriminative classification: B. Smith a DISCRIMINATOR with MARGIN, the date a THEME (CRQ-001 lever)
    disc = results["discriminative_weight"].outputs
    assert disc["theme_cutoff"] == 5 and disc["max_grounded_degree"] == 12
    by_canon = {w["canonical"]: w for w in disc["weights"].values()}
    assert by_canon["B. Smith"]["weight"] == 2 and by_canon["B. Smith"]["is_theme"] is False  # margin 3
    assert by_canon["2025-01-01"]["is_theme"] is True          # ubiquitous -> theme

    # the gold EDGE formed between the two B. Smith records (the theme date is stoplisted as an anchor)
    link_out = results["cross_chunk_link"].outputs
    assert link_out["n_links"] >= 1
    assert "2025-01-01" in link_out["dry_run"]["stoplisted_anchors"]

    # the gold-note FLOOR passes (actor B. Smith + reversal content on the gold chunk's own text)
    floor = gold_floor_from_results(rs, results)
    assert floor["passed"] is True and floor["has_b_smith_actor"] and floor["has_reversal"]

    # the gated MeaningWriter stored the discriminative local fact; filler chunks (only a THEME date) are
    # REJECTED — only discriminative meanings reach enrichment_meaning (the embedded side).
    assert ms.meanings.get(GOLD_CHUNK_ID) == GOLD_MEANING
    assert all("filler-chunk" not in cid for cid in ms.meanings)

    # the gate reads discriminative-substance coverage
    gate = read_gate(results, record_store=rs, entity_store=es)
    assert gate.chunks_grounded >= 2

    # THE CODEX IS WALKABLE on PIPELINE-PRODUCED data: (1) the gold record is reachable from a B. Smith
    # chunk via the codex; (2) the formed cross-chunk LINK is itself a grounded, cited, walkable edge off
    # the gold record. NOTE: assemble() here reaches via the shared B. Smith entity (mentions->cites), NOT
    # over the link — genuine link-ONLY reach (no shared entity) is proven in test_codex_walk.py, and the
    # real-corpus reach-via-links is build 10b.
    gold_rec = next(r for r in rs.records_by_chunk(GOLD_CHUNK_ID) if r.actor == "B. Smith")
    walk = CodexWalk(record_store=rs, entity_store=es, link_store=ls)
    res = walk.assemble(target_record=gold_rec.record_id, seed_chunk=C2)
    assert res.reached and all(h.cited for h in res.path)
    link_hops = [h for h in walk.neighbors(gold_rec.record_id) if h.kind == "link"]
    assert link_hops and all(h.cited and h.relation == "corroborates" for h in link_hops)  # link walkable
