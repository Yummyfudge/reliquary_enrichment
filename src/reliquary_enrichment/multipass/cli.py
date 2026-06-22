from __future__ import annotations

"""Multipass CLI — run the whole codex-refactor pipeline over the test set, end to end.

Wires the candidate ModelClient (all passes), the SHARED GroundingCore (Pass-3 grounder + the linker +
the MeaningWriter, all judge-gated against a throwaway probe_<label> schema), the §5 hardening (raw export
BEFORE drop — records AND the codex/meaning artifacts — score/read -> export -> drop, never drop unscored,
isolation proof), the gold-note FLOOR (checked FIRST), the GATE reading, and the 5-min heartbeat. The
NEEDLE (embedding) is deferred.

Building is pure code; a real run needs the candidate on the lane (re-acquire the BATON). The end-to-end
PASS CHAIN is exercised against fakes in tests/test_multipass_pipeline_integration.py (no lane/DB).
"""

import argparse
import json
import sys
from pathlib import Path

from reliquary_enrichment.entities import EntityResolver, EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import LiteLLMGroundingJudge
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.meaning_writer import MeaningWriter
from reliquary_enrichment.multipass.discriminative import DiscriminativeWeightPass
from reliquary_enrichment.multipass.export import export_codex, export_records
from reliquary_enrichment.multipass.fill_wiring import make_grounder, make_proposer
from reliquary_enrichment.multipass.floor import gold_floor_from_results
from reliquary_enrichment.multipass.gate import read_gate
from reliquary_enrichment.multipass.inputs import _DEFAULT_SLICE, assemble_inputs
from reliquary_enrichment.multipass.isolation import _isolation_unchanged, prod_enrichment_counts
from reliquary_enrichment.multipass.isolation_schema import create_probe_schema, drop_probe_schema
from reliquary_enrichment.multipass.link_wiring import make_link_proposer
from reliquary_enrichment.multipass.meaning_wiring import make_meaning_proposer
from reliquary_enrichment.multipass.pass_base import ModelClient, PassContext
from reliquary_enrichment.multipass.passes.pass1_prose import Pass1Prose
from reliquary_enrichment.multipass.passes.pass2_9_normalize import EntityNormalizationPass
from reliquary_enrichment.multipass.passes.pass2_objecttypes import Pass2ObjectTypes
from reliquary_enrichment.multipass.passes.pass3_fillvalues import Pass3FillValues
from reliquary_enrichment.multipass.passes.pass5_meaning import MeaningWriterPass
from reliquary_enrichment.multipass.passes.pass_link import CrossChunkLinkPass
from reliquary_enrichment.multipass.pipeline import Pipeline
from reliquary_enrichment.multipass.review import write_review
from reliquary_enrichment.multipass.walk_trace import write_walk_trace
from reliquary_enrichment.postgres.entity_store import PostgresEntityStore
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader
from reliquary_enrichment.postgres.link_store import PostgresLinkStore
from reliquary_enrichment.postgres.meaning_store import PostgresEnrichmentMeaningStore
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore
from reliquary_enrichment.write_enrichment import WriteEnrichment

# thinking-OFF for the qwen3 family (handoff §2); same mapping as the probe run.sh.
_THINK_OFF = {"chat_template_kwargs": {"enable_thinking": False}}


def all_passes() -> list:
    # §7 LITERAL run order (the list index IS the run order). EntityNormalizationPass is the "2.9" SLOT
    # but is positioned AFTER Pass 3: Pass 3 grounds typed-entity INSTANCES, normalization
    # canonicalizes/resolves what 3 grounded (codex-first sequencing). pass4_keywords / pass4_9_cleanup
    # are GONE (untyped lexical bags -> typed entities + the theme-flag). Pass 5 is the gated
    # MeaningWriter — the embedded side of the bright line (meaning NEVER routes through records).
    return [
        Pass1Prose(),               # 1   prose / non-prose
        Pass2ObjectTypes(),         # 2   typed entity types present (closed vocab)
        Pass3FillValues(),          # 3   MULTI-record grounded typed-entity instances
        EntityNormalizationPass(),  # 2.9 slot — runs AFTER 3: canonicalize + resolve
        DiscriminativeWeightPass(), #     weight + theme-flag (code, no LLM)
        CrossChunkLinkPass(),       #     bounded candidate-gen -> LinkEvents grounds
        MeaningWriterPass(),        # 5   gated local-fact meaning (embedded side)
    ]


