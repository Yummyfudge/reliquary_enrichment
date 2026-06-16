from __future__ import annotations

"""Scoring — grounding pass-rate, cross-context capture, smoking-gun, throughput.

The probe schema (judge-gated records the candidate actually grounded) is authoritative for
quality; the RunLog supplies attempts + wall-clock for rates/throughput. The pure scorer
(``score_from_data``) takes plain dicts so every metric is unit-testable with no DB; the DB
loader pulls the probe schema rows.
"""

import json
from dataclasses import asdict, dataclass, field

from reliquary_enrichment.postgres.connection import connect, qualified

# The gold note — the supervisor reversal the whole system exists to surface (mislabeled
# chunk_type "Medical Records Request"). The smoking-gun decider keys on this chunk.
GOLD_CHUNK_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"

# Reversal/restoration DIRECTION — the prior change was undone and the claim put BACK to the
# Mental Health limitation. Broadened from the literal "revers" (Architect, 2026-06-16) so a
# candidate phrasing it "reverted" / "placed back" / "reinstated" / "returned to" doesn't
# false-negative the decider. Substring match, lowercased; gated by actor + condition so loose
# terms ("back to") can't false-positive on their own.
REVERSAL_TERMS = (
    "revers",      # reversed / reversal / reverse
    "revert",      # reverted / reverting / reversion
    "reinstat",    # reinstated / reinstatement
    "restor",      # restored / restoration
    "overturn",    # overturned
    "rescind",     # rescinded
    "reappl",      # reapplied / re-applied
    "undo", "undone",
    "return",      # returned / returning the claim to ...
    "placed back", "put back", "moved back", "changed back", "switched back",
    "back to", "back under",
)


@dataclass(slots=True)
class ScoreCard:
    label: str
    candidate_model: str
    n_proposals: int
    n_located: int
    n_locate_miss: int
    n_records: int
    n_grounded: int
    n_flagged: int
    grounding_pass_rate: float          # grounded / reached-judge (the safety floor)
    end_to_end_yield: float             # records / proposals (incl. pointing misses)
    cross_context_entities: int         # entities referenced by records on >=2 distinct chunks
    smoking_gun: bool
    smoking_gun_detail: dict
    chunks_seen: int
    chunks_missing: int
    chunks_per_min: float
    records_per_min: float
    wall_seconds: float
    extract_errors: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _haystack(rec: dict) -> str:
    parts = [
        rec.get("evidence_span") or "",
        json.dumps(rec.get("fields") or {}),
        rec.get("claim_relevance") or "",
        rec.get("actor") or "",
        rec.get("event_date") or "",
    ]
    return " ".join(parts).lower()


def smoking_gun(records: list[dict]) -> tuple[bool, dict]:
    """Did the candidate capture+GROUND the B. Smith reversal on the gold chunk?

    Transparent matcher (returns what matched, for audit): a GROUNDED record on
    GOLD_CHUNK_ID whose text shows the actor (Smith), a reversal, and the condition swap
    (long COVID / Mental Health limitation). Partial/flagged does not count — the brief
    requires a grounded capture.
    """
    for rec in records:
        if str(rec.get("source_chunk_id")) != GOLD_CHUNK_ID:
            continue
        verdict = (rec.get("provenance_validation") or {}).get("verdict")
        if verdict != "grounded":
            continue
        text = _haystack(rec)
        matched_term = next((t for t in REVERSAL_TERMS if t in text), None)
        signals = {
            "actor_smith": "smith" in text,
            "reversal_direction": matched_term,   # which undo/restore term matched (or None)
            "condition_swap": ("long covid" in text) or ("mental health" in text),
        }
        if signals["actor_smith"] and matched_term and signals["condition_swap"]:
            return True, {"record_id": rec.get("record_id"), "signals": signals}
    return False, {"record_id": None, "signals": {}}


def cross_context_entities(records: list[dict]) -> int:
    """Count Entities referenced by records sitting on >=2 DIFFERENT source chunks (v1 proxy)."""
    by_entity: dict[str, set[str]] = {}
    for rec in records:
        chunk = str(rec.get("source_chunk_id"))
        for ref in rec.get("entity_refs") or []:
            by_entity.setdefault(ref["entity_id"], set()).add(chunk)
    return sum(1 for chunks in by_entity.values() if len(chunks) >= 2)


