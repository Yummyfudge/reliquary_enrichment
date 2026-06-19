from __future__ import annotations

"""Multipass CLI — run the whole pipeline over the test set, end to end.

Wires the candidate ModelClient (all passes), the Pass-3 grounder (write_enrichment over a
throwaway probe_<label> schema, judge-gated), the §5 hardening carried forward (raw export
BEFORE drop, score/read -> export -> drop, never drop unscored, isolation proof), the GATE
reading, and the 5-min heartbeat. The NEEDLE is deferred (gate-only v0).

Building is pure code; a real run needs the candidate on the lane (re-acquire the BATON). The
end-to-end path is dry-runnable on the scratch DB with injected fakes (no lane).
"""

import argparse
import json
import sys
from pathlib import Path

from reliquary_enrichment.entities import EntityResolver
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import LiteLLMGroundingJudge
from reliquary_enrichment.multipass.fill_wiring import make_grounder, make_proposer
from reliquary_enrichment.multipass.gate import read_gate
from reliquary_enrichment.multipass.inputs import assemble_inputs
from reliquary_enrichment.multipass.pass_base import ModelClient, PassContext
from reliquary_enrichment.multipass.passes.pass1_prose import Pass1Prose
from reliquary_enrichment.multipass.passes.pass2_9_consolidate import Pass2_9Consolidate
from reliquary_enrichment.multipass.passes.pass2_objecttypes import Pass2ObjectTypes
from reliquary_enrichment.multipass.passes.pass3_fillvalues import Pass3FillValues
from reliquary_enrichment.multipass.passes.pass4_9_cleanup import Pass4_9Cleanup
from reliquary_enrichment.multipass.passes.pass4_keywords import Pass4Keywords
from reliquary_enrichment.multipass.passes.pass5_meaning import Pass5Meaning
from reliquary_enrichment.multipass.pipeline import Pipeline
from reliquary_enrichment.multipass.review import write_review
from reliquary_enrichment.postgres.entity_store import PostgresEntityStore
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore
from reliquary_enrichment.probe.cli import _isolation_unchanged, prod_enrichment_counts
from reliquary_enrichment.probe.export import export_records
from reliquary_enrichment.probe.schema import create_probe_schema, drop_probe_schema
from reliquary_enrichment.write_enrichment import WriteEnrichment

# thinking-OFF for the qwen3 family (handoff §2); same mapping as the probe run.sh.
_THINK_OFF = {"chat_template_kwargs": {"enable_thinking": False}}


def all_passes() -> list:
    return [Pass1Prose(), Pass2ObjectTypes(), Pass2_9Consolidate(), Pass3FillValues(),
            Pass4Keywords(), Pass4_9Cleanup(), Pass5Meaning()]


def _build_write_service(schema: str, judge=None) -> WriteEnrichment:
    reader = PostgresFragmentReader()
    core = GroundingCore(fragment_reader=reader, handle_map=HandleMap(),
                         judge=judge or LiteLLMGroundingJudge())
    return WriteEnrichment(
        core=core,
        record_store=PostgresEnrichmentRecordStore(schema=schema),
        entity_resolver=EntityResolver(PostgresEntityStore(schema=schema)),
    )


def execute_multipass(
    *,
    label: str,
    candidate_model: str,
    api_model: str | None = None,
    pdf_filenames: tuple[str, ...] = (),
    slice_path: str = "probe/slice/chunk_ids.txt",
    out_dir: str | Path,
    extra_body: dict | None = None,
    drop_after: bool = True,
    model=None,
    fill_services=None,   # (proposer, grounder) — injected for the scratch dry-run
    judge=None,
) -> dict:
    """Run the multipass pipeline; capture per-pass state + gate; §5 export/isolation/drop."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chunks = assemble_inputs(slice_path=slice_path, pdf_filenames=pdf_filenames)
    progress_file = (out / "progress.log").open("a", buffering=1)

    def emit(line: str) -> None:
        progress_file.write(line + "\n")
        print(line, flush=True)

    before = prod_enrichment_counts()
    schema = create_probe_schema(label)
    gate = None
    scored_and_exported = False
    try:
        model = model or ModelClient(model=api_model or candidate_model, extra_body=extra_body or {})
        if fill_services is not None:
            proposer, grounder = fill_services
        else:
            write_service = _build_write_service(schema, judge)
            proposer = make_proposer(model)
            grounder = make_grounder(write_service, f"mp-{label}")
        ctx = PassContext(model=model, model_name=candidate_model,
                          extras={"proposer": proposer, "grounder": grounder})
        results = Pipeline(passes=all_passes(), chunks=chunks, ctx=ctx, out_dir=out, emit=emit).run()
        gate = read_gate(results)
        (out / "gate.json").write_text(json.dumps(gate.as_dict(), indent=2, default=str))
        export_records(schema, out)               # §5: raw records BEFORE drop
        write_review(out)                          # basic enriched-data review.md (Joe's ask)
        scored_and_exported = True
    finally:
        progress_file.close()
        after = prod_enrichment_counts()
        iso = {
            "prod_untouched": _isolation_unchanged(before, after),
            "prod_counts_before": before, "prod_counts_after": after,
            "proof": ("count-verified" if before.get("_access") == "ok"
                      else "structural: prod enrichment read-denied to the probe role"),
            "scored_and_exported": scored_and_exported,
        }
        (out / "isolation.json").write_text(json.dumps(iso, indent=2, default=str))
        if drop_after and scored_and_exported:
            drop_probe_schema(label)
        elif not scored_and_exported:
            print(f"[multipass] KEEPING schema probe_{label}: pipeline/export did not complete "
                  "— investigate before dropping.", file=sys.stderr)
    return {"gate": gate.as_dict() if gate else None, **iso, "n_chunks": len(chunks)}


def main(argv: list[str] | None = None) -> int:
    import os
    ap = argparse.ArgumentParser(description="Run the multipass test harness for one candidate.")
    ap.add_argument("candidate_model", help="candidate identity (e.g. llama-4-scout)")
    ap.add_argument("label", help="probe label -> probe_<label> schema + results dir")
    ap.add_argument("--api-model", default=None, help="LiteLLM alias to call (default big-thinker)")
    ap.add_argument("--pdf", action="append", default=[], help="page-range PDF filename (repeatable)")
    ap.add_argument("--out", default=None, help="output dir (default multipass/results/<label>)")
    ap.add_argument("--keep-schema", action="store_true")
    args = ap.parse_args(argv)

    api_model = args.api_model or os.getenv("PROBE_CANDIDATE_MODEL") or "big-thinker"
    extra_body = _THINK_OFF if args.candidate_model.startswith(("qwen3.5", "qwen3-14b", "qwen3-omni")) else {}
    out_dir = args.out or f"multipass/results/{args.label}"
    result = execute_multipass(
        label=args.label, candidate_model=args.candidate_model, api_model=api_model,
        pdf_filenames=tuple(args.pdf), out_dir=out_dir, extra_body=extra_body,
        drop_after=not args.keep_schema,
    )
    g = result["gate"] or {}
    print(json.dumps({"candidate": args.candidate_model, "n_chunks": result["n_chunks"],
                      "faithfulness_rate": g.get("faithfulness_rate"),
                      "chunks_grounded": g.get("chunks_grounded"),
                      "prod_untouched": result["prod_untouched"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
