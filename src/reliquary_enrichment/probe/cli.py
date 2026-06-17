from __future__ import annotations

"""Probe orchestration — wire services to the probe schema, run, score, tear down.

`execute_probe` is the testable core (inject a fake extractor/judge for a deterministic dry
run); `main` is the CLI `run.sh` calls. Isolation guard: prod enrichment counts are snapshot
before/after and asserted unchanged when readable — and the harness only ever holds the scoped
`probe` role, which physically cannot write prod enrichment.
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

from reliquary_enrichment.entities import EntityResolver
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import LiteLLMGroundingJudge
from reliquary_enrichment.postgres.connection import connect, qualified
from reliquary_enrichment.postgres.entity_store import PostgresEntityStore
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore
from reliquary_enrichment.probe.export import export_records
from reliquary_enrichment.probe.extraction import CandidateExtractor
from reliquary_enrichment.probe.runner import ProbeRunner
from reliquary_enrichment.probe.schema import create_probe_schema, drop_probe_schema
from reliquary_enrichment.probe.scoring import score
from reliquary_enrichment.read_tools import ReadTools

_PROD_SCHEMA = "context_reliquary"
_ENRICHMENT_TABLES = ("enrichment_records", "codex_entities", "enrichment_links")


def load_chunk_ids(path: str | Path) -> list[str]:
    """Read the frozen slice fixture — one UUID per line, '#' comments + blanks ignored."""
    ids = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line.split()[0])
    return ids


def prod_enrichment_counts() -> dict:
    """Row counts of the PROD enrichment tables for the isolation proof (never None).

    Returns ``{table: count, "_access": "ok"}`` when readable (needs SELECT on the prod
    enrichment tables — see schema/grants.probe_read.sql). If the probe role is
    permission-denied, returns ``{"_access": "permission_denied"}`` — itself proof the harness
    cannot even READ prod enrichment, let alone write it (the wall, stronger). Either way the
    run records its own isolation evidence rather than leaving nulls (F5).
    """
    out: dict = {}
    try:
        with connect() as conn, conn.cursor() as cur:
            for t in _ENRICHMENT_TABLES:
                cur.execute(f"SELECT count(*) AS n FROM {qualified(_PROD_SCHEMA, t)}")
                out[t] = cur.fetchone()["n"]
        out["_access"] = "ok"
        return out
    except psycopg.errors.InsufficientPrivilege:
        return {"_access": "permission_denied"}
    except Exception as exc:  # pragma: no cover - operational
        return {"_access": f"error: {type(exc).__name__}"}


def _isolation_unchanged(before: dict, after: dict) -> bool:
    """True if prod enrichment is provably unchanged: equal counts, or read-denied both times."""
    return before == after


def execute_probe(
    *,
    label: str,
    candidate_model: str,
    chunk_ids: list[str],
    out_dir: str | Path,
    extractor=None,
    judge=None,
    drop_after: bool = True,
) -> dict:
    """Run one candidate over the slice into a fresh probe_<label> schema; score; tear down.

    Returns a dict: {scorecard, prod_untouched, prod_counts_before/after}. Persists
    attempts.jsonl, run_meta.json, scorecard.json under out_dir.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    before = prod_enrichment_counts()
    schema = create_probe_schema(label)
    card = None
    scored_and_exported = False
    try:
        handle_map = HandleMap()
        reader = PostgresFragmentReader()
        core = GroundingCore(
            fragment_reader=reader, handle_map=handle_map,
            judge=judge or LiteLLMGroundingJudge(),
        )
        from reliquary_enrichment.write_enrichment import WriteEnrichment
        write_service = WriteEnrichment(
            core=core,
            record_store=PostgresEnrichmentRecordStore(schema=schema),
            entity_resolver=EntityResolver(PostgresEntityStore(schema=schema)),
        )
        read_service = ReadTools(fragment_reader=reader, handle_map=handle_map)
        # Live heartbeat: tail -f probe/results/<label>/progress.log to watch progress + ETA.
        progress_file = (out / "progress.log").open("a", buffering=1)

        def _progress(line: str) -> None:
            progress_file.write(line + "\n")
            print(line, flush=True)  # also into run.sh's log

        runner = ProbeRunner(
            extractor=extractor or CandidateExtractor(model=candidate_model),
            write_service=write_service, read_service=read_service,
            label=label, candidate_model=candidate_model, schema=schema,
            progress=_progress,
        )
        try:
            run_log = runner.run(chunk_ids)
        finally:
            progress_file.close()
        # ORDER: score -> export -> (only then) drop. The schema stays LIVE until BOTH its
        # score and its raw export are on disk — never dropped unscored (F2).
        run_log.persist(out)
        card = score(schema, run_log)
        (out / "scorecard.json").write_text(json.dumps(card.as_dict(), indent=2))
        export_records(schema, out)         # raw records (evidence_span + PV + entity_refs)
        scored_and_exported = True
    finally:
        after = prod_enrichment_counts()
        untouched = _isolation_unchanged(before, after)
        isolation = {
            "prod_untouched": untouched,
            "prod_counts_before": before,
            "prod_counts_after": after,
            "proof": ("count-verified" if before.get("_access") == "ok"
                      else "structural: prod enrichment read-denied to the probe role"),
            "scored_and_exported": scored_and_exported,
        }
        (out / "isolation.json").write_text(json.dumps(isolation, indent=2, default=str))
        if drop_after and scored_and_exported:
            drop_probe_schema(label)
        elif not scored_and_exported:
            print(f"[probe] KEEPING schema {schema}: score/export did not complete — "
                  "investigate before dropping (never drop unscored).", file=sys.stderr)

    if untouched is False:
        raise RuntimeError(f"ISOLATION BREACH: prod enrichment changed {before} -> {after}")
    return {"scorecard": card.as_dict() if card else None, **isolation}


