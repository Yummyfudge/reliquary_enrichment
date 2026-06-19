"""multipass — the multi-pass test harness (retires the single-pass probe).

One focused job per PASS, each pass running the whole file before the next (vs the single-pass
"elephant" that timed models out). Passes: 1 prose / 2 object-types / 2.9 consolidate / 3
fill-values / 4 keywords / 4.9 cleanup / 5 meaning. Two SEPARATE readings: the GATE (per-chunk
faithfulness, judge-side) and the NEEDLE (gold-note rank, big_thinker-side; deferred for v0).

Reuses the probe's bones (grounding core + judge, write_enrichment, the frozen slice, the
audition-2 hardening: big max_tokens + long deadline + thinking-off). See
notes/multipass-design-v0.md.
"""
