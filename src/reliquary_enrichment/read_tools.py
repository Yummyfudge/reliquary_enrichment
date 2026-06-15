from __future__ import annotations

"""Read tools — get_chunk / get_neighbors. Read-only; mint Chunk Handles (Decision D4).

These surface Fragment text (== payload->>'chunk_text', the slice source) tagged with a
short session-scoped Chunk Handle the model uses for write_enrichment/link_events. So the
model points with a 1-2 char handle, never a 36-char UUID it could corrupt. Read-only ->
auto-approve. The text returned here is EXACTLY what the offsets index into.
"""

from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader


class ReadTools:
    """get_chunk + get_neighbors over claim_chunks, minting handles into the HandleMap."""

    def __init__(self, *, fragment_reader=None, handle_map: HandleMap) -> None:
        self._reader = fragment_reader or PostgresFragmentReader()
        self._handles = handle_map

    def _present(self, frag, workstream_id: str) -> dict:
        handle = self._handles.mint(workstream_id, frag.chunk_id)
        return {
            "chunk_handle": handle,
            "chunk_id": frag.chunk_id,
            "text": frag.text,
            "document": frag.document,
            "page": frag.page,
            "chunk_type": frag.chunk_type,
        }

    def get_chunk(self, chunk_id: str, *, workstream_id: str) -> dict:
        """Return one Fragment tagged with a fresh Chunk Handle (or a not-found rejection).

        Also sets this Fragment as the workstream's "current Fragment", so per-Fragment
        passes (Pass 2) work after a single get_chunk — the model then writes with no chunk
        ref. Handle mode (Pass 3) passes explicit handles and does not rely on current.
        """
        frag = self._reader.get(chunk_id)
        if frag is None:
            return {
                "ok": False,
                "reason_code": "fragment_not_found",
                "detail": f"no Fragment in claim_chunks for chunk_id {chunk_id!r}.",
            }
        self._handles.set_current(workstream_id, frag.chunk_id)
        return {"ok": True, **self._present(frag, workstream_id)}

    def get_neighbors(self, chunk_id: str, *, window: int = 1, workstream_id: str) -> dict:
        """Return the anchor + adjacent Fragments (same document), each handle-tagged."""
        neighbors = self._reader.neighbors(chunk_id, window)
        if not neighbors:
            return {
                "ok": False,
                "reason_code": "fragment_not_found",
                "detail": f"no Fragment (or neighbors) for chunk_id {chunk_id!r}.",
            }
        return {
            "ok": True,
            "anchor_chunk_id": chunk_id,
            "window": window,
            "fragments": [self._present(f, workstream_id) for f in neighbors],
        }
