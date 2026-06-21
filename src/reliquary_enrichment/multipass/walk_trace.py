from __future__ import annotations

"""Gold-target assembly walk over a run's EXPORTED codex (brief §10 (4), build 10b).

Reconstructs the codex (records + entities + links) from the run's exported jsonl — so the trace survives
the throwaway probe schema's drop — and runs codex_walk.assemble() from a B.-Smith-mentioning chunk to the
gold reversal record. Writes walk_trace.json: the cited path, whether a grounded LINK was traversed, and
the gold record's grounded link neighbours (the §8d required edges, so a reviewer can see whether the gold
edge actually formed within step 7's bounds). Pure reconstruction + traversal — no DB, no model.
"""

import json
from pathlib import Path

from reliquary_enrichment.codex_walk import CodexWalk
from reliquary_enrichment.models import EnrichmentRecord, Entity, EntityRef, Link
from reliquary_enrichment.multipass.floor import GOLD_CHUNK_ID


class _RecStore:
    """In-memory record store exposing the read APIs CodexWalk needs (mirrors the Postgres/Fake semantics)."""

    def __init__(self, records):
        self.records = {r.record_id: r for r in records}

    def get(self, record_id):
        return self.records.get(record_id)

    def records_by_entity(self, entity_id):
        return sorted((r for r in self.records.values()
                       if any(ref.entity_id == entity_id for ref in r.entity_refs)),
                      key=lambda r: r.record_id)

    def records_by_chunk(self, chunk_id):
        return sorted((r for r in self.records.values() if r.source_chunk_id == chunk_id),
                      key=lambda r: r.record_id)


class _EntStore:
    def __init__(self, entities):
        self.entities = {e.entity_id: e for e in entities}

    def get(self, entity_id):
        return self.entities.get(entity_id)


class _LinkStore:
    def __init__(self, links):
        self.links = {l.link_id: l for l in links}

    def links_for_record(self, record_id):
        return sorted((l for l in self.links.values()
                       if l.record_a == record_id or l.record_b == record_id),
                      key=lambda l: l.link_id)


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _record(row: dict) -> EnrichmentRecord:
    refs = [EntityRef(r["role"], str(r["entity_id"]), r["entity_type"], r["canonical"])
            for r in (row.get("entity_refs") or [])]
    return EnrichmentRecord(
        record_type=row["record_type"], tier=row["tier"], source_chunk_id=str(row["source_chunk_id"]),
        char_start=row["char_start"], char_end=row["char_end"], evidence_span=row["evidence_span"],
        provenance_validation=row.get("provenance_validation") or {}, fields=row.get("fields") or {},
        actor=row.get("actor"), event_date=row.get("event_date"), entity_refs=refs,
        record_id=str(row["record_id"]))


def _link(row: dict) -> Link:
    return Link(
        record_a=str(row["record_a"]), record_b=str(row["record_b"]), relation=row["relation"],
        tier=row["tier"], evidence=row.get("evidence") or {},
        provenance_validation=row.get("provenance_validation") or {},
        event_entity=str(row["event_entity"]) if row.get("event_entity") else None,
        flagged=bool(row.get("flagged")), link_id=str(row["link_id"]))


def _entity(row: dict) -> Entity:
    return Entity(
        entity_type=row["entity_type"], canonical=row["canonical"], aliases=row.get("aliases") or [],
        metadata=row.get("metadata") or {}, flagged=bool(row.get("flagged")),
        entity_id=str(row["entity_id"]))


def build_codex_from_exports(out_dir: str | Path):
    """Load records.jsonl / entities.jsonl / links.jsonl into in-memory read-API stores."""
    out = Path(out_dir)
    rs = _RecStore([_record(r) for r in _read_jsonl(out / "records.jsonl")])
    es = _EntStore([_entity(r) for r in _read_jsonl(out / "entities.jsonl")])
    ls = _LinkStore([_link(r) for r in _read_jsonl(out / "links.jsonl")])
    return rs, es, ls


def _hop(h) -> dict:
    return {"kind": h.kind, "relation": h.relation, "src": h.src, "dst": h.dst, "cited": h.cited}


def gold_walk_trace(out_dir: str | Path, *, gold_chunk_id: str = GOLD_CHUNK_ID) -> dict:
    """Assemble from a B.-Smith-mentioning chunk to the gold reversal record over the exported codex."""
    rs, es, ls = build_codex_from_exports(out_dir)
    smith = next((e for e in es.entities.values()
                  if e.entity_type == "actor" and "b. smith" in e.canonical.lower()), None)
    gold_recs = rs.records_by_chunk(gold_chunk_id)
    target = None
    if smith:
        target = next((r for r in gold_recs
                       if any(ref.entity_id == smith.entity_id for ref in r.entity_refs)), None)
    target = target or (gold_recs[0] if gold_recs else None)

    seed_chunk = None
    if smith:
        for r in rs.records_by_entity(smith.entity_id):
            if r.source_chunk_id != gold_chunk_id:
                seed_chunk = r.source_chunk_id
                break

    walk = CodexWalk(record_store=rs, entity_store=es, link_store=ls)
    out: dict = {
        "gold_chunk_id": gold_chunk_id,
        "b_smith_entity": smith.entity_id if smith else None,
        "target_record": target.record_id if target else None,
        "seed_chunk": seed_chunk,
        # the §8d required edges: the gold record's grounded (walkable) link neighbours
        "gold_link_neighbours": [_hop(h) for h in walk.neighbors(target.record_id)] if target else [],
    }
    if target and seed_chunk:
        res = walk.assemble(target_record=target.record_id, seed_chunk=seed_chunk)
        out.update({
            "reached": res.reached, "examined": res.examined,
            "path": [_hop(h) for h in res.path],
            "reached_via_grounded_link": any(h.kind == "link" for h in res.path),
            "every_hop_cited": all(h.cited for h in res.path) if res.path else False,
        })
    else:
        out.update({"reached": False,
                    "reason": "gold target record or a B. Smith seed chunk not present in the codex"})
    return out


def write_walk_trace(out_dir: str | Path, out_name: str = "walk_trace.json") -> Path:
    out = Path(out_dir) / out_name
    out.write_text(json.dumps(gold_walk_trace(out_dir), indent=2, default=str))
    return out


def main(argv: list[str] | None = None) -> int:
    """Regenerate walk_trace.json from a run's results dir: python -m ...multipass.walk_trace <dir>."""
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    path = write_walk_trace(argv[0] if argv else ".")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
