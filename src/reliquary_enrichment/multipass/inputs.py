from __future__ import annotations

"""Input loaders — turn the test set into ChunkRefs the pipeline consumes.

Two sources, both read-only over ``claim_chunks`` (the probe role's corpus access):
  * the frozen 131-chunk slice (``probe/slice/chunk_ids.txt``), source="slice".
  * a page RANGE, source="pdf:<name>" — the two test "PDFs" Joe named
    (Aflac_claim_file_400-426, _575-580) are page ranges of the same claim file whose text is
    already chunked in claim_chunks, so v0 feeds those ranges from the corpus (same chunking as
    the slice, comparable, no PDF parsing/OCR). If we later need to parse the RAW PDFs, that's a
    separate chunker swapped in behind the same ChunkRef interface.

The text is ``payload->>'chunk_text'`` — exactly the Fragment text the grounding core slices,
so passes see the same units the single-pass probe did.
"""

import re
from pathlib import Path

from reliquary_enrichment.multipass.pass_base import ChunkRef
from reliquary_enrichment.postgres.connection import connect

_PDF_NAME = re.compile(r"(\d+)-(\d+)")


def load_slice_chunks(slice_path: str | Path = "probe/slice/chunk_ids.txt") -> list[ChunkRef]:
    """Load the frozen slice as ChunkRefs (source='slice'), in the slice's file order."""
    ids = [
        line.split()[0]
        for line in Path(slice_path).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    rows = _fetch_text({"ids": ids})
    by_id = {str(r["claim_chunk_id"]): (r["chunk_text"] or "") for r in rows}
    return [ChunkRef(cid, by_id[cid], "slice") for cid in ids if cid in by_id]


def load_page_range_chunks(name: str, lo: int, hi: int) -> list[ChunkRef]:
    """Load claim_chunks for pages [lo, hi] as ChunkRefs (source='pdf:<name>'), in document order."""
    rows = _fetch_text({"lo": lo, "hi": hi}, page_range=True)
    src = f"pdf:{name}"
    return [ChunkRef(str(r["claim_chunk_id"]), r["chunk_text"] or "", src) for r in rows]


def page_range_from_filename(filename: str) -> tuple[str, int, int]:
    """'Aflac_claim_file_400-426.pdf' -> ('Aflac_claim_file_400-426', 400, 426)."""
    stem = Path(filename).stem
    m = _PDF_NAME.search(stem)
    if not m:
        raise ValueError(f"no page range (NNN-MMM) in filename {filename!r}")
    return stem, int(m.group(1)), int(m.group(2))


def _fetch_text(params: dict, *, page_range: bool = False) -> list[dict]:
    if page_range:
        sql = ("SELECT claim_chunk_id, page_number, segment_index, "
               "payload->>'chunk_text' AS chunk_text "
               "FROM context_reliquary.claim_chunks "
               "WHERE page_number BETWEEN %(lo)s AND %(hi)s "
               "ORDER BY page_number, segment_index")
    else:
        sql = ("SELECT claim_chunk_id, payload->>'chunk_text' AS chunk_text "
               "FROM context_reliquary.claim_chunks WHERE claim_chunk_id = ANY(%(ids)s)")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
