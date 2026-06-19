from __future__ import annotations

"""v0 end-to-end dry run of the whole multipass pipeline on the scratch DB (no lane).

A prompt-routing fake model drives every pass; Pass 3 grounds real records via a fake judge
into a probe schema. Validates: all 7 passes run + capture state, the gate reads faithfulness,
raw records.jsonl exports BEFORE drop, isolation.json is populated, the schema is dropped.
"""

import json

import pytest

from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.multipass.cli import execute_multipass
from reliquary_enrichment.postgres.connection import connect, connection_kwargs
from reliquary_enrichment.probe.schema import probe_schema_name
from tests.fakes.fake_judge import ConstantJudge

pytestmark = pytest.mark.integration

C1 = "11111111-1111-1111-1111-111111111111"
C2 = "22222222-2222-2222-2222-222222222222"
T1 = "Supervisor B. Smith reversed the prior approval on 2025-02-18 to Mental Health limitation."
T2 = "Adjuster note: claim returned to long COVID review on 2025-01-05 by the case manager."


def _local_scratch() -> bool:
    kw = connection_kwargs()
    return str(kw.get("host", "")) in ("127.0.0.1", "localhost", "::1") and bool(kw.get("password"))


class PromptRoutingFake:
    """One fake model that answers each pass by inspecting its system prompt."""

    def complete(self, system: str, user: str):
        s = system.lower()
        if "prose" in s and "non_prose" in s:
            return "prose", 3
        if "types of records" in s:
            return '["status_change","date"]', 4
        if "canonical schema" in s:
            return ('{"canonical":["status_change","date"],'
                    '"mapping":{"status_change":"status_change","date":"date"}}'), 4
        if "extract one grounded record" in s:
            chunk = user.split("CHUNK:\n", 1)[-1]
            quote = chunk[:40]                       # verbatim prefix -> locate_quote succeeds
            return json.dumps({"quote": quote, "record_type": "status_change", "tier": "fact",
                               "fields": {}, "actor": None, "event_date": None,
                               "confidence": 0.9}), 8
        if "signal keywords" in s:
            return '["reversal","mental health"]', 4
        if "claim-relevance meaning" in s:
            return '{"claim_meaning":"significance","questions_answered":["why?"]}', 5
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
    assert gate["chunks_total"] == 2 and gate["chunks_grounded"] == 2   # both grounded
    assert gate["faithfulness_rate"] == 1.0

    # glass box: every pass captured its state
    for name in ["1_prose", "2_objecttypes", "2_9_consolidate", "3_fillvalues",
                 "4_keywords", "4_9_cleanup", "5_meaning"]:
        assert (tmp_path / f"{name}.json").exists(), f"missing state for {name}"
    state1 = json.loads((tmp_path / "1_prose.json").read_text())
    assert state1["outputs"][C1] == {"label": "prose"}
    state29 = json.loads((tmp_path / "2_9_consolidate.json").read_text())
    assert set(state29["outputs"]) == {"raw", "raw_types", "final", "mapping"}

    # basic enriched-data review.md generated (Joe's ask) — original + enriched surfaced
    review = (tmp_path / "review.md").read_text()
    assert "Enriched-data review" in review and T1[:20] in review and (tmp_path / "inputs.json").exists()

    # §5: raw records exported BEFORE drop, with evidence_span; isolation populated; schema gone
    recs = (tmp_path / "records.jsonl").read_text().splitlines()
    assert recs and json.loads(recs[0])["evidence_span"]
    iso = json.loads((tmp_path / "isolation.json").read_text())
    assert iso["scored_and_exported"] is True and iso["prod_untouched"] is True
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s",
                    (probe_schema_name("mpdry"),))
        assert cur.fetchone() is None      # dropped only AFTER export
