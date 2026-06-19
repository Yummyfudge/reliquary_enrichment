# Extraction Probe — Results

Candidates scored on the **real extraction job** (drive `write_enrichment` over the locked slice; the fixed Qwen2.5-14B judge gates every record). Smoking-gun = does the model capture+ground the B. Smith reversal on the gold note — the decider.

| label | model | grounding% | coverage | cross-context | smoking-gun | throughput |
|---|---|---|---|---|---|---|
| demo | qwen3-14b | 86% (12/14) | 0/7 | 0 | ✅ YES | 1.5 ch/min, 2.6 rec/min |
| gemma_4_31b | gemma-4-31b | 100% (22/22) | 22/131 | 3 | ❌ no | 0.6 ch/min, 0.1 rec/min |
| llama_3_3_70b | llama-3.3-70b | 69% (257/373) | 77/131 | 37 | ❌ no | 0.7 ch/min, 1.4 rec/min |
| llama_4_scout | llama-4-scout | 74% (629/849) | 115/131 | 68 | ❌ no | 2.2 ch/min, 10.4 rec/min |
| qwen3_14b | qwen3-14b | 69% (179/258) | 0/131 | 26 | ✅ YES | 1.5 ch/min, 2.0 rec/min |
| qwen3_5_122b | qwen3.5-122b | 71% (641/906) | 104/131 | 75 | ✅ YES | 1.4 ch/min, 6.9 rec/min |

## Per-model detail

### demo — `qwen3-14b`
- **Grounding pass-rate:** 85.7% (12 grounded / 14 reached judge; 0 flagged; 0 pointing misses of 14 proposals)
- **End-to-end yield:** 85.7% (12 records / 14 proposals)
- **Coverage / recall:** 0/7 chunks drew proposals (0 empty)
- **Cross-context entities (>=2 chunks):** 0
- **Smoking-gun (B. Smith reversal on 89503c71…):** ✅ captured + grounded — {'record_id': 'd2baa3e9-9096-4e8b-adde-c99a38934870', 'signals': {'actor_smith': True, 'reversal_direction': 'back to', 'condition_swap': True}}
- **Throughput:** 1.5 chunks/min, 2.6 records/min (7 chunks in 277s; 0 missing, 0 extract errors)

### gemma_4_31b — `gemma-4-31b`
- **Grounding pass-rate:** 100.0% (22 grounded / 22 reached judge; 0 flagged; 0 pointing misses of 22 proposals)
- **End-to-end yield:** 100.0% (22 records / 22 proposals)
- **Coverage / recall:** 22/131 chunks drew proposals (109 empty)
- **Cross-context entities (>=2 chunks):** 3
- **Smoking-gun (B. Smith reversal on 89503c71…):** ❌ missed — {'record_id': None, 'signals': {}}
- **Throughput:** 0.6 chunks/min, 0.1 records/min (131 chunks in 13887s; 0 missing, 105 extract errors)

### llama_3_3_70b — `llama-3.3-70b`
- **Grounding pass-rate:** 68.9% (257 grounded / 373 reached judge; 2 flagged; 23 pointing misses of 396 proposals)
- **End-to-end yield:** 65.4% (259 records / 396 proposals)
- **Coverage / recall:** 77/131 chunks drew proposals (54 empty)
- **Cross-context entities (>=2 chunks):** 37
- **Smoking-gun (B. Smith reversal on 89503c71…):** ❌ missed — {'record_id': None, 'signals': {}}
- **Throughput:** 0.7 chunks/min, 1.4 records/min (131 chunks in 10976s; 0 missing, 46 extract errors)

### llama_4_scout — `llama-4-scout`
- **Grounding pass-rate:** 74.1% (629 grounded / 849 reached judge; 1 flagged; 25 pointing misses of 874 proposals)
- **End-to-end yield:** 72.1% (630 records / 874 proposals)
- **Coverage / recall:** 115/131 chunks drew proposals (16 empty)
- **Cross-context entities (>=2 chunks):** 68
- **Smoking-gun (B. Smith reversal on 89503c71…):** ❌ missed — {'record_id': None, 'signals': {}}
- **Throughput:** 2.2 chunks/min, 10.4 records/min (131 chunks in 3637s; 0 missing, 0 extract errors)

### qwen3_14b — `qwen3-14b`
- **Grounding pass-rate:** 69.4% (179 grounded / 258 reached judge; 1 flagged; 13 pointing misses of 271 proposals)
- **End-to-end yield:** 66.4% (180 records / 271 proposals)
- **Coverage / recall:** 0/131 chunks drew proposals (0 empty)
- **Cross-context entities (>=2 chunks):** 26
- **Smoking-gun (B. Smith reversal on 89503c71…):** ✅ captured + grounded — {'record_id': '576c2c6b-7c02-45bc-a3f4-068d3973eb04', 'signals': {'actor_smith': True, 'reversal_direction': 'back to', 'condition_swap': True}}
- **Throughput:** 1.5 chunks/min, 2.0 records/min (131 chunks in 5271s; 0 missing, 0 extract errors)

### qwen3_5_122b — `qwen3.5-122b`
- **Grounding pass-rate:** 70.8% (641 grounded / 906 reached judge; 1 flagged; 21 pointing misses of 927 proposals)
- **End-to-end yield:** 69.3% (642 records / 927 proposals)
- **Coverage / recall:** 104/131 chunks drew proposals (27 empty)
- **Cross-context entities (>=2 chunks):** 75
- **Smoking-gun (B. Smith reversal on 89503c71…):** ✅ captured + grounded — {'record_id': '9291e5a6-6ec1-4965-88b0-269a24a5096e', 'signals': {'actor_smith': True, 'reversal_direction': 'back to', 'condition_swap': True}}
- **Throughput:** 1.4 chunks/min, 6.9 records/min (131 chunks in 5617s; 0 missing, 0 extract errors)

