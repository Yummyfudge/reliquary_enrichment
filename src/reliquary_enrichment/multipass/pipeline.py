from __future__ import annotations

"""Pipeline — runs passes in order over the whole input, captures glass-box state, heartbeats.

Owns the cross-pass status line (design §"Status heartbeat", Joe's ask): every ~5 min, to both
the emit sink (progress.log/stdout) and overall-progress-aware:

    Test running | <model> | Pass p/N | Chunk c/total | <tok/s> tok/s | <pct>% total

where ``pct`` spans ALL passes — (done_passes*total + c) / (N*total) — so a long pass reads as
real progress, not a stall. Time-based (~5 min), so a stall still shows. Each pass's state is
persisted (glass box) the moment it completes — never lost mid-run.
"""

import json
import os
import time
from pathlib import Path

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult

STATUS_INTERVAL_S: float = float(os.getenv("MULTIPASS_STATUS_INTERVAL_S", "300"))  # ~5 min


class Pipeline:
    def __init__(
        self,
        *,
        passes: list[Pass],
        chunks: list[ChunkRef],
        ctx: PassContext,
        out_dir: str | Path | None = None,
        emit=print,
        clock=time.monotonic,
        status_interval_s: float = STATUS_INTERVAL_S,
    ) -> None:
        self._passes = passes
        self._chunks = chunks
        self._ctx = ctx
        self._out = Path(out_dir) if out_dir else None
        self._emit = emit
        self._clock = clock
        self._interval = status_interval_s

    def run(self) -> dict[str, PassResult]:
        results: dict[str, PassResult] = {}
        total = len(self._chunks)
        n = len(self._passes)
        started = self._clock()
        status_last = started
        win = {"t0": started, "tok": 0}
        if self._out:
            self._out.mkdir(parents=True, exist_ok=True)
            # capture the INPUTS too (original text per chunk) so the review is offline-readable
            (self._out / "inputs.json").write_text(json.dumps(
                {c.chunk_id: {"text": c.text, "source": c.source} for c in self._chunks},
                indent=2))

        errors = 0
        for p_idx, p in enumerate(self._passes):
            if p.per_chunk:
                outputs: dict = {}
                for c_idx, chunk in enumerate(self._chunks, 1):
                    try:
                        out, toks = p.process_chunk(chunk, results, self._ctx)
                    except Exception as exc:   # CONTAIN: one bad chunk must not kill the run
                        out, toks = {"error": f"{type(exc).__name__}: {exc}"}, 0
                        errors += 1
                        self._emit(f"[skip] {p.name} chunk {chunk.chunk_id[:8]} — {type(exc).__name__}")
                    outputs[chunk.chunk_id] = out
                    win["tok"] += toks or 0
                    now = self._clock()
                    if now - status_last >= self._interval:
                        self._emit(self._heartbeat(p_idx, n, c_idx, total, now, win))
                        status_last = now
                        win = {"t0": now, "tok": 0}
                results[p.name] = PassResult(p.name, outputs)
            else:
                try:
                    state = p.process_all(self._chunks, results, self._ctx)
                except Exception as exc:       # CONTAIN: a consolidation error degrades, not crashes
                    state = {"error": f"{type(exc).__name__}: {exc}"}
                    errors += 1
                    self._emit(f"[skip] consolidate {p.name} — {type(exc).__name__}")
                results[p.name] = PassResult(p.name, state)
                pct = 100.0 * (p_idx + 1) / n if n else 0.0
                self._emit(
                    f"Test running | {self._ctx.model_name} | Pass {p_idx + 1}/{n} "
                    f"(consolidate {p.name}) | {pct:.0f}% total"
                )
            self._persist(results[p.name])
        self._emit(f"Test run COMPLETE | {self._ctx.model_name} | {total} chunks x {n} passes "
                   f"| {errors} skipped")
        return results

    def _heartbeat(self, p_idx: int, n: int, c: int, total: int, now: float, win: dict) -> str:
        done = p_idx * total + c                      # chunks done across ALL passes
        denom = n * total
        pct = 100.0 * done / denom if denom else 0.0
        win_secs = max(1e-9, now - win["t0"])
        toks = win["tok"] / win_secs
        return (f"Test running | {self._ctx.model_name} | Pass {p_idx + 1}/{n} | "
                f"Chunk {c}/{total} | {toks:.1f} tok/s | {pct:.0f}% total")

    def _persist(self, result: PassResult) -> None:
        if not self._out:
            return
        (self._out / f"{result.pass_name}.json").write_text(
            json.dumps({"pass": result.pass_name, "outputs": result.outputs,
                        "meta": result.meta}, indent=2, default=str)
        )
