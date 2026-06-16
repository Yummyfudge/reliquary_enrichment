from __future__ import annotations

"""The grounding judge — the heart's transport (Decision D2).

What: the GroundingJudge protocol (what the core depends on) + LiteLLMGroundingJudge,
the real implementation that calls the LiteLLM ``judge`` alias (Qwen2.5-14B-Q6).
Why: the judge is the only component that decides whether a code-sliced span supports a
claim. It is injected so the core is unit-testable against a fake (the live ``judge``
alias is registered by the Architect before acceptance — D2).

Decision B (judge structured-output → engineer's call): JSON mode + temperature 0 +
DEFENSIVE parse + one retry. The non-negotiable rule is **fail CLOSED**: any
unparseable / invalid judge output raises (never silently returns "grounded"). A judge
we can't read must never let an ungrounded token through.
"""

import json
import os
import re
from typing import Protocol

import requests

from reliquary_enrichment.grounding.types import (
    GroundingError,
    JudgeResult,
    ReasonCode,
    Verdict,
)
from reliquary_enrichment.llm_http import LLMTimeout, post_json


class GroundingJudge(Protocol):
    """Verifies a claim against a code-sliced span. Injected into the grounding-core."""

    @property
    def model_id(self) -> str:
        """Stable judge identity frozen into Provenance Validation (e.g. ``judge``)."""
        ...

    @property
    def version(self) -> str:
        """Judge version/served-model label frozen into Provenance Validation."""
        ...

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResult:
        """Return the structured Grounding Verdict. Fail CLOSED (raise) on unreadable output."""
        ...


# LiteLLM proxy — same base-url as the agent/embeddings (D2). The ``judge`` alias maps to
# the Qwen2.5-14B-Q6 container.
LITELLM_BASE_URL: str = os.getenv(
    "RELIQUARY_ENRICHMENT_LITELLM_BASE_URL",
    os.getenv("CONTEXT_RELIQUARY_LITELLM_BASE_URL", "http://192.168.1.53:4000"),
)
JUDGE_MODEL_ALIAS: str = os.getenv("RELIQUARY_ENRICHMENT_JUDGE_MODEL", "judge")


def parse_judge_json(content: str) -> JudgeResult:
    """Defensively parse the judge's reply into a JudgeResult, or raise (fail closed).

    Accepts a bare JSON object or one embedded in prose (extracts the first {...}).
    Requires a valid ``verdict``; coerces ``failing_values`` to a list[str]. Raises
    GroundingError(JUDGE_UNAVAILABLE) when the verdict cannot be read — NEVER defaults
    to grounded.
    """
    raw = content or ""
    obj: dict | None = None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict) or "verdict" not in obj:
        raise GroundingError(
            ReasonCode.JUDGE_UNAVAILABLE,
            f"judge returned unparseable output (fail-closed): {raw[:200]!r}",
        )
    try:
        verdict = Verdict(str(obj["verdict"]).strip().lower())
    except ValueError:
        raise GroundingError(
            ReasonCode.JUDGE_UNAVAILABLE,
            f"judge returned unknown verdict {obj.get('verdict')!r} (fail-closed)",
        )
    failing = obj.get("failing_values") or []
    if not isinstance(failing, list):
        failing = [str(failing)]
    failing = [str(v) for v in failing]
    reason = str(obj.get("reason", ""))
    return JudgeResult(verdict=verdict, failing_values=failing, reason=reason, raw=raw)


class LiteLLMGroundingJudge:
    """Real judge: LiteLLM chat-completions against the ``judge`` alias, JSON mode."""

    def __init__(
        self,
        *,
        base_url: str = LITELLM_BASE_URL,
        model: str = JUDGE_MODEL_ALIAS,
        version: str = "qwen2.5-14b-q6",
        timeout: float = 60.0,
        max_tokens: int = 512,
        deadline_s: float = 90.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._version = version
        self._timeout = timeout
        self._max_tokens = max_tokens   # judge output is small JSON; cap it + bound the call
        self._deadline_s = deadline_s
        self._endpoint = f"{self._base_url}/v1/chat/completions"

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def version(self) -> str:
        return self._version

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResult:
        """Call the judge once, retry once on a parse miss, then fail closed."""
        last_error: GroundingError | None = None
        for attempt in range(2):
            content = self._call(system_prompt, user_prompt, attempt)
            try:
                return parse_judge_json(content)
            except GroundingError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _call(self, system_prompt: str, user_prompt: str, attempt: int) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            body = post_json(
                self._endpoint, payload,
                read_timeout=self._timeout, total_deadline=self._deadline_s,
            )
            return body["choices"][0]["message"]["content"]
        except (LLMTimeout, requests.RequestException, KeyError, IndexError, ValueError) as exc:
            # Fail CLOSED: a judge we can't read bounces the record (run continues).
            raise GroundingError(
                ReasonCode.JUDGE_UNAVAILABLE,
                f"judge call failed ({self._endpoint}, attempt {attempt + 1}): {exc}",
            ) from exc
