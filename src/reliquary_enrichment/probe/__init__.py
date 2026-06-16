"""probe — the extraction probe harness (evaluate models on the real extraction job).

Drives a CANDIDATE model (the variable) as the extraction agent over a LOCKED corpus slice,
writing through the real `write_enrichment` (fixed Qwen2.5-14B judge gates every record) into
a THROWAWAY `probe_<label>` schema, then scores grounding / cross-context / smoking-gun /
throughput. The corpus is read-only; prod enrichment tables are never touched.

Decisions P1-P4 (notes/decisions-log.md): candidate extracts + judge fixed; run on mcp-hub +
ssh llm-lxc for lane swaps; engineer writes the slice-builder, Architect freezes it; v1
cross-context = shared entities across chunks.
"""
