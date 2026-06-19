from __future__ import annotations

"""Integration: input loaders over claim_chunks (scratch only). Marked integration."""

import json

import pytest

from reliquary_enrichment.multipass.inputs import load_page_range_chunks, load_slice_chunks
from reliquary_enrichment.postgres.connection import connect, connection_kwargs

pytestmark = pytest.mark.integration

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
C = "33333333-3333-3333-3333-333333333333"


def _local_scratch() -> bool:
    kw = connection_kwargs()
    return str(kw.get("host", "")) in ("127.0.0.1", "localhost", "::1") and bool(kw.get("password"))


@pytest.fixture()
def seeded(tmp_path):
    if not _local_scratch():
        pytest.skip("loader integration runs only against a local scratch DB")
    with connect() as conn, conn.cursor() as cur:
        for cid, page, seg, text in ((A, 742, 0, "slice chunk A"), (B, 410, 0, "page-range B"),
                                     (C, 412, 1, "page-range C")):
            cur.execute("DELETE FROM context_reliquary.claim_chunks WHERE claim_chunk_id=%s", (cid,))
            cur.execute(
                "INSERT INTO context_reliquary.claim_chunks "
                "(claim_chunk_id, document_name, chunk_type, page_number, segment_index, payload) "
                "VALUES (%s,'claim.pdf','x',%s,%s, jsonb_build_object('chunk_text', %s::text))",
                (cid, page, seg, text))
    sl = tmp_path / "slice.txt"
    sl.write_text(f"# frozen\n{A}\n")
    yield sl


def test_load_slice_chunks(seeded):
    chunks = load_slice_chunks(seeded)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == A and chunks[0].text == "slice chunk A" and chunks[0].source == "slice"


def test_load_page_range_chunks_in_document_order(seeded):
    chunks = load_page_range_chunks("Aflac_claim_file_400-426", 400, 426)
    ids = [c.chunk_id for c in chunks]
    assert B in ids and C in ids                       # pages 410, 412 are in range
    assert all(c.source == "pdf:Aflac_claim_file_400-426" for c in chunks)
    # ordered by (page_number, segment_index)
    assert ids.index(B) < ids.index(C)
