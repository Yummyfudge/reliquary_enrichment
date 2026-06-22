from __future__ import annotations

"""MeaningWriterPass (the new Pass 5) — the gated meaning wired into the pass framework (brief §5.4, §7).

The pass assembles each chunk's resolved codex entities (theme-flag from §9), lets the proposer point a
local fact + verbatim span, CODE locates the span, and the gated MeaningWriter grounds/judges/stores. This
verifies the WIRING — the gate's own two-pole calibration lives in test_meaning_writer.py.
"""

import json

from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.meaning_writer import MeaningWriter
from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef
from reliquary_enrichment.multipass.meaning_wiring import make_meaning_proposer
from reliquary_enrichment.multipass.pass_base import ChunkRef, PassContext
from reliquary_enrichment.multipass.passes.pass5_meaning import (
    MeaningWriterPass,
    resolved_entities_for_chunk,
)
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge
from tests.fakes.fake_meaning_store import FakeMeaningStore
from tests.fakes.fake_stores import FakeEntityStore, FakeRecordStore

GOLD_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"
GOLD_TEXT = "Body Reviewed with manager B. Smith: Place claim back to a Mental Health limitation"
GOLD_MEANING = "Manager B. Smith placed the claim back under the Mental Health limitation"


class _ScriptedModel:
    """A model whose meaning reply is fixed; returns the JSON the meaning proposer parses."""

    def __init__(self, meaning: str, quote: str):
        self._reply = json.dumps({"meaning": meaning, "quote": quote})

    def complete(self, system: str, user: str):
        return self._reply, 7


def _ctx_and_stores(*, meaning, quote, is_theme=False, verdict=Verdict.GROUNDED):
    rs, es = FakeRecordStore(), FakeEntityStore()
    smith = Entity(entity_type="actor", canonical="B. Smith"); es.insert(smith)
    es.set_entity_flags(smith.entity_id, weight=2, is_theme=is_theme)
    rs.insert(EnrichmentRecord(
        record_type="actor", tier="fact", source_chunk_id=GOLD_ID, char_start=0, char_end=8,
        evidence_span="B. Smith", provenance_validation={"verdict": "grounded"},
        entity_refs=[EntityRef("actor", smith.entity_id, "actor", "B. Smith")]))
    core = GroundingCore(fragment_reader=FakeFragmentReader({GOLD_ID: Fragment(GOLD_ID, GOLD_TEXT, "d.txt", 1, "note")}),
                         handle_map=HandleMap(), judge=ConstantJudge(verdict))
    store = FakeMeaningStore()
    ctx = PassContext(model=_ScriptedModel(meaning, quote), model_name="f", extras={
        "meaning_writer": MeaningWriter(core=core, meaning_store=store),
        "meaning_proposer": make_meaning_proposer(_ScriptedModel(meaning, quote)),
        "record_store": rs, "entity_store": es,
    })
    return ctx, store


def test_pass_grounds_and_stores_the_gold_local_fact():
    ctx, store = _ctx_and_stores(meaning=GOLD_MEANING, quote=GOLD_TEXT)
    out, tokens = MeaningWriterPass().process_chunk(ChunkRef(GOLD_ID, GOLD_TEXT), {}, ctx)
    assert out["ok"] is True and store.meanings[GOLD_ID] == GOLD_MEANING and tokens == 7


def test_pass_rejects_theme_only_meaning_via_the_gate():
    # B. Smith flagged a THEME -> the meaning names no discriminator -> the gate rejects it.
    ctx, store = _ctx_and_stores(meaning="The claim was reviewed", quote=GOLD_TEXT, is_theme=True)
    out, _ = MeaningWriterPass().process_chunk(ChunkRef(GOLD_ID, GOLD_TEXT), {}, ctx)
    assert out["ok"] is False and out["reason_code"] == "non_discriminative" and store.meanings == {}


def test_pass_drops_unlocatable_quote():
    ctx, store = _ctx_and_stores(meaning=GOLD_MEANING, quote="a span that is not in the chunk at all")
    out, _ = MeaningWriterPass().process_chunk(ChunkRef(GOLD_ID, GOLD_TEXT), {}, ctx)
    assert out["ok"] is False and out["reason_code"] == "locate_miss" and store.meanings == {}


def test_pass_drops_empty_proposal():
    ctx, store = _ctx_and_stores(meaning="", quote="")
    out, _ = MeaningWriterPass().process_chunk(ChunkRef(GOLD_ID, GOLD_TEXT), {}, ctx)
    assert out["ok"] is False and out["reason_code"] == "no_proposal"


def test_resolved_entities_carry_theme_flag_and_type():
    ctx, _ = _ctx_and_stores(meaning=GOLD_MEANING, quote=GOLD_TEXT, is_theme=True)
    resolved = resolved_entities_for_chunk(ctx.extras["record_store"], ctx.extras["entity_store"], GOLD_ID)
    assert resolved == [{"canonical": "B. Smith", "entity_type": "actor", "aliases": [], "is_theme": True}]
