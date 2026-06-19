from __future__ import annotations

"""Basic enriched-data review — a readable surface over the glass-box state (Joe's light ask).

Reads a run's results dir (inputs.json + per-pass <name>.json + records.jsonl) and renders
review.md: per chunk, ORIGINAL text -> ENRICHED output (object-types/values, keywords, meaning),
the per-pass PROGRESSION (what changed), and a top summary of the final enriched shape
(consolidated schema, keyword vocab, grounded count). Form is intentionally basic — no UI, no
quality scoring (the needle is parked). Just: produce the data, and look at it.
"""

import json
from pathlib import Path


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _pass_outputs(results: Path, name: str) -> dict:
    return _load_json(results / f"{name}.json", {}).get("outputs", {}) or {}


def render_review(results_dir: str | Path) -> str:
    r = Path(results_dir)
    inputs = _load_json(r / "inputs.json", {})
    prose = _pass_outputs(r, "1_prose")
    otypes = _pass_outputs(r, "2_objecttypes")
    consolidate = _load_json(r / "2_9_consolidate.json", {}).get("outputs", {})
    fill = _pass_outputs(r, "3_fillvalues")
    cleanup = _load_json(r / "4_9_cleanup.json", {}).get("outputs", {})
    meaning = _pass_outputs(r, "5_meaning")

    mapping = consolidate.get("mapping", {}) if isinstance(consolidate, dict) else {}
    cleaned = cleanup.get("cleaned", {}) if isinstance(cleanup, dict) else {}

    # grounded records (records.jsonl) keyed by source_chunk_id
    records: dict[str, list] = {}
    rj = r / "records.jsonl"
    if rj.exists():
        for line in rj.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                records.setdefault(str(rec.get("source_chunk_id")), []).append(rec)

    grounded_chunks = sum(1 for o in fill.values() if o.get("grounded"))
    lines = [
        "# Enriched-data review",
        "",
        f"- **chunks:** {len(inputs)}",
        f"- **grounded records:** {grounded_chunks}/{len(fill)} chunks "
        f"({sum(len(v) for v in records.values())} records)",
        f"- **consolidated object-type schema (2.9 final):** "
        f"{', '.join(consolidate.get('final', [])) or '—'}",
        f"- **keyword vocabulary (4.9 final):** {', '.join(cleanup.get('final', [])[:40]) or '—'}",
        "",
        "---",
        "",
    ]

    for cid, meta in inputs.items():
        short = cid[:8]
        lines.append(f"## {short} · {meta.get('source', '')}")
        lines.append("**ORIGINAL:**")
        lines.append("> " + (meta.get("text", "") or "").replace("\n", "\n> "))
        lines.append("")
        # ENRICHED
        raw_types = otypes.get(cid, {}).get("object_types", [])
        canon = sorted({mapping.get(t, t) for t in raw_types})
        lines.append("**ENRICHED:**")
        lines.append(f"- prose?: `{prose.get(cid, {}).get('label', '—')}`")
        lines.append(f"- object-types: {raw_types or '—'} → canonical: {canon or '—'}")
        f3 = fill.get(cid, {})
        if f3.get("grounded"):
            for rec in records.get(cid, []):
                lines.append(f"- record `{rec.get('record_type')}` / {(rec.get('provenance_validation') or {}).get('verdict')}: "
                             f"actor={rec.get('actor')!r} date={rec.get('event_date')!r} "
                             f"fields={json.dumps(rec.get('fields') or {}, ensure_ascii=False)}")
                lines.append(f"    evidence: {rec.get('evidence_span')!r}")
        else:
            lines.append(f"- record: _not grounded_ (reason={f3.get('reason_code')}, "
                         f"attempts={f3.get('attempts')}, confidence={f3.get('confidence_trajectory')})")
        lines.append(f"- keywords: {cleaned.get(cid, []) or '—'}")
        m = meaning.get(cid, {})
        lines.append(f"- meaning: {m.get('claim_meaning', '—')}")
        if m.get("questions_answered"):
            lines.append(f"    answers: {m['questions_answered']}")
        # PROGRESSION (what changed, pass by pass)
        lines.append("")
        lines.append("<details><summary>progression (per-pass)</summary>")
        lines.append("")
        lines.append(f"- 1_prose: `{prose.get(cid, {}).get('label', '—')}`")
        lines.append(f"- 2_objecttypes: {raw_types}")
        lines.append(f"- 3_fillvalues: grounded={f3.get('grounded')} attempts={f3.get('attempts')} "
                     f"confidence={f3.get('confidence_trajectory')}")
        lines.append(f"- 4_keywords→cleaned: {cleaned.get(cid, [])}")
        lines.append(f"- 5_meaning: {m.get('claim_meaning', '—')}")
        lines.append("</details>")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_review(results_dir: str | Path, out_name: str = "review.md") -> Path:
    out = Path(results_dir) / out_name
    out.write_text(render_review(results_dir))
    return out


def main(argv: list[str] | None = None) -> int:
    """Regenerate review.md from a run's results dir: python -m ...multipass.review <dir>."""
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    out = write_review(argv[0] if argv else ".")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
