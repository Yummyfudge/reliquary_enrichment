from __future__ import annotations

"""Basic enriched-data review — a readable surface over the codex-refactor glass-box (Joe's light ask).

Reads a run's results dir (inputs.json + per-pass <name>.json + records.jsonl + meaning.jsonl) and renders
review.md: per chunk, ORIGINAL text -> the grounded CODEX (typed entities on each record) + the gated
MEANING (stored local fact or the reason it was rejected), the per-pass PROGRESSION, and a top summary of
the codex shape (entities, themes, links, meanings). Form is intentionally basic — produce the data and
look at it. The needle (embedding/ranking) is parked.
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


def _by_chunk(results: Path, filename: str, key: str = "source_chunk_id") -> dict[str, list]:
    out: dict[str, list] = {}
    p = results / filename
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue                       # skip a malformed line rather than crash the review
                out.setdefault(str(row.get(key)), []).append(row)
    return out


def render_review(results_dir: str | Path) -> str:
    r = Path(results_dir)
    inputs = _load_json(r / "inputs.json", {})
    prose = _pass_outputs(r, "1_prose")
    otypes = _pass_outputs(r, "2_objecttypes")
    fill = _pass_outputs(r, "3_fillvalues")
    meaning_pass = _pass_outputs(r, "5_meaning")
    normalize = _load_json(r / "2_9_normalize.json", {}).get("outputs", {})
    discriminative = _load_json(r / "discriminative_weight.json", {}).get("outputs", {})
    links = _load_json(r / "cross_chunk_link.json", {}).get("outputs", {})

    records = _by_chunk(r, "records.jsonl")
    meanings = {cid: rows[0].get("claim_meaning") for cid, rows in _by_chunk(r, "meaning.jsonl").items()}

    final_entities = normalize.get("final", {}) if isinstance(normalize, dict) else {}
    themes = discriminative.get("themes", []) if isinstance(discriminative, dict) else []
    grounded_chunks = sum(1 for o in fill.values() if o.get("grounded"))
    lines = [
        "# Enriched-data review (codex)",
        "",
        f"- **chunks:** {len(inputs)}",
        f"- **grounded records:** {grounded_chunks}/{len(fill)} chunks "
        f"({sum(len(v) for v in records.values())} records)",
        f"- **codex entities:** {len(final_entities)}  ·  **themes:** {len(themes)} "
        f"({', '.join(themes[:12]) or '—'})",
        f"- **cross-chunk links:** {links.get('n_links', 0) if isinstance(links, dict) else 0}",
        f"- **meanings stored:** {len(meanings)}",
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
        raw_types = otypes.get(cid, {}).get("object_types", [])
        lines.append("**ENRICHED:**")
        lines.append(f"- prose?: `{prose.get(cid, {}).get('label', '—')}`")
        lines.append(f"- object-types: {raw_types or '—'}")
        f3 = fill.get(cid, {})
        if f3.get("grounded"):
            for rec in records.get(cid, []):
                refs = ", ".join(f"{x.get('entity_type')}:{x.get('canonical')}"
                                 for x in (rec.get("entity_refs") or []))
                lines.append(f"- record `{rec.get('record_type')}` / "
                             f"{(rec.get('provenance_validation') or {}).get('verdict')}: "
                             f"actor={rec.get('actor')!r} date={rec.get('event_date')!r} "
                             f"fields={json.dumps(rec.get('fields') or {}, ensure_ascii=False)}")
                lines.append(f"    evidence: {rec.get('evidence_span')!r}")
                if refs:
                    lines.append(f"    entities: {refs}")
        else:
            lines.append(f"- record: _not grounded_ (reason={f3.get('reason_code')}, "
                         f"attempts={f3.get('attempts')}, confidence={f3.get('confidence_trajectory')})")
        m = meaning_pass.get(cid, {})
        if cid in meanings:
            lines.append(f"- meaning: {meanings[cid]!r}" + ("  ⚑flagged" if m.get("flagged") else ""))
        else:
            lines.append(f"- meaning: _not stored_ (reason={m.get('reason_code', '—')})")
        # PROGRESSION (what changed, pass by pass)
        lines.append("")
        lines.append("<details><summary>progression (per-pass)</summary>")
        lines.append("")
        lines.append(f"- 1_prose: `{prose.get(cid, {}).get('label', '—')}`")
        lines.append(f"- 2_objecttypes: {raw_types}")
        lines.append(f"- 3_fillvalues: grounded={f3.get('grounded')} attempts={f3.get('attempts')} "
                     f"confidence={f3.get('confidence_trajectory')}")
        lines.append(f"- 5_meaning: ok={m.get('ok')} reason={m.get('reason_code', '—')} "
                     f"flagged={m.get('flagged')}")
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