def main(argv: list[str] | None = None) -> int:
    import os
    ap = argparse.ArgumentParser(description="Run the extraction probe for one candidate.")
    ap.add_argument("candidate_model", help="candidate IDENTITY for reporting (e.g. qwen2.5-72b)")
    ap.add_argument("label", help="probe label -> probe_<label> schema + results/<label>/")
    ap.add_argument("--api-model", default=None,
                    help="LiteLLM alias to CALL (default $PROBE_CANDIDATE_MODEL, else the identity). "
                         "In the lane-swap loop this is the stable alias (big-thinker).")
    ap.add_argument("--slice", default="probe/slice/chunk_ids.txt", help="frozen chunk_id fixture")
    ap.add_argument("--out", default=None, help="output dir (default probe/results/<label>)")
    ap.add_argument("--keep-schema", action="store_true", help="don't drop probe_<label> after scoring")
    args = ap.parse_args(argv)

    chunk_ids = load_chunk_ids(args.slice)
    if not chunk_ids:
        print(f"no chunk_ids in {args.slice} — is the slice frozen?", file=sys.stderr)
        return 2
    api_model = args.api_model or os.getenv("PROBE_CANDIDATE_MODEL") or args.candidate_model
    out_dir = args.out or f"probe/results/{args.label}"
    result = execute_probe(
        label=args.label, candidate_model=args.candidate_model,
        chunk_ids=chunk_ids, out_dir=out_dir, drop_after=not args.keep_schema,
        extractor=CandidateExtractor(model=api_model),
    )
    card = result["scorecard"]
    print(json.dumps({
        "label": card["label"], "model": card["candidate_model"],
        "grounding_pass_rate": card["grounding_pass_rate"],
        "cross_context_entities": card["cross_context_entities"],
        "smoking_gun": card["smoking_gun"],
        "records_per_min": card["records_per_min"],
        "prod_untouched": result["prod_untouched"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
