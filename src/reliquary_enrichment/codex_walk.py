from __future__ import annotations

"""codex_walk — the query-time AGENTIC-ASSEMBLY walker (brief §3.1, §5.4 #9, §10 (4)).

The bright line: a chunk's MEANING is embedded for RETRIEVAL; the larger answer is NOT embedded — it is
*assembled at query time by walking the codex* (entities + records + grounded links), not packed into a
vector. This module is that walk. From a seed (a chunk or an entity) it steps:

    seed chunk  --mentions-->  entity  --cites-->  record  --link-->  neighbor record  --link-->  ...

returning the path it took, where EVERY hop carries the grounded evidence that justifies it. Two
properties make the walk faithful to the grounding law rather than a generic graph traversal:

  1. ONLY CITED EDGES ARE WALKABLE. A record with no ``evidence_span`` and a link with empty ``evidence``
     are invisible to assembly — an ungrounded edge can never smuggle a path. So "every hop cited" is a
     structural invariant of what the walk *can* reach, not a property checked after the fact.
  2. The §10 acceptance is reach-via-LINKS: from any chunk mentioning B. Smith the walk reaches the
     gold-note reversal event — and the decision it undid / its date node — over grounded links, even
     when no vector retrieval would surface them. The walker holds NO embeddings; it is pure structure.
"""

from collections import deque
from dataclasses import dataclass


def _is_span_pair(value: object) -> bool:
    """A code-sliced span is a [start, end] pair of ints (link_events writes list(p.a_span))."""
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in value))


def _span_grounded(span: str | None) -> bool:
    """A record-side citation is grounded iff it carries a NON-BLANK evidence span (mirrors the DB's
    enrichment_records_span_nonblank_chk: evidence_span ~ '[^[:space:]]'). '' / None / whitespace fail."""
    return bool(span and span.strip())


def _link_grounded(evidence: object) -> bool:
    """A link-side citation is grounded iff it carries the CODE-SLICED span pair the linker actually writes
    (link_events.py: evidence={'a_span':[s,e], 'b_span':[s,e], ...}). A non-empty but SPAN-LESS dict like
    {'note': 'hunch'} is NOT grounded — it cannot smuggle a path. This makes "only cited edges are
    walkable" a structural READ-TIME guarantee, not a lean on the writer's discipline (step-9 review HIGH)."""
    return (isinstance(evidence, dict)
            and _is_span_pair(evidence.get("a_span")) and _is_span_pair(evidence.get("b_span")))


@dataclass(frozen=True, slots=True)
class Hop:
    """One cited step of an assembly walk. ``citation`` is the grounded evidence justifying THIS hop;
    the walker never constructs a hop without one (see ``cited``)."""

    kind: str                 # "mentions" (chunk->entity) | "cites" (entity->record) | "link" (record->record)
    relation: str | None      # the Link relation, for kind == "link"; None otherwise
    src: str                  # source node id (chunk_id / entity_id / record_id)
    dst: str                  # destination node id (entity_id / record_id)
    citation: dict            # grounded evidence: a record span, or a link's a_span/b_span pair

    @property
    def cited(self) -> bool:
        """Grounded iff the citation carries a REAL span: a link hop needs the a_span/b_span pair; a
        record hop needs a non-blank evidence_span. Kind-specific, so a stray cross-kind key can't smuggle
        citedness, and a span-less/blank citation reads as uncited (step-9 review HIGH/MED/LOW)."""
        if self.kind == "link":
            return _link_grounded(self.citation.get("evidence"))
        return _span_grounded(self.citation.get("evidence_span"))


@dataclass(frozen=True, slots=True)
class WalkResult:
    reached: bool
    target: str | None
    path: list[Hop]           # the cited hops from seed to target ([] if not reached)
    examined: int             # nodes dequeued (glass-box: how much codex the walk touched)


