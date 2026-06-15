from __future__ import annotations

"""Chunk Handles — short, session-scoped aliases for Fragments (Decision C).

What: an in-process, workstream-keyed map. Read tools (get_chunk/get_neighbors) MINT
handles (``F1``, ``F2``, …) for the Fragments they return; write_enrichment/link_events
RESOLVE a handle back to the canonical chunk_id. Per-Fragment passes instead set a
"current Fragment" and the model passes no chunk reference at all.

Why this is a defense, not a convenience: a 1-2 char handle is far harder for a model to
corrupt than a 36-char UUID, and a corrupted handle resolves to a DIFFERENT real Fragment
whose text won't support the claim — so corruption is caught at the judge, never stored
(write_enrichment §3-1). The model never transcribes the id.

Scope: in-process, keyed by workstream id (revisit if multi-node — Decision C).
"""

import threading


class HandleMap:
    """Workstream-keyed handle <-> chunk_id map, plus a per-workstream current Fragment.

    Thread-safe: the live MCP server may service concurrent workstreams. Handles are
    allocated per workstream (``F1`` resets per workstream) so short aliases stay short.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # workstream_id -> {handle -> chunk_id}
        self._by_handle: dict[str, dict[str, str]] = {}
        # workstream_id -> {chunk_id -> handle}  (so the same Fragment reuses its handle)
        self._by_chunk: dict[str, dict[str, str]] = {}
        # workstream_id -> chunk_id  (per-Fragment "current Fragment")
        self._current: dict[str, str] = {}

    def mint(self, workstream_id: str, chunk_id: str) -> str:
        """Return a stable handle for this Fragment in this workstream, creating one if new.

        Idempotent: minting the same chunk_id twice in a workstream returns the same handle.
        """
        with self._lock:
            chunks = self._by_chunk.setdefault(workstream_id, {})
            existing = chunks.get(chunk_id)
            if existing is not None:
                return existing
            handles = self._by_handle.setdefault(workstream_id, {})
            handle = f"F{len(handles) + 1}"
            handles[handle] = chunk_id
            chunks[chunk_id] = handle
            return handle

    def resolve(self, workstream_id: str, handle: str) -> str | None:
        """Resolve a handle to its canonical chunk_id, or None if unknown in this workstream."""
        with self._lock:
            return self._by_handle.get(workstream_id, {}).get(handle)

    def set_current(self, workstream_id: str, chunk_id: str) -> None:
        """Set the per-Fragment 'current Fragment' (orchestrator, Pass 2 / per-Fragment mode)."""
        with self._lock:
            self._current[workstream_id] = chunk_id

    def current(self, workstream_id: str) -> str | None:
        """Return the workstream's current Fragment chunk_id, or None if unset."""
        with self._lock:
            return self._current.get(workstream_id)
