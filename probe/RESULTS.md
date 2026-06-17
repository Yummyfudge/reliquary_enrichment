# Extraction Probe — Results

Candidates scored on the **real extraction job** (drive `write_enrichment` over the locked slice; the fixed Qwen2.5-14B judge gates every record). Smoking-gun = does the model capture+ground the B. Smith reversal on the gold note — the decider.

| label | model | grounding% | cross-context | smoking-gun | throughput |
|---|---|---|---|---|---|
| qwen3_14b | qwen3-14b | 69% (179/258) | 26 | ✅ YES | 1.5 ch/min, 2.0 rec/min |

## Per-model detail

### qwen3_14b — `qwen3-14b`
- **Grounding pass-rate:** 69.4% (179 grounded / 258 reached judge; 1 flagged; 13 pointing misses of 271 proposals)
- **End-to-end yield:** 66.4% (180 records / 271 proposals)
- **Cross-context entities (>=2 chunks):** 26
- **Smoking-gun (B. Smith reversal on 89503c71…):** ✅ captured + grounded — {'record_id': '576c2c6b-7c02-45bc-a3f4-068d3973eb04', 'signals': {'actor_smith': True, 'reversal_direction': 'back to', 'condition_swap': True}}
- **Throughput:** 1.5 chunks/min, 2.0 records/min (131 chunks in 5271s; 0 missing, 0 extract errors)

