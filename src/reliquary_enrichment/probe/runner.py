from __future__ import annotations

"""ProbeRunner — drive the candidate over the locked slice through the real write_enrichment.

For each chunk: get_chunk (mints a handle, read-only over the corpus) → candidate extracts
proposals → locate each verbatim quote → call write_enrichment (judge gates, writes into the
probe_<label> schema). Captures every attempt + timing for scoring. A failure on one chunk is
contained (logged, run continues) — only the loop level skips a whole candidate.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reliquary_enrichment.probe.extraction import locate_quote

# §3 (audition-2 handoff): push a rolling status line on this cadence (default 15 min).
STATUS_INTERVAL_S: float = float(os.getenv("PROBE_STATUS_INTERVAL_S", "900"))


@dataclass(slots=True)
class Attempt:
    """One proposal's journey through grounding (the unit scoring counts)."""

    chunk_id: str
    record_type: str
    tier: str
    located: bool
    ok: bool
    reason_code: str | None = None
    record_id: str | None = None
    elapsed_s: float = 0.0


@dataclass(slots=True)
class RunLog:
    """Everything a run produced (besides the rows in the probe schema)."""

    label: str
    candidate_model: str
    schema: str
    chunk_ids: list[str]
    attempts: list[Attempt] = field(default_factory=list)
    chunks_seen: int = 0
    chunks_missing: int = 0
    extract_errors: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def wall_seconds(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    @property
    def records_written(self) -> int:
        return sum(1 for a in self.attempts if a.ok)

    def persist(self, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "attempts.jsonl").open("w") as fh:
            for a in self.attempts:
                fh.write(json.dumps(asdict(a)) + "\n")
        meta = {k: getattr(self, k) for k in (
            "label", "candidate_model", "schema", "chunks_seen", "chunks_missing",
            "extract_errors", "started_at", "finished_at",
        )}
        meta["n_chunks"] = len(self.chunk_ids)
        meta["records_written"] = self.records_written
        meta["wall_seconds"] = self.wall_seconds
        (out / "run_meta.json").write_text(json.dumps(meta, indent=2))
        return out


class ProbeRunner:
    def __init__(
        self,
        *,
        extractor,
        write_service,
        read_service,
        label: str,
        candidate_model: str,
        schema: str,
        workstream_id: str | None = None,
        clock=time.monotonic,
        progress=None,
    ) -> None:
        self._extractor = extractor
        self._write = write_service
        self._read = read_service
        self._label = label
        self._candidate_model = candidate_model
        self._schema = schema
        self._ws = workstream_id or f"probe-{label}"
        self._clock = clock
        self._progress = progress  # Callable[[str], None] | None — heartbeat sink

    def _emit(self, line: str) -> None:
        if self._progress:
            self._progress(line)

    def _line(self, i: int, total: int, cid: str, start: float, detail: str) -> str:
        elapsed = self._clock() - start
        eta = (elapsed / i) * (total - i) if i else 0.0
        return (f"{time.strftime('%H:%M:%S')} [{i}/{total}] {cid[:8]} | {detail} | "
                f"elapsed {elapsed/60:.0f}m eta ~{eta/60:.0f}m")

    def _status_line(self, i: int, total: int, now: float, start: float, win: dict) -> str:
        """The §3 ~15-min heartbeat: % done / rolling chunk accept-rate / current tok/s."""
        pct = 100.0 * i / total if total else 0.0
        win_secs = max(1e-9, now - win["t0"])
        toks = win["tok"] / win_secs
        accept = (win["grounded"] / win["located"]) if win["located"] else 0.0
        elapsed = (now - start) / 60.0
        eta = (now - start) / i * (total - i) / 60.0 if i else 0.0
        return (f"{time.strftime('%H:%M:%S')} STATUS {pct:.0f}% ({i}/{total}) | "
                f"accept {accept:.0%} ({win['grounded']}/{win['located']} located, rolling) | "
                f"{toks:.0f} tok/s | elapsed {elapsed:.0f}m eta ~{eta:.0f}m")

    def run(self, chunk_ids: list[str]) -> RunLog:
        log = RunLog(
            label=self._label, candidate_model=self._candidate_model,
            schema=self._schema, chunk_ids=list(chunk_ids), started_at=self._clock(),
        )
        total = len(chunk_ids)
        self._emit(f"START {total} chunks | model={self._candidate_model} schema={self._schema}")
        # Rolling window for the §3 status heartbeat (reset each interval).
        status_last = log.started_at
        win = {"t0": log.started_at, "tok": 0, "located": 0, "grounded": 0}
        for i, cid in enumerate(chunk_ids, 1):
            got = self._read.get_chunk(cid, workstream_id=self._ws)
            if not got.get("ok"):
                log.chunks_missing += 1
                self._emit(self._line(i, total, cid, log.started_at, "MISSING fragment"))
                continue
            log.chunks_seen += 1
            handle, text = got["chunk_handle"], got["text"]
            try:
                proposals = self._extractor.extract(text)
            except Exception as exc:  # timeout/HTTP on one chunk -> log + SKIP, never kill
                log.extract_errors += 1
                self._emit(self._line(i, total, cid, log.started_at,
                                      f"EXTRACT FAIL ({type(exc).__name__}) — skipped"))
                continue
            before = len(log.attempts)
            t0 = self._clock()
            for p in proposals:
                log.attempts.append(self._attempt(cid, handle, text, p))
            chunk = log.attempts[before:]
            g = sum(1 for a in chunk if a.ok)
            located = sum(1 for a in chunk if a.located)
            miss = len(chunk) - located
            self._emit(self._line(
                i, total, cid, log.started_at,
                f"{len(proposals)} props | {g} grounded {len(chunk)-g-miss} bounced {miss} miss "
                f"| {self._clock()-t0:.0f}s | total {log.records_written} recs"))
            # accumulate the rolling window + emit a STATUS line every ~15 min
            win["tok"] += getattr(self._extractor, "last_completion_tokens", None) or 0
            win["located"] += located
            win["grounded"] += g
            now = self._clock()
            if now - status_last >= STATUS_INTERVAL_S:
                self._emit(self._status_line(i, total, now, log.started_at, win))
                status_last = now
                win = {"t0": now, "tok": 0, "located": 0, "grounded": 0}
        log.finished_at = self._clock()
        self._emit(f"DONE {log.chunks_seen} chunks seen, {log.records_written} records, "
                   f"{log.extract_errors} extract-fails, {log.wall_seconds/60:.0f}m")
        return log

    def _attempt(self, chunk_id, handle, text, p) -> Attempt:
        t0 = self._clock()
        loc = locate_quote(text, p.quote)
        if loc is None:
            return Attempt(chunk_id, p.record_type, p.tier, located=False, ok=False,
                           reason_code="locate_miss", elapsed_s=self._clock() - t0)
        char_start, char_end = loc
        out = self._write.write({
            "chunk_handle": handle,
            "char_start": char_start, "char_end": char_end,
            "record_type": p.record_type, "tier": p.tier, "fields": p.fields,
            "actor": p.actor, "event_date": p.event_date,
            "claim_relevance": p.claim_relevance, "confidence": p.confidence,
        }, workstream_id=self._ws)
        return Attempt(
            chunk_id, p.record_type, p.tier, located=True, ok=bool(out.get("ok")),
            reason_code=out.get("reason_code"), record_id=out.get("record_id"),
            elapsed_s=self._clock() - t0,
        )
