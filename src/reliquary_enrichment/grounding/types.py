from __future__ import annotations

"""Shared grounding types — enums, the short-circuit error, and value objects.

What: the vocabulary the grounding-core, write_enrichment, and link_events all speak —
Tier, Verdict, ReasonCode, the GroundingError that aborts the pipeline on first failure,
and the JudgeResult the judge returns.
Why: one definition of the controlled vocabularies (== the contracts' terms) so the
ubiquitous language is enforced in code, not re-typed per tool.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Tier(StrEnum):
    """fact (must be literally grounded) | interpretation (inference that cites facts)."""

    FACT = "fact"
    INTERPRETATION = "interpretation"


class Verdict(StrEnum):
    """The grounding judge's ruling over a code-sliced span."""

    GROUNDED = "grounded"
    PARTIAL = "partial"
    UNGROUNDED = "ungrounded"


class ReasonCode(StrEnum):
    """Rejection codes returned to the agent (write_enrichment §6, codex §9).

    The rejection IS the feedback loop: the agent fixes and retries by RE-POINTING,
    never by re-transcribing.
    """

    # write_enrichment
    UNKNOWN_FRAGMENT = "unknown_fragment"
    FRAGMENT_NOT_FOUND = "fragment_not_found"
    BAD_OFFSETS = "bad_offsets"
    EMPTY_SPAN = "empty_span"
    UNGROUNDED_FACT = "ungrounded_fact"
    UNSUPPORTED_INTERPRETATION = "unsupported_interpretation"
    SCHEMA_INVALID = "schema_invalid"
    # link_events
    UNKNOWN_RECORD = "unknown_record"
    UNGROUNDED_RELATION = "ungrounded_relation"
    # judge transport / defensive-parse failure (fail CLOSED, never silently accept)
    JUDGE_UNAVAILABLE = "judge_unavailable"


class GroundingError(Exception):
    """Raised to abort the pipeline on the first failure (short-circuit).

    Carries the agent-readable ``reason_code`` + ``detail`` the tool surfaces as
    ``{ok: false, reason_code, detail}``. ``detail`` must help the agent re-point.
    """

    def __init__(self, reason_code: ReasonCode, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """The grounding judge's structured output over a code-sliced span.

    ``failing_values`` names any asserted value the span does NOT support (e.g.
    ``["event_date"]``) — surfaced to the agent so it re-points rather than re-types.
    ``raw`` keeps the model's literal text for audit/debugging.
    """

    verdict: Verdict
    failing_values: list[str] = field(default_factory=list)
    reason: str = ""
    raw: str = ""


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """Result of the tier gate (write_enrichment §5 step 6 / codex §5 step 5).

    ``flagged`` marks a soft-tier ``partial`` that is accepted-but-flagged for curation.
    A rejection never produces a GateOutcome — it raises GroundingError instead.
    """

    flagged: bool
