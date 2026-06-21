from __future__ import annotations

"""CrossChunkLinkPass — wire the orphaned LinkEvents into the codex's connective layer (brief §8).

per_chunk=False; runs AFTER entities + discriminative-weight (it needs the theme stoplist). The flow:
  code generates BOUNDED candidate pairs -> the model/code PROPOSES a relation + spans -> LinkEvents
  GROUNDS each (point->copy->judge->attest, one link per call; link_events.py untouched).

§8 reinforcements, all here (never inside link_events):
  (a) CANDIDATE-GEN is bounded: a pair is a candidate only if the two records share a RESOLVED NON-HUB
      (non-theme) entity — themes are STOPLISTED as anchors — and per-anchor fan-out is capped. The
      dry-run glass-box (candidate count, per-anchor fan-out, stoplisted anchors) is the "explosion
      bounded" acceptance. Never all-pairs.
  (b) TWO grounding classes: CODE-DERIVED temporal (precedes/follows over two resolved DATES, citing each
      record's own date-bearing span — the judge verifies the ordering) and MODEL-ASSERTED semantic
      (causes/corroborates/contradicts/elaborates/same_event — the model points spans, the judge rules).
  (c) same_event PRECISION guard: a grounded same_event MERGES the Event (union-find), so it is gated
      BEFORE link() — same actor anchor with DIFFERENT dates is NOT one event (distinct occurrences).
  (d) shared THEMES on each candidate are CAPTURED as glass-box metadata and NEVER acted on (no boost,
      no ranking, no effect on which links form) — a deferred, measurable signal (test_pass_link guards
      that it can't influence link creation/ordering). Resolved from data after the first real run.
"""

import re
from typing import Any

from reliquary_enrichment.multipass.locate import locate_quote
from reliquary_enrichment.multipass.parsing import validate_link_proposal
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAME_EVENT = "same_event"


def _is_theme(entity_store, entity_id: str) -> bool:
    e = entity_store.get(entity_id)
    return bool(e and e.metadata.get("is_theme"))


def _record_date(record) -> str | None:
    for ref in record.entity_refs:
        if ref.entity_type == "date":
            return ref.canonical
    return None


def same_event_allowed(rec_a, rec_b) -> bool:
    """§8c precision guard. Over-merge is the highest-severity link failure (it collapses distinct
    occurrences and destroys the timeline). A same_event candidate already shares a non-hub anchor; the
    one extra guard: if BOTH records are dated and the dates DIFFER, they are distinct occurrences (e.g.
    the same actor on two different dates) and must NOT be merged into one Event."""
    da, db = _record_date(rec_a), _record_date(rec_b)
    if da and db and da != db:
        return False
    return True


def generate_candidates(
    record_store, entity_store, *, fan_out_cap: int, max_candidates: int = 5000
) -> tuple[list[dict], dict]:
    """Bounded candidate pairs (§8a): cross-chunk record pairs sharing a NON-THEME entity (the anchor),
    per-anchor fan-out capped at F AND a global ceiling of K (so the total can't scale with corpus
    entity-richness past K — §10 'distinct pairs <= K, no entity > F'). Themes stoplisted. Returns
    (candidates, dry_run-glass-box). Pure/code. A hit cap is reported (no silent truncation)."""
    pairs: dict[tuple, dict] = {}
    fanout: dict[str, int] = {}
    stoplisted: list[str] = []
    capped = False

    for etype in sorted(ENTITY_TYPES):
        if capped:
            break
        for entity in entity_store.entities_of_type(etype):
            if capped:
                break
            if entity.metadata.get("is_theme"):
                stoplisted.append(entity.canonical)
                continue                                   # STOPLIST: a theme is never a link anchor
            recs = record_store.records_by_entity(entity.entity_id)
            made = 0
            for i in range(len(recs)):
                if made >= fan_out_cap or capped:
                    break
                for j in range(i + 1, len(recs)):
                    ra, rb = recs[i], recs[j]
                    if ra.source_chunk_id == rb.source_chunk_id:
                        continue                            # cross-CHUNK only
                    if made >= fan_out_cap:
                        break
                    if len(pairs) >= max_candidates:        # global K ceiling
                        capped = True
                        break
                    key = tuple(sorted((ra.record_id, rb.record_id)))
                    if key in pairs:
                        continue
                    pairs[key] = {"record_a": key[0], "record_b": key[1],
                                  "anchor": entity.canonical, "anchor_type": etype}
                    made += 1
            fanout[entity.canonical] = made

    # shared themes per pair — CAPTURED as a deferred signal, never used in gen/ranking/grounding above.
    for info in pairs.values():
        ra, rb = record_store.get(info["record_a"]), record_store.get(info["record_b"])
        a_th = {r.entity_id for r in ra.entity_refs if _is_theme(entity_store, r.entity_id)}
        b_th = {r.entity_id for r in rb.entity_refs if _is_theme(entity_store, r.entity_id)}
        info["shared_themes"] = sorted(entity_store.get(eid).canonical for eid in (a_th & b_th))

    dry_run = {
        "candidate_pairs": len(pairs),
        "per_anchor_fanout": fanout,
        "stoplisted_anchors": sorted(set(stoplisted)),
        "fan_out_cap": fan_out_cap,
        "max_candidates": max_candidates,
        "capped": capped,                                  # true => generation hit the global K ceiling
    }
    return list(pairs.values()), dry_run


