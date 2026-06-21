from __future__ import annotations

"""Inspection export — stored record vs the ORIGINAL Fragment text (the §5 raw-export-before-drop).

Rehomed into `multipass/` from the retired `probe/` (codex refactor §13). The harness drops its
throwaway schema after export, so without this the detailed records vanish. ``export_records`` runs
BEFORE the drop and writes two artifacts under the run's results dir, so every run stays inspectable:
  * records.jsonl — one grounded record per line (machine-readable).
  * records.txt   — human-readable: per Fragment, the ORIGINAL chunk_text, then each record's
    code-sliced Evidence Span + fields + verdict, with a byte-exact check that
    ``evidence_span == chunk_text[char_start:char_end]`` (the grounding proof, visible).

`claim_relevance` is gone (codex refactor §5.3 — whole-claim significance relocated; never written).
"""

import json
from pathlib import Path

from reliquary_enrichment.postgres.connection import connect, qualified


def _load(schema: str):
    records_tbl = qualified(schema, "enrichment_records")
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT record_id, source_chunk_id, record_type, tier, char_start, char_end, "
            f"evidence_span, actor, event_date, fields, page, document, "
            f"provenance_validation, entity_refs FROM {records_tbl} "
            f"ORDER BY source_chunk_id, char_start"
        )
        recs = cur.fetchall()
        chunk_ids = sorted({str(r["source_chunk_id"]) for r in recs})
        texts: dict[str, str] = {}
        if chunk_ids:
            cur.execute(
                "SELECT claim_chunk_id, payload->>'chunk_text' AS t "
                "FROM context_reliquary.claim_chunks WHERE claim_chunk_id = ANY(%s)",
                (chunk_ids,),
            )
            texts = {str(r["claim_chunk_id"]): (r["t"] or "") for r in cur.fetchall()}
    return recs, texts


def export_records(schema: str, out_dir: str | Path) -> int:
    """Write records.jsonl + records.txt for the run. Returns the record count."""
    recs, texts = _load(schema)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Full raw record per line — incl. provenance_validation (verdict + judge id + hashes) and
    # entity_refs — so the run is independently re-analyzable after the schema is dropped.
    with (out / "records.jsonl").open("w") as fh:
        for r in recs:
            fh.write(json.dumps({
                "record_id": str(r["record_id"]),
                "source_chunk_id": str(r["source_chunk_id"]),
                "record_type": r["record_type"], "tier": r["tier"],
                "char_start": r["char_start"], "char_end": r["char_end"],
                "evidence_span": r["evidence_span"], "actor": r["actor"],
                "event_date": r["event_date"],
                "fields": r["fields"],
                "provenance_validation": r["provenance_validation"],
                "verdict": (r["provenance_validation"] or {}).get("verdict"),
                "entity_refs": r["entity_refs"],
                "page": r["page"], "document": r["document"],
            }, default=str, ensure_ascii=False) + "\n")

    by_chunk: dict[str, list] = {}
    for r in recs:
        by_chunk.setdefault(str(r["source_chunk_id"]), []).append(r)

    lines: list[str] = [
        f"# Extracted records vs original text — {len(recs)} records across {len(by_chunk)} Fragments",
        "# (span==source slice proves the stored Evidence Span is byte-exact from the corpus)\n",
    ]
    for cid, rs in by_chunk.items():
        text = texts.get(cid, "")
        lines.append("=" * 100)
        lines.append(f"FRAGMENT {cid}  (page {rs[0]['page']}, {rs[0]['document']}) — {len(rs)} records")
        lines.append("-" * 100)
        lines.append("ORIGINAL chunk_text:")
        lines.append(text)
        lines.append("-" * 100)
        for r in rs:
            sliced = text[r["char_start"]:r["char_end"]] if text else ""
            match = "OK" if sliced == r["evidence_span"] else "MISMATCH!"
            verdict = (r["provenance_validation"] or {}).get("verdict")
            lines.append(
                f"  [{r['record_type']} / {r['tier']} / {verdict}]  "
                f"offsets {r['char_start']}..{r['char_end']}  (span==source slice: {match})"
            )
            lines.append(f"    EVIDENCE SPAN  : {r['evidence_span']!r}")
            if r["actor"]:
                lines.append(f"    actor          : {r['actor']}")
            if r["event_date"]:
                lines.append(f"    event_date     : {r['event_date']}")
            if r["fields"]:
                lines.append(f"    fields         : {json.dumps(r['fields'], ensure_ascii=False)}")
            lines.append("")
    (out / "records.txt").write_text("\n".join(lines))
    return len(recs)
