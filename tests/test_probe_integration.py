from __future__ import annotations

"""End-to-end probe dry run against scratch Postgres (never prod).

Fake candidate (deterministic proposals) + fake judge (deterministic verdict) exercise the
WHOLE harness: create probe_<label> schema, drive write_enrichment into it, score
(grounding / cross-context / smoking-gun / throughput), verify prod enrichment UNTOUCHED,
drop the schema. Marked integration; guarded to a local password-auth scratch DB.
"""

import json
import os

import pytest

from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.postgres.connection import connect, connection_kwargs, qualified
from reliquary_enrichment.probe.cli import execute_probe, prod_enrichment_counts
from reliquary_enrichment.probe.extraction import ExtractionProposal
from reliquary_enrichment.probe.schema import probe_schema_name
from reliquary_enrichment.probe.scoring import GOLD_CHUNK_ID
from tests.fakes.fake_judge import ConstantJudge

pytestmark = pytest.mark.integration

CHUNK2 = "22222222-2222-2222-2222-222222222222"
CHUNK3 = "33333333-3333-3333-3333-333333333333"
GOLD_TEXT = ("Supervisor B. Smith reversed the long COVID removal, returning the claim "
             "to the Mental Health limitation on 2025-02-18.")
C2_TEXT = "Adjuster note: B. Smith approved the initial claim on 2025-01-05."
C3_TEXT = "Administrative note regarding mailing address updates only."


def _is_local_scratch() -> bool:
    kw = connection_kwargs()
    return str(kw.get("host", "")) in ("127.0.0.1", "localhost", "::1") and bool(kw.get("password"))


class FakeExtractor:
    """Deterministic candidate: gold->smoking-gun record; chunk2->shared actor; chunk3->locate miss."""

    model = "fake-candidate"

    def extract(self, text: str) -> list[ExtractionProposal]:
        if "reversed the long COVID" in text:
            return [ExtractionProposal(
                quote="B. Smith reversed the long COVID removal, returning the claim to the Mental Health limitation",
                record_type="status_change", tier="fact",
                fields={"change": "reversal"}, actor="B. Smith", event_date="2025-02-18")]
        if "approved the initial claim" in text:
            return [ExtractionProposal(
                quote="B. Smith approved the initial claim", record_type="status_change",
                tier="fact", actor="B. Smith", event_date="2025-01-05")]
        return [ExtractionProposal(quote="A QUOTE THAT DOES NOT APPEAR", record_type="x")]


@pytest.fixture()
def seeded():
    if not _is_local_scratch():
        pytest.skip("probe dry run requires a local password-auth scratch DB")
    with connect() as conn, conn.cursor() as cur:
        for cid, text, seg in ((GOLD_CHUNK_ID, GOLD_TEXT, 0), (CHUNK2, C2_TEXT, 1), (CHUNK3, C3_TEXT, 2)):
            cur.execute("DELETE FROM context_reliquary.claim_chunks WHERE claim_chunk_id=%s", (cid,))
            cur.execute(
                "INSERT INTO context_reliquary.claim_chunks "
                "(claim_chunk_id, document_name, chunk_type, page_number, segment_index, payload) "
                "VALUES (%s,%s,%s,%s,%s, jsonb_build_object('chunk_text', %s::text))",
                (cid, "claim.pdf", "Medical Records Request", 742, seg, text))
    yield [GOLD_CHUNK_ID, CHUNK2, CHUNK3]


def test_probe_dry_run_scores_and_leaves_prod_untouched(seeded, tmp_path):
    before = prod_enrichment_counts()
    assert before is not None  # scratch superuser can read prod enrichment tables

    result = execute_probe(
        label="dryrun", candidate_model="qwen-fake", chunk_ids=seeded,
        out_dir=str(tmp_path), extractor=FakeExtractor(), judge=ConstantJudge(Verdict.GROUNDED),
        drop_after=True,
    )
    card = result["scorecard"]

    # extraction quality
    assert card["n_proposals"] == 3 and card["n_located"] == 2 and card["n_locate_miss"] == 1
    assert card["n_records"] == 2 and card["n_grounded"] == 2
    assert card["grounding_pass_rate"] == 1.0
    # smoking-gun: the B. Smith reversal on the gold note, grounded
    assert card["smoking_gun"] is True
    assert card["smoking_gun_detail"]["record_id"] is not None
    # cross-context: B. Smith actor entity referenced by records on 2 different chunks
    assert card["cross_context_entities"] >= 1
    # throughput recorded
    assert card["records_per_min"] >= 0

    # coverage / recall surfaced (F3)
    assert card["chunks_with_proposals"] >= 1 and "chunks_empty" in card

    # ISOLATION: prod enrichment counts captured + unchanged; isolation.json populated (F5).
    assert result["prod_untouched"] is True
    assert prod_enrichment_counts() == before
    iso = json.loads((tmp_path / "isolation.json").read_text())
    assert iso["prod_untouched"] is True and iso["scored_and_exported"] is True
    assert iso["proof"] == "count-verified"          # scratch superuser can read counts
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s",
                    (probe_schema_name("dryrun"),))
        assert cur.fetchone() is None  # dropped — but only AFTER score + export

    # RAW records exported (incl. evidence_span + provenance_validation + entity_refs) BEFORE drop
    assert (tmp_path / "attempts.jsonl").exists() and (tmp_path / "scorecard.json").exists()
    rec_lines = (tmp_path / "records.jsonl").read_text().splitlines()
    assert rec_lines, "records.jsonl must be non-empty"
    rec0 = json.loads(rec_lines[0])
    assert rec0["evidence_span"] and "provenance_validation" in rec0 and "entity_refs" in rec0
    assert (tmp_path / "records.txt").exists()


def test_never_drops_schema_when_scoring_fails(seeded, tmp_path, monkeypatch):
    # If score/export can't complete, the schema must be KEPT for investigation (F2), not dropped.
    import reliquary_enrichment.probe.cli as cli_mod
    monkeypatch.setattr(cli_mod, "score", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        execute_probe(label="keepme", candidate_model="qwen-fake", chunk_ids=[GOLD_CHUNK_ID],
                      out_dir=str(tmp_path), extractor=FakeExtractor(),
                      judge=ConstantJudge(Verdict.GROUNDED), drop_after=True)
    from reliquary_enrichment.probe.schema import drop_probe_schema, probe_schema_name as psn
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (psn("keepme"),))
        kept = cur.fetchone() is not None
    drop_probe_schema("keepme")          # cleanup
    assert kept, "schema was dropped despite scoring failure — must keep unscored schemas"


def test_probe_writes_only_to_probe_schema_not_prod(seeded, tmp_path):
    # the run's records land in the PROBE schema; prod enrichment_records gains nothing.
    from reliquary_enrichment.probe.schema import drop_probe_schema

    before = prod_enrichment_counts()
    execute_probe(label="iso", candidate_model="qwen-fake", chunk_ids=[GOLD_CHUNK_ID],
                  out_dir=str(tmp_path), extractor=FakeExtractor(),
                  judge=ConstantJudge(Verdict.GROUNDED), drop_after=False)
    try:
        probe_tbl = qualified(probe_schema_name("iso"), "enrichment_records")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*) AS n FROM {probe_tbl}")
            assert cur.fetchone()["n"] == 1            # the record went to the probe schema
        assert prod_enrichment_counts() == before       # ...and NOT to prod
    finally:
        drop_probe_schema("iso")
