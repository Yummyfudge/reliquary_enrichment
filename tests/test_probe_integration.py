from __future__ import annotations

"""End-to-end probe dry run against scratch Postgres (never prod).

Fake candidate (deterministic proposals) + fake judge (deterministic verdict) exercise the
WHOLE harness: create probe_<label> schema, drive write_enrichment into it, score
(grounding / cross-context / smoking-gun / throughput), verify prod enrichment UNTOUCHED,
drop the schema. Marked integration; guarded to a local password-auth scratch DB.
"""

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

    # ISOLATION: prod enrichment counts unchanged, and the probe schema was dropped.
    assert result["prod_untouched"] is True
    assert prod_enrichment_counts() == before
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s",
                    (probe_schema_name("dryrun"),))
        assert cur.fetchone() is None  # dropped after scoring

    # results artifacts written
    assert (tmp_path / "attempts.jsonl").exists() and (tmp_path / "scorecard.json").exists()


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
