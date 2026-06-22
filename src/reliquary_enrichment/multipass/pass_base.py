from __future__ import annotations

"""Pass framework — the tested boundary every pass implements + the model client.

A Pass turns inputs (the corpus chunks + prior passes' state) into this pass's state. Per-chunk
passes implement ``process_chunk``; whole-state passes (the .9 consolidations) implement
``process_all``. The Pipeline drives the loop, captures glass-box state, and emits the heartbeat.

ModelClient is the generic candidate LLM call carrying the audition-2 hardening forward
(big max_tokens, long deadline, thinking-off via extra_body). It is injected, so passes are
unit-testable with a fake — no lane needed to build.
"""

import os
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Protocol

from reliquary_enrichment.grounding.judge import LITELLM_BASE_URL
from reliquary_enrichment.llm_http import post_json

# Audition-2 §2 defaults carried forward (env-overridable per candidate).
# DEADLINE AUDIT (10b): every model-call path is bounded by post_json's hard total_deadline + read_timeout
# (llm_http.py) — the proposers (fill/link/meaning) all route through ModelClient.complete below, and the
# grounding judge through LiteLLMGroundingJudge._call (its own 90s/60s bound). read_timeout is the hard
# per-request SILENT-server catch (raises if no response byte for N s); total_deadline backstops slow-drip.
# Backstop lowered 600 -> 300 so a sick backend fails ~2x faster while still clearing a full 4096-tok
# generation (~100s at observed throughput). The read_timeout (min(deadline,120)) is unchanged — it must
# exceed non-streaming generation time, so it is NOT lowered (that would false-timeout big extractions).
MODEL_MAX_TOKENS: int = int(os.getenv("MULTIPASS_MAX_TOKENS", "4096"))
MODEL_DEADLINE_S: float = float(os.getenv("MULTIPASS_DEADLINE_S", "300"))


@dataclass(frozen=True, slots=True)
class ChunkRef:
    """One input unit — a chunk from the frozen slice or (later) a PDF."""

    chunk_id: str
    text: str
    source: str = "slice"   # "slice" | "pdf:<name>"


@dataclass(slots=True)
class PassResult:
    """A pass's captured state (glass box).

    For per-chunk passes, ``outputs`` maps chunk_id -> the pass's output for that chunk.
    Whole-state passes (.9) may store arbitrary structure (e.g. 2.9's raw/final/mapping).
    """

    pass_name: str
    outputs: dict
    meta: dict = field(default_factory=dict)


class Completer(Protocol):
    """What a Pass needs from the candidate model: prompt -> (content, completion_tokens)."""

    def complete(self, system: str, user: str) -> tuple[str, int]:
        ...


class ModelClient:
    """The candidate LLM call via LiteLLM, with the audition-2 hardening (Completer impl)."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = LITELLM_BASE_URL,
        max_tokens: int = MODEL_MAX_TOKENS,
        deadline_s: float = MODEL_DEADLINE_S,
        extra_body: dict | None = None,
    ) -> None:
        self._model = model
        self._endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._max_tokens = max_tokens
        self._deadline_s = deadline_s
        self._extra_body = extra_body or {}

    def complete(self, system: str, user: str) -> tuple[str, int]:
        body = post_json(
            self._endpoint,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": self._max_tokens,
                **self._extra_body,   # thinking-off etc. (handoff §2)
            },
            read_timeout=min(self._deadline_s, 120.0),
            total_deadline=self._deadline_s,
        )
        content = body["choices"][0]["message"]["content"]
        tokens = (body.get("usage") or {}).get("completion_tokens") or 0
        return content, tokens


@dataclass
class PassContext:
    """Shared services handed to every pass (model + model label + slots for judge/stores)."""

    model: Completer
    model_name: str
    extras: dict = field(default_factory=dict)   # judge, write_service, etc. as passes need them


class Pass(ABC):
    """A tested boundary. ``per_chunk`` passes implement process_chunk; .9 passes process_all."""

    name: str = "pass"
    per_chunk: bool = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        """Return (output_for_this_chunk, completion_tokens). Override in per-chunk passes."""
        raise NotImplementedError

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> dict:
        """Return the whole-pass state. Override in .9 consolidation passes."""
        raise NotImplementedError
