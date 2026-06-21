from __future__ import annotations

"""v0 end-to-end dry run of the whole codex-refactor pipeline on the scratch DB (no lane).

A prompt-routing fake model drives every §7 pass; Pass 3 grounds real records, normalization resolves the
codex entities, the discriminative pass weighs them, the linker grounds cross-chunk links, and the gated
MeaningWriter stores meanings — all into a probe schema, judged by a fake GROUNDED judge. Validates: all
seven passes run + capture state, the gold-note FLOOR is evaluated, the gate reads faithfulness, the
records AND codex artifacts (entities/links/meaning) export BEFORE drop, isolation.json is populated, the
schema drops. C1 IS the gold chunk so the floor passes end-to-end on the scratch DB.
"""

import json

import pytest

from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.multipass.cli import execute_multipass
from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID
from reliquary_enrichment.multipass.isolation_schema import probe_schema_name
from reliquary_enrichment.postgres.connection import connect, connection_kwargs
from tests.fakes.fake_judge import ConstantJudge

pytestmark = pytest.mark.integration

C1 = GOLD_CHUNK_ID                                    # the gold chunk — so the FLOOR passes end-to-end
C2 = "22222222-2222-2222-2222-222222222222"
T1 = "Reviewed with manager B. Smith: place claim back to a Mental Health limitation on 2025-02-18."
T2 = "Adjuster note: claim returned to long COVID review on 2025-01-05 by the case manager."


def _local_scratch() -> bool:
    kw = connection_kwargs()
    return str(kw.get("host", "")) in ("127.0.0.1", "localhost", "::1") and bool(kw.get("password"))


class PromptRoutingFake:
    """One fake model answering each §7 pass by its system prompt; routes Pass 3 by chunk content."""

    def complete(self, system: str, user: str):
        s = system.lower()
        chunk = user.split("CHUNK:\n", 1)[-1].split("\n\nFEEDBACK")[0].strip() if "CHUNK:\n" in user else ""
        if "prose or non_prose" in s:
            return "prose", 3
        if "which of these entity types are present" in s:
            return ('["actor","provision"]' if "B. Smith" in chunk else '["date"]'), 4
        if "extract every typed entity" in s:
            if "B. Smith" in chunk:                  # gold chunk -> actor (evidence carries the reversal)
                return json.dumps([{"type": "actor", "surface": "B. Smith", "quote": chunk,
                                    "tier": "fact", "confidence": 0.9}]), 8
            return json.dumps([{"type": "date", "surface": "2025-01-05", "quote": chunk,
                                "tier": "fact", "confidence": 0.9}]), 6
        if "same real-world entity" in s:
            return "[]", 2
        if "cross-record relation" in s:
            return json.dumps({"relation": "corroborates", "a_span": "B. Smith", "b_span": "claim",
                               "rationale": "x"}), 4
        if "local fact" in s:
            return json.dumps({"meaning": "Manager B. Smith placed the claim back under the Mental "
                                          "Health limitation", "quote": chunk}), 5
        return "prose", 1


@pytest.fixture()
def seeded(tmp_path):
    if not _local_scratch():
        pytest.skip("multipass e2e runs only against a local scratch DB")
    with connect() as conn, conn.cursor() as cur:
        for cid, text in ((C1, T1), (C2, T2)):
            cur.execute("DELETE FROM context_reliquary.claim_chunks WHERE claim_chunk_id=%s", (cid,))
            cur.execute(
                "INSERT INTO context_reliquary.claim_chunks "
                "(claim_chunk_id, document_name, chunk_type, page_number, segment_index, payload) "
                "VALUES (%s,'c.pdf','x',742,0, jsonb_build_object('chunk_text', %s::text))",
                (cid, text))
    sl = tmp_path / "slice.txt"
    sl.write_text(f"{C1}\n{C2}\n")
    yield sl


def test_multipass_v0_end_to_end(seeded, tmp_path):
    result = execute_multipass(
        label="mpdry", candidate_model="fake-candidate", slice_path=str(seeded),
        out_dir=str(tmp_path), model=PromptRoutingFake(),
        judge=ConstantJudge(Verdict.GROUNDED), drop_after=True)

    gate = result["gate"]
    assert gate["chunks_total"] == 2 and gate["chunks_grounded"] == 2

    # glass box: every §7 pass captured its state
    for name in ["1_prose", "2_objecttypes", "3_fillvalues", "2_9_normalize",
                 "discriminative_weight", "cross_chunk_link", "5_meaning"]:
        assert (tmp_path / f"{name}.json").exists(), f"missing state for {name}"
    state1 = json.loads((tmp_path / "1_prose.json").read_text())
    assert state1["outputs"][C1] == {"label": "prose"}
    norm = json.loads((tmp_path / "2_9_normalize.json").read_text())["outputs"]
    assert set(norm) == {"raw", "mapping", "final", "flagged_merges"}

    # the gold-note FLOOR passes end-to-end (C1 IS the gold chunk: B. Smith actor + reversal content)
    floor = json.loads((tmp_path / "floor.json").read_text())
    assert floor["passed"] is True and floor["has_b_smith_actor"] and floor["has_reversal"]
    assert result["floor"]["passed"] is True

    # basic enriched-data review.md generated — original + codex surfaced
    review = (tmp_path / "review.md").read_text()
    assert "Enriched-data review (codex)" in review and (tmp_path / "inputs.json").exists()

    # §5: records AND the codex+meaning artifacts exported BEFORE drop; isolation populated; schema gone
    recs = (tmp_path / "records.jsonl").read_text().splitlines()
    assert recs and json.loads(recs[0])["evidence_span"]
    for artifact in ("entities.jsonl", "links.jsonl", "meaning.jsonl"):
        assert (tmp_path / artifact).exists(), f"missing codex export {artifact}"
    iso = json.loads((tmp_path / "isolation.json").read_text())
    assert iso["scored_and_exported"] is True and iso["prod_untouched"] is True
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s",
                    (probe_schema_name("mpdry"),))
        assert cur.fetchone() is None      # dropped only AFTER export