def _build_services(*, schema: str, model, judge=None, label: str) -> dict:
    """Build the SHARED grounding core + all four stores + every per-pass service as one extras dict. The
    core is shared so Pass 3 (records), the linker (links + events), and the MeaningWriter (meaning) all
    judge against the SAME throwaway probe_<label> schema. Targets the probe schema; never prod."""
    core = GroundingCore(fragment_reader=PostgresFragmentReader(), handle_map=HandleMap(),
                         judge=judge or LiteLLMGroundingJudge())
    entity_store = PostgresEntityStore(schema=schema)
    record_store = PostgresEnrichmentRecordStore(schema=schema)
    link_store = PostgresLinkStore(schema=schema)
    meaning_store = PostgresEnrichmentMeaningStore(schema=schema)
    resolver = EntityResolver(entity_store)
    write_service = WriteEnrichment(core=core, record_store=record_store, entity_resolver=resolver)
    linker = LinkEvents(core=core, record_store=record_store, link_store=link_store,
                        event_materializer=EventMaterializer(entity_store))
    ws = f"mp-{label}"
    return {
        "proposer": make_proposer(model),
        "grounder": make_grounder(write_service, ws),
        "entity_resolver": resolver,
        "record_store": record_store,
        "entity_store": entity_store,
        "link_store": link_store,
        "linker": linker,
        "link_proposer": make_link_proposer(model),
        "meaning_writer": MeaningWriter(core=core, meaning_store=meaning_store),
        "meaning_proposer": make_meaning_proposer(model),
        "workstream_id": ws,
        "meaning_workstream_id": f"{ws}-meaning",
    }