def _temporal_payload(rec_a, rec_b) -> dict | None:
    """CODE-DERIVED temporal class: two resolved ISO dates that DIFFER -> precedes/follows, citing each
    record's own (already-grounded) span. No model call. The judge verifies the ordering."""
    da, db = _record_date(rec_a), _record_date(rec_b)
    if not da or not db or da == db or not (_ISO.match(da) and _ISO.match(db)):
        return None
    relation = "precedes" if da < db else "follows"
    return {
        "record_a": rec_a.record_id, "record_b": rec_b.record_id, "relation": relation, "tier": "fact",
        "rationale": f"{da} {relation} {db} (code-derived temporal ordering of two grounded dates)",
        "evidence": {"a_span": [rec_a.char_start, rec_a.char_end],
                     "b_span": [rec_b.char_start, rec_b.char_end]},
    }


class CrossChunkLinkPass(Pass):
    name = "cross_chunk_link"
    per_chunk = False

    def __init__(self, *, fan_out_cap: int = 8, max_candidates: int = 5000) -> None:
        self.fan_out_cap = fan_out_cap
        self.max_candidates = max_candidates

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> Any:
        record_store = ctx.extras["record_store"]
        entity_store = ctx.extras["entity_store"]
        linker = ctx.extras["linker"]                       # LinkEvents
        propose = ctx.extras["link_proposer"]               # model-asserted semantic proposer
        ws = ctx.extras.get("workstream_id", "mp-link")
        text = {c.chunk_id: c.text for c in chunks}

        candidates, dry_run = generate_candidates(
            record_store, entity_store, fan_out_cap=self.fan_out_cap, max_candidates=self.max_candidates)
        links: list[dict] = []
        for cand in candidates:
            meta = {"record_a": cand["record_a"], "record_b": cand["record_b"],
                    "anchor": cand["anchor"], "shared_themes": cand["shared_themes"]}
            ra, rb = record_store.get(cand["record_a"]), record_store.get(cand["record_b"])

            # class 1 — CODE-DERIVED temporal (date-bearing pair), no model call
            temporal = _temporal_payload(ra, rb)
            if temporal is not None:
                res = linker.link(temporal, workstream_id=ws)
                links.append({**meta, "klass": "temporal", "relation": temporal["relation"],
                              "ok": res.get("ok"), "link_id": res.get("link_id"),
                              "reason_code": res.get("reason_code")})

            # class 2 — MODEL-ASSERTED semantic
            lp = validate_link_proposal(propose(ra, rb, text.get(ra.source_chunk_id, ""),
                                                text.get(rb.source_chunk_id, ""), cand["anchor"]))
            if lp is None:
                links.append({**meta, "klass": "semantic", "ok": False, "reason_code": "no_proposal"})
                continue
            # Normalize the relation to lowercase so the same_event guard AND link_events' exact-string
            # materialization agree on case — a 'SAME_EVENT' variant can't slip the guard yet still write
            # an inconsistent edge (over-merge is the highest-severity failure; harden the detection).
            relation = lp.relation.strip().lower()
            if relation == SAME_EVENT and not same_event_allowed(ra, rb):
                links.append({**meta, "klass": "semantic", "relation": relation,
                              "ok": False, "reason_code": "same_event_guard"})
                continue
            la = locate_quote(text.get(ra.source_chunk_id, ""), lp.a_span)
            lb = locate_quote(text.get(rb.source_chunk_id, ""), lp.b_span)
            if la is None or lb is None:
                links.append({**meta, "klass": "semantic", "relation": relation,
                              "ok": False, "reason_code": "locate_miss"})
                continue
            payload = {"record_a": ra.record_id, "record_b": rb.record_id, "relation": relation,
                       "rationale": lp.rationale, "tier": "interpretation",
                       "evidence": {"a_span": list(la), "b_span": list(lb)}}
            res = linker.link(payload, workstream_id=ws)
            links.append({**meta, "klass": "semantic", "relation": relation, "ok": res.get("ok"),
                          "link_id": res.get("link_id"), "reason_code": res.get("reason_code"),
                          "event_entity": res.get("event_entity")})

        return {"dry_run": dry_run, "links": links,
                "n_links": sum(1 for link in links if link.get("ok"))}
