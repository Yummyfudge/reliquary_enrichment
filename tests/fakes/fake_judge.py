from __future__ import annotations

"""Scriptable fake GroundingJudge for unit tests (Decision D2).

Three flavors:
  * ConstantJudge   — always returns the same verdict.
  * ScriptedJudge   — returns a queued sequence of JudgeResults (one per evaluate()).
  * RuleJudge       — derives the verdict from a callable inspecting (system, user).
All record the prompts they saw, so tests can assert the core built the right prompt and
slice (proving "the judge sees the code-sliced span, never the model's prose").
"""

from collections.abc import Callable

from reliquary_enrichment.grounding.judge import GroundingJudge
from reliquary_enrichment.grounding.types import JudgeResult, Verdict


class _RecordingJudge(GroundingJudge):
    def __init__(self, model_id: str = "judge", version: str = "fake-1") -> None:
        self._model_id = model_id
        self._version = version
        self.calls: list[tuple[str, str]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def version(self) -> str:
        return self._version


class ConstantJudge(_RecordingJudge):
    def __init__(
        self,
        verdict: Verdict = Verdict.GROUNDED,
        *,
        failing_values: list[str] | None = None,
        reason: str = "",
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._result = JudgeResult(
            verdict=verdict, failing_values=failing_values or [], reason=reason
        )

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResult:
        self.calls.append((system_prompt, user_prompt))
        return self._result


class ScriptedJudge(_RecordingJudge):
    def __init__(self, results: list[JudgeResult], **kw) -> None:
        super().__init__(**kw)
        self._results = list(results)

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResult:
        self.calls.append((system_prompt, user_prompt))
        if not self._results:
            raise AssertionError("ScriptedJudge ran out of scripted results")
        return self._results.pop(0)


class RuleJudge(_RecordingJudge):
    def __init__(self, rule: Callable[[str, str], JudgeResult], **kw) -> None:
        super().__init__(**kw)
        self._rule = rule

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResult:
        self.calls.append((system_prompt, user_prompt))
        return self._rule(system_prompt, user_prompt)