class CodexWalk:
    """Walks the persisted codex over GROUNDED edges only. Holds the three read-API stores; no embeddings."""

    def __init__(self, *, record_store, entity_store, link_store) -> None:
        self._records = record_store
        self._entities = entity_store
        self._links = link_store

    # --- cited primitive hops -------------------------------------------------
    def entities_of_chunk(self, chunk_id: str) -> list[Hop]:
        """chunk -> each entity it mentions, cited by the grounded record span that names it."""
        hops: list[Hop] = []
        seen: set[tuple[str, str]] = set()
        for rec in self._records.records_by_chunk(chunk_id):
            if not _span_grounded(rec.evidence_span):      # ungrounded record: not a walkable citation
                continue
            for ref in rec.entity_refs:
                key = (ref.entity_id, rec.record_id)
                if key in seen:
                    continue
                seen.add(key)
                hops.append(Hop("mentions", None, chunk_id, ref.entity_id, {
                    "record_id": rec.record_id, "source_chunk_id": rec.source_chunk_id,
                    "char_start": rec.char_start, "char_end": rec.char_end,
                    "evidence_span": rec.evidence_span, "role": ref.role, "canonical": ref.canonical,
                }))
        return hops

    def records_for_entity(self, entity_id: str) -> list[Hop]:
        """entity -> each record citing it, cited by that record's own grounded span."""
        hops: list[Hop] = []
        for rec in self._records.records_by_entity(entity_id):
            if not _span_grounded(rec.evidence_span):
                continue
            hops.append(Hop("cites", None, entity_id, rec.record_id, {
                "record_id": rec.record_id, "source_chunk_id": rec.source_chunk_id,
                "char_start": rec.char_start, "char_end": rec.char_end,
                "evidence_span": rec.evidence_span,
            }))
        return hops

    def neighbors(self, record_id: str) -> list[Hop]:
        """record -> linked neighbor records, cited by the LINK's grounded evidence. ONLY grounded links
        are walkable: an ungrounded link (empty evidence) is invisible to assembly."""
        hops: list[Hop] = []
        for link in self._links.links_for_record(record_id):
            if not _link_grounded(link.evidence):          # span-less / ungrounded link: not walkable
                continue
            other = link.record_b if link.record_a == record_id else link.record_a
            hops.append(Hop("link", link.relation, record_id, other, {
                "link_id": link.link_id, "relation": link.relation,
                "evidence": link.evidence, "tier": link.tier, "flagged": link.flagged,
            }))
        return hops

    # --- the assembly walk ----------------------------------------------------
    def assemble(self, *, target_record: str, seed_chunk: str | None = None,
                 seed_entity: str | None = None, max_hops: int = 8) -> WalkResult:
        """BFS from the seed to ``target_record`` over grounded hops; return the shortest cited path found
        (or reached=False). ``max_hops`` bounds the path length. Reaches a target via links even when no
        embedding would rank it — the codex is the structure, not the vector."""
        if not (seed_chunk or seed_entity):
            raise ValueError("assemble() needs a seed_chunk or a seed_entity")

        queue: deque[tuple[str, str, list[Hop]]] = deque()
        visited_entities: set[str] = set()
        visited_records: set[str] = set()

        if seed_entity:
            visited_entities.add(seed_entity)
            queue.append(("entity", seed_entity, []))
        if seed_chunk:
            for h in self.entities_of_chunk(seed_chunk):
                if h.dst in visited_entities:
                    continue
                visited_entities.add(h.dst)
                queue.append(("entity", h.dst, [h]))

        examined = 0
        while queue:
            kind, node, path = queue.popleft()
            examined += 1
            next_hops = self.records_for_entity(node) if kind == "entity" else self.neighbors(node)
            for h in next_hops:
                new_path = path + [h]
                if len(new_path) > max_hops:
                    continue
                if h.dst == target_record:
                    return WalkResult(True, target_record, new_path, examined)
                if h.dst in visited_records:
                    continue
                visited_records.add(h.dst)
                queue.append(("record", h.dst, new_path))
        return WalkResult(False, None, [], examined)
