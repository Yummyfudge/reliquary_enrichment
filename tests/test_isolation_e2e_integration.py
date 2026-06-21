from __future__ import annotations

"""END-TO-END §5 isolation proof for the REHOMED harness (codex refactor §13, Joe's add #1).

Units prove the pieces; this proves the rehomed `multipass/` isolation harness still ISOLATES — the one
property we cannot regress. A full cycle against a REAL throwaway schema: prod-counts(before) ->
create-schema -> write -> export(before drop) -> drop -> prod-counts(after), asserting prod is provably
untouched (equal counts, or read-denied both times — the stronger structural wall). Also asserts the §6
probe structure (no claim_relevance column; enrichment_meaning table; GIN on entity_refs) and that the
exported artifact carries no claim_relevance (the §5.3 throw).
"""

import json
import pathlib
import tempfile
import uuid

import pytest

from reliquary_enrichment.models import EnrichmentRecord, EntityRef
from reliquary_enrichment.multipass.export import export_records
from reliquary_enrichment.multipass.isolation import _isolation_unchanged, prod_enrichment_counts
from reliquary_enrichment.multipass.isolation_schema import (
    create_probe_schema,
    drop_probe_schema,
    probe_schema_name,
)
from reliquary_enrichment.postgres.connection import connect
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore

pytestmark = pytest.mark.integration


def _db_available() -> bool:
    try:
        with connect() as conn:
            conn.cursor().execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture()
def live_db():
    if not _db_available():
        pytest.skip("isolation e2e proof needs the live DB (RELIQUARY_ENRICHMENT_PG* env)")


def test_isolation_proof_end_to_end_after_rehome(live_db):
    label = "iso_e2e_test"
    schema = probe_schema_name(label)
    before = prod_enrichment_counts()
    create_probe_schema(label)
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT count(*) n FROM information_schema.columns WHERE table_schema=%s "
                "AND table_name='enrichment_records' AND column_name='claim_relevance'", (schema,))
            assert cur.fetchone()["n"] == 0          # §10.2: probe records has NO claim_relevance
            cur.execute(
                "SELECT count(*) n FROM information_schema.tables WHERE table_schema=%s "
                "AND table_name='enrichment_meaning'", (schema,))
            assert cur.fetchone()["n"] == 1          # §6: probe meaning table exists
            cur.execute(
                "SELECT count(*) n FROM pg_indexes WHERE schemaname=%s "
                "AND indexdef ILIKE '%%gin%%entity_refs%%'", (schema,))
            assert cur.fetchone()["n"] == 1          # §6: GIN on entity_refs

        rs = PostgresEnrichmentRecordStore(schema=schema)
        rec = EnrichmentRecord(
            record_type="actor", tier="fact", source_chunk_id=str(uuid.uuid4()),
            char_start=0, char_end=8, evidence_span="B. Smith",
            provenance_validation={"verdict": "grounded"}, actor="B. Smith",
            entity_refs=[EntityRef("actor", "e1", "actor", "B. Smith")])
        rid = rs.insert(rec)
        assert rs.get(rid) is not None               # write landed in the PROBE schema

        out = tempfile.mkdtemp()
        assert export_records(schema, out) == 1       # raw export BEFORE drop
        first = json.loads((pathlib.Path(out) / "records.jsonl").read_text().splitlines()[0])
        assert "claim_relevance" not in first         # §5.3 throw — gone from the artifact
    finally:
        drop_probe_schema(label)

    after = prod_enrichment_counts()
    assert _isolation_unchanged(before, after)        # PROD UNTOUCHED (count-match OR read-denied both)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) n FROM information_schema.schemata WHERE schema_name=%s", (schema,))
        assert cur.fetchone()["n"] == 0               # schema dropped only AFTER export