def execute_multipass(
    *,
    label: str,
    candidate_model: str,
    api_model: str | None = None,
    pdf_filenames: tuple[str, ...] = (),
    slice_path: str = _DEFAULT_SLICE,
    out_dir: str | Path,
    extra_body: dict | None = None,
    drop_after: bool = True,
    model=None,
    services=None,        # full extras dict — injected to bypass the Postgres builder
    judge=None,
) -> dict:
    """Run the multipass pipeline; capture per-pass state; FLOOR-first + gate; §5 two-artifact
    export/isolation/drop (records AND codex+meaning)."""
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
    floor = None
    pass_errors: dict = {}
    scored_and_exported = False
    try:
        model = model or ModelClient(model=api_model or candidate_model, extra_body=extra_body or {})
        extras = services or _build_services(schema=schema, model=model, judge=judge, label=label)
        ctx = PassContext(model=model, model_name=candidate_model, extras=extras)
        results = Pipeline(passes=all_passes(), chunks=chunks, ctx=ctx, out_dir=out, emit=emit).run()
        # A contained crash in a WHOLE-STATE pass (pipeline.py CONTAIN) leaves {"error": ...} as its output
        # and the run otherwise proceeds — but e.g. a failed discriminative_weight silently empties the
        # theme stoplist (the CRQ-001 lever inverts to "all discriminators"). Surface it loudly so a
        # degraded codex is never mistaken for a clean run (step-10 review observability note).
        pass_errors = {name: r.outputs["error"] for name, r in results.items()
                       if isinstance(r.outputs, dict) and "error" in r.outputs}
        if pass_errors:
            emit(f"[multipass] WARNING — pass error(s); the codex may be DEGRADED: {pass_errors}")
        # FLOOR FIRST — the gold-note continuity anchor is the first acceptance, ahead of any rate.
        floor = gold_floor_from_results(extras["record_store"], results)
        (out / "floor.json").write_text(json.dumps(floor, indent=2, default=str))
        emit(f"[multipass] GOLD FLOOR: {'PASS' if floor['passed'] else 'FAIL'} "
             f"(b_smith_actor={floor['has_b_smith_actor']}, reversal={floor['has_reversal']}, "
             f"gold_records={floor['gold_records']})")
        gate = read_gate(results, record_store=extras["record_store"], entity_store=extras["entity_store"])
        (out / "gate.json").write_text(json.dumps(gate.as_dict(), indent=2, default=str))
        export_records(schema, out)               # §5: raw records BEFORE drop
        codex = export_codex(schema, out)         # §5: codex + meaning (entities/links/meaning) BEFORE drop
        emit(f"[multipass] exported codex artifacts: {codex}")
        # the gold-target assembly walk over the EXPORTED codex (survives the drop) — §10 (4) acceptance
        trace = write_walk_trace(out)
        wt = json.loads(trace.read_text())
        emit(f"[multipass] gold walk: reached={wt.get('reached')} "
             f"via_link={wt.get('reached_via_grounded_link')} "
             f"gold_link_neighbours={len(wt.get('gold_link_neighbours', []))}")
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
    if not iso["prod_untouched"]:
        # Re-homed from the deleted probe's breach-raise (§13 — keep the safety): the harness writes
        # ONLY its throwaway schema, so a changed prod enrichment count is a hard alarm, not a logged
        # footnote. Evidence is already in isolation.json (recorded in the finally above).
        raise RuntimeError(
            f"ISOLATION BREACH: prod enrichment changed during run {label!r} "
            f"(before={before}, after={after}) — investigate immediately."
        )
    return {"gate": gate.as_dict() if gate else None, "floor": floor, "pass_errors": pass_errors,
            **iso, "n_chunks": len(chunks)}


def main(argv: list[str] | None = None) -> int:
    import os
    ap = argparse.ArgumentParser(description="Run the multipass test harness for one candidate.")
    ap.add_argument("candidate_model", help="candidate identity (e.g. llama-4-scout)")
    ap.add_argument("label", help="probe label -> probe_<label> schema + results dir")
    ap.add_argument("--api-model", default=None, help="LiteLLM alias to call (default big-thinker)")
    ap.add_argument("--pdf", action="append", default=[], help="page-range PDF filename (repeatable)")
    ap.add_argument("--slice", default=_DEFAULT_SLICE, help="frozen chunk_id slice")
    ap.add_argument("--out", default=None, help="output dir (default multipass/results/<label>)")
    ap.add_argument("--keep-schema", action="store_true")
    args = ap.parse_args(argv)

    api_model = args.api_model or os.getenv("PROBE_CANDIDATE_MODEL") or "big-thinker"
    extra_body = _THINK_OFF if args.candidate_model.startswith(("qwen3.5", "qwen3-14b", "qwen3-omni")) else {}
    out_dir = args.out or f"multipass/results/{args.label}"
    result = execute_multipass(
        label=args.label, candidate_model=args.candidate_model, api_model=api_model,
        pdf_filenames=tuple(args.pdf), slice_path=args.slice, out_dir=out_dir,
        extra_body=extra_body, drop_after=not args.keep_schema,
    )
    g = result["gate"] or {}
    floor = result["floor"] or {}
    print(json.dumps({"candidate": args.candidate_model, "n_chunks": result["n_chunks"],
                      "gold_floor_passed": floor.get("passed"),
                      "faithfulness_rate": g.get("faithfulness_rate"),
                      "chunks_grounded": g.get("chunks_grounded"),
                      "prod_untouched": result["prod_untouched"]}, indent=2))
    # The gold-note FLOOR is the hard continuity anchor (§10.2): a failed floor is a non-zero exit so the
    # run is not mistaken for a pass, even when the rate looks fine. The export already ran (inspect why).
    return 0 if floor.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