def score_from_data(run_log, records: list[dict]) -> ScoreCard:
    """Pure scorer — RunLog + the probe schema's records (as dicts). No DB."""
    attempts = run_log.attempts
    n_proposals = len(attempts)
    n_located = sum(1 for a in attempts if a.located)
    n_locate_miss = n_proposals - n_located
    n_records = len(records)
    n_grounded = sum(1 for r in records if (r.get("provenance_validation") or {}).get("verdict") == "grounded")
    n_flagged = sum(1 for r in records if r.get("flagged"))
    pass_rate = (n_grounded / n_located) if n_located else 0.0
    yield_rate = (n_records / n_proposals) if n_proposals else 0.0
    sg, sg_detail = smoking_gun(records)
    minutes = run_log.wall_seconds / 60.0 if run_log.wall_seconds else 0.0
    return ScoreCard(
        label=run_log.label, candidate_model=run_log.candidate_model,
        n_proposals=n_proposals, n_located=n_located, n_locate_miss=n_locate_miss,
        n_records=n_records, n_grounded=n_grounded, n_flagged=n_flagged,
        grounding_pass_rate=round(pass_rate, 4), end_to_end_yield=round(yield_rate, 4),
        cross_context_entities=cross_context_entities(records),
        smoking_gun=sg, smoking_gun_detail=sg_detail,
        chunks_seen=run_log.chunks_seen, chunks_missing=run_log.chunks_missing,
        chunks_per_min=round(run_log.chunks_seen / minutes, 2) if minutes else 0.0,
        records_per_min=round(n_records / minutes, 2) if minutes else 0.0,
        wall_seconds=round(run_log.wall_seconds, 2), extract_errors=run_log.extract_errors,
    )


def load_probe_records(schema: str) -> list[dict]:
    """Read the records the run grounded into the probe schema (with verdict + entity_refs)."""
    table = qualified(schema, "enrichment_records")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT record_id, source_chunk_id, actor, event_date, evidence_span, fields, "
            f"claim_relevance, flagged, provenance_validation, entity_refs FROM {table}"
        )
        rows = cur.fetchall()
    for r in rows:
        r["record_id"] = str(r["record_id"])
        r["source_chunk_id"] = str(r["source_chunk_id"])
    return rows


def score(schema: str, run_log) -> ScoreCard:
    """Load the probe schema rows and score the run."""
    return score_from_data(run_log, load_probe_records(schema))


# --- RESULTS.md rendering ------------------------------------------------------------
def results_row(card: ScoreCard) -> str:
    sg = "✅ YES" if card.smoking_gun else "❌ no"
    return (
        f"| {card.label} | {card.candidate_model} | {card.grounding_pass_rate:.0%} "
        f"({card.n_grounded}/{card.n_located}) | {card.cross_context_entities} | {sg} | "
        f"{card.chunks_per_min:.1f} ch/min, {card.records_per_min:.1f} rec/min |"
    )


def results_detail(card: ScoreCard) -> str:
    return (
        f"### {card.label} — `{card.candidate_model}`\n"
        f"- **Grounding pass-rate:** {card.grounding_pass_rate:.1%} "
        f"({card.n_grounded} grounded / {card.n_located} reached judge; "
        f"{card.n_flagged} flagged; {card.n_locate_miss} pointing misses of {card.n_proposals} proposals)\n"
        f"- **End-to-end yield:** {card.end_to_end_yield:.1%} ({card.n_records} records / {card.n_proposals} proposals)\n"
        f"- **Cross-context entities (>=2 chunks):** {card.cross_context_entities}\n"
        f"- **Smoking-gun (B. Smith reversal on {GOLD_CHUNK_ID[:8]}…):** "
        f"{'✅ captured + grounded' if card.smoking_gun else '❌ missed'} "
        f"— {card.smoking_gun_detail}\n"
        f"- **Throughput:** {card.chunks_per_min:.1f} chunks/min, {card.records_per_min:.1f} records/min "
        f"({card.chunks_seen} chunks in {card.wall_seconds:.0f}s; {card.chunks_missing} missing, "
        f"{card.extract_errors} extract errors)\n"
    )


RESULTS_TABLE_HEADER = (
    "| label | model | grounding% | cross-context | smoking-gun | throughput |\n"
    "|---|---|---|---|---|---|"
)
