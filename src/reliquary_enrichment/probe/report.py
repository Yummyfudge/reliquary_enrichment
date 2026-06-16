from __future__ import annotations

"""Aggregate every results/<label>/scorecard.json into probe/RESULTS.md (table + details)."""

import json
import sys
from pathlib import Path

from reliquary_enrichment.probe.scoring import (
    RESULTS_TABLE_HEADER,
    ScoreCard,
    results_detail,
    results_row,
)


def render(results_dir: str | Path) -> str:
    cards = []
    for sc in sorted(Path(results_dir).glob("*/scorecard.json")):
        cards.append(ScoreCard(**json.loads(sc.read_text())))
    lines = [
        "# Extraction Probe — Results",
        "",
        "Candidates scored on the **real extraction job** (drive `write_enrichment` over the "
        "locked slice; the fixed Qwen2.5-14B judge gates every record). Smoking-gun = does the "
        "model capture+ground the B. Smith reversal on the gold note — the decider.",
        "",
        RESULTS_TABLE_HEADER,
    ]
    lines += [results_row(c) for c in cards] or ["| _(no runs yet)_ |  |  |  |  |  |"]
    lines += ["", "## Per-model detail", ""]
    lines += [results_detail(c) for c in cards]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    results_dir = argv[0] if argv else "probe/results"
    out = argv[1] if len(argv) > 1 else "probe/RESULTS.md"
    Path(out).write_text(render(results_dir))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
