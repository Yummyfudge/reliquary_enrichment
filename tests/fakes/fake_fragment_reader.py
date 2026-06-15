from __future__ import annotations

"""In-memory FragmentReader for unit tests — no DB."""

from reliquary_enrichment.grounding.fragments import Fragment, FragmentReader


class FakeFragmentReader(FragmentReader):
    """Holds a fixed set of Fragments keyed by chunk_id; get() returns None when absent."""

    def __init__(self, fragments: dict[str, Fragment] | None = None) -> None:
        self._fragments: dict[str, Fragment] = dict(fragments or {})

    def add(self, fragment: Fragment) -> None:
        self._fragments[fragment.chunk_id] = fragment

    def get(self, chunk_id: str) -> Fragment | None:
        return self._fragments.get(chunk_id)
