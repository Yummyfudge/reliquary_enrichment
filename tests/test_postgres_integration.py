from __future__ import annotations

"""DB-backed integration — the Postgres stores + read tools + live DDL constraints.

Marked ``integration`` (skipped by default). Runs ONLY against a local scratch Postgres,
NEVER prod: it refuses to run unless the target host is local AND a password is set (prod
uses cert-auth with no password) — and it TRUNCATEs/seeds, which must never hit the corpus.

Set up the scratch DB first (see tests/scratch_db.md), then:
    RELIQUARY_ENRICHMENT_PGHOST=127.0.0.1 RELIQUARY_ENRICHMENT_PGPORT=55432 \
    RELIQUARY_ENRICHMENT_PGDATABASE=scratch RELIQUARY_ENRICHMENT_PGUSER=postgres \
    RELIQUARY_ENRICHMENT_PGPASSWORD=scratch RELIQUARY_ENRICHMENT_PGSSLMODE=disable \
    pytest -m integration tests/test_postgres_integration.py
"""

import hashlib
import os

import pytest

from reliquary_enrichment.entities import EntityResolver, EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.postgres.connection import connect, connection_kwargs
from reliquary_enrichment.postgres.entity_store import PostgresEntityStore
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader
from reliquary_enrichment.postgres.link_store import PostgresLinkStore
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore
from reliquary_enrichment.read_tools import ReadTools
from reliquary_enrichment.write_enrichment import WriteEnrichment
from tests.fakes.fake_judge import ConstantJudge

pytestmark = pytest.mark.integration

CHUNK_A = "11111111-1111-1111-1111-111111111111"
CHUNK_B = "22222222-2222-2222-2222-222222222222"
TEXT_A = "Supervisor B. Smith reversed the prior approval on 2025-02-18."
TEXT_B = "The reversal was logged in the audit trail on 2025-02-18."
WS = "ws-int"


def _is_local_scratch() -> bool:
    kw = connection_kwargs()
    host = str(kw.get("host", ""))
    return host in ("127.0.0.1", "localhost", "::1") and bool(kw.get("password"))


@pytest.fixture()
def db():
    if not _is_local_scratch():
        pytest.skip("integration DB test runs only against a local password-auth scratch DB")
    with connect() as conn, conn.cursor() as cur:
        # scratch-only reset + seed (TRUNCATE never reaches prod — guarded above).
        cur.execute("TRUNCATE context_reliquary.enrichment_links, "
                    "context_reliquary.enrichment_records, context_reliquary.codex_entities, "
                    "context_reliquary.enrichment_meaning RESTART IDENTITY")
        cur.execute("DELETE FROM context_reliquary.claim_chunks WHERE claim_chunk_id IN (%s,%s)",
                    (CHUNK_A, CHUNK_B))
        for cid, text, seg in ((CHUNK_A, TEXT_A, 0), (CHUNK_B, TEXT_B, 1)):
            cur.execute(
                "INSERT INTO context_reliquary.claim_chunks "
                "(claim_chunk_id, document_name, chunk_type, page_number, segment_index, payload) "
                "VALUES (%s,%s,%s,%s,%s, jsonb_build_object('chunk_text', %s::text))",
                (cid, "denial.pdf", "status_change", 7, seg, text),
            )
    yield


def _wiring(verdict=Verdict.GROUNDED):
    reader = PostgresFragmentReader()
    hm = HandleMap()
    core = GroundingCore(fragment_reader=reader, handle_map=hm, judge=ConstantJudge(verdict))
    records = PostgresEnrichmentRecordStore()
    entities = PostgresEntityStore()
    write = WriteEnrichment(core=core, record_store=records,
                            entity_resolver=EntityResolver(entities))
    link = LinkEvents(core=core, record_store=records, link_store=PostgresLinkStore(),
                      event_materializer=EventMaterializer(entities))
    read = ReadTools(fragment_reader=reader, handle_map=hm)
    return read, write, link, records, entities


def test_get_chunk_mints_handle_and_write_persists_grounded_record(db):
    read, write, _, records, entities = _wiring()
    got = read.get_chunk(CHUNK_A, workstream_id=WS)
    assert got["ok"] and got["text"] == TEXT_A
    handle = got["chunk_handle"]

    out = write.write({
        "chunk_handle": handle, "char_start": 0, "char_end": 28,
        "record_type": "status_change", "tier": "fact",
        "actor": "B. Smith", "event_date": "2025-02-18",
        "fields": {"change": "approval reversed"},
    }, workstream_id=WS)
    assert out["ok"], out

    # round-trip the row + verify the frozen hashes match the stored bytes.
    stored = records.get(out["record_id"])
    assert stored.evidence_span == TEXT_A[0:28]
    assert stored.source_chunk_id == CHUNK_A and stored.page == 7
    pv = stored.provenance_validation
    assert pv["evidence_sha256"] == hashlib.sha256(TEXT_A[0:28].encode()).hexdigest()
    assert pv["source_sha256"] == hashlib.sha256(TEXT_A.encode()).hexdigest()
    # actor + date Entities materialized.
    assert entities.find("actor", "B. Smith") is not None
    assert entities.find("date", "2025-02-18") is not None


def test_write_once_trigger_blocks_update(db):
    _, write, _, _, _ = _wiring()
    out = write.write({
        "chunk_handle": None, "chunk_id": CHUNK_A, "char_start": 0, "char_end": 28,
        "record_type": "status_change", "tier": "fact",
    }, workstream_id=WS)
    assert out["ok"], out
    import psycopg
    with pytest.raises(psycopg.errors.Error):
        with connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE context_reliquary.enrichment_records SET actor='x' "
                        "WHERE record_id=%s", (out["record_id"],))


def test_same_event_link_materializes_event_in_db(db):
    read, write, link, records, entities = _wiring()
    a = write.write({"chunk_id": CHUNK_A, "char_start": 0, "char_end": 28,
                     "record_type": "status_change", "tier": "fact"}, workstream_id=WS)
    b = write.write({"chunk_id": CHUNK_B, "char_start": 0, "char_end": 12,
                     "record_type": "status_change", "tier": "fact"}, workstream_id=WS)
    assert a["ok"] and b["ok"]
    out = link.link({
        "record_a": a["record_id"], "record_b": b["record_id"],
        "relation": "same_event", "tier": "fact",
        "evidence": {"a_span": [0, 28], "b_span": [0, 12]},
        "rationale": "same reversal event on the same date",
    }, workstream_id=WS)
    assert out["ok"], out
    ev = entities.event_for_record(a["record_id"])
    assert ev is not None and ev.entity_id == out["event_entity"]
    assert set(ev.metadata["member_records"]) == {a["record_id"], b["record_id"]}


def test_unknown_record_ref_writes_nothing(db):
    _, _, link, _, _ = _wiring()
    out = link.link({
        "record_a": "33333333-3333-3333-3333-333333333333",
        "record_b": "44444444-4444-4444-4444-444444444444",
        "relation": "precedes", "tier": "fact",
        "evidence": {"a_span": [0, 5], "b_span": [0, 5]}, "rationale": "x",
    }, workstream_id=WS)
    assert out["ok"] is False and out["reason_code"] == "unknown_record"


def test_get_neighbors_returns_both_seeded_chunks(db):
    read, *_ = _wiring()
    out = read.get_neighbors(CHUNK_A, window=2, workstream_id=WS)
    assert out["ok"]
    ids = {f["chunk_id"] for f in out["fragments"]}
    assert {CHUNK_A, CHUNK_B} <= ids
