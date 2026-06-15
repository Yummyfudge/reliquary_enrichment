from __future__ import annotations

"""The shared grounding-core — pipeline steps 1-6, factored (Decision D).

What: the reusable mechanics both write_enrichment and link_events compose —
  1. resolve a Fragment (handle / current / cross-checked id),
  2. load it, 3. bounds-check, 4. code-slice the Evidence Span,
  5. run the tier-aware grounding judge, 6. gate on the verdict,
  + freeze the immutable Provenance Validation attestation (hashes of exact bytes).
Why: one heart, tested once, guarantees the invariant identically at every write
boundary. The model POINTS; code COPIES; the judge CHECKS; the row ATTESTS.

The core depends only on protocols (FragmentReader, GroundingJudge) + the in-process
HandleMap — never on a concrete DB — so it is fully unit-testable with a fake judge
(D2). Prompt construction lives here because the prompts are contract-specified
(write_enrichment §8, codex §5) and shared.
"""

import hashlib
from datetime import UTC, datetime

from reliquary_enrichment.grounding.fragments import Fragment, FragmentReader
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import GroundingJudge
from reliquary_enrichment.grounding.types import (
    GateOutcome,
    GroundingError,
    JudgeResult,
    ReasonCode,
    Tier,
    Verdict,
)


def sha256_text(text: str) -> str:
    """SHA-256 hex of the UTF-8 bytes — freezes the exact bytes a record was grounded on."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Judge prompts (contract-specified; tier-aware) ----------------------------------

_RECORD_SYSTEM = (
    "You are a strict grounding judge. You are given an EVIDENCE SPAN copied verbatim "
    "from a source document by code (never paraphrased), and a CLAIM asserted about it. "
    "Decide whether the span supports the claim. Reply with ONLY a JSON object: "
    '{"verdict": "grounded|partial|ungrounded", "failing_values": [..], "reason": ".."}. '
    "Do not transcribe or alter the span. Judge only what the span literally contains."
)

_LINK_SYSTEM = (
    "You are a strict grounding judge for a RELATION between two records. You are given "
    "two EVIDENCE SPANS copied verbatim by code from two source documents, and a proposed "
    "RELATION between record A and record B. Decide whether the cited evidence supports the "
    "relation. Reply with ONLY a JSON object: "
    '{"verdict": "grounded|partial|ungrounded", "failing_values": [..], "reason": ".."}.'
)


def build_record_judge_messages(tier: Tier, claim: str, span: str) -> tuple[str, str]:
    """Messages for grounding a record's claim against its span (write_enrichment §8)."""
    if tier is Tier.FACT:
        task = (
            "TIER=fact. Is EVERY asserted value (actor, date, each field) LITERALLY "
            "supported by this span? Answer grounded only if all hold; name any value that "
            "fails in failing_values. Catch value drift (e.g. reversal->reversible, "
            "03-30->03-29)."
        )
    else:
        task = (
            "TIER=interpretation. Is the claim a REASONABLE inference from this span? It need "
            "not be literal, but it must NOT contradict the span. Mark ungrounded only if it "
            "contradicts or has no basis."
        )
    user = f"{task}\n\nEVIDENCE SPAN:\n{span}\n\nCLAIM:\n{claim}"
    return _RECORD_SYSTEM, user


def build_link_judge_messages(
    tier: Tier, relation: str, span_a: str, span_b: str, rationale: str
) -> tuple[str, str]:
    """Messages for grounding a relation across two records (codex §5 step 4)."""
    if tier is Tier.FACT:
        task = (
            f"TIER=fact. Does the cited evidence EXPLICITLY state that record A '{relation}' "
            "record B? Answer grounded only if explicit."
        )
    else:
        task = (
            f"TIER=interpretation. Is '{relation}' a reasonable inference from A, B, and this "
            "evidence, without contradicting it?"
        )
    user = (
        f"{task}\n\nRELATION: A {relation} B\n\n"
        f"EVIDENCE SPAN A:\n{span_a}\n\nEVIDENCE SPAN B:\n{span_b}\n\n"
        f"RATIONALE:\n{rationale}"
    )
    return _LINK_SYSTEM, user


class GroundingCore:
    """The factored pipeline mechanics (steps 1-6 + attestation). Injected dependencies."""

    def __init__(
        self,
        *,
        fragment_reader: FragmentReader,
        handle_map: HandleMap,
        judge: GroundingJudge,
    ) -> None:
        self._fragments = fragment_reader
        self._handles = handle_map
        self._judge = judge

    # --- Steps 1-2: resolve + load -------------------------------------------------
    def resolve_fragment(
        self,
        workstream_id: str,
        *,
        chunk_handle: str | None = None,
        chunk_id: str | None = None,
    ) -> Fragment:
        """Resolve a reference to a loaded Fragment (steps 1-2).

        Reference modes (Decision A):
          * ``chunk_handle`` given -> resolve via the handle map (source of truth).
          * neither given -> per-Fragment mode -> the workstream's current Fragment.
          * ``chunk_id`` given alone -> raw-id mode (allowed; the judge still checks).
        ``chunk_id`` given ALONGSIDE a handle/current is a redundant cross-check: if it
        disagrees with the resolved id it signals corruption -> REJECT unknown_fragment.
        The model never supplies the source-of-truth id; a 1-2 char handle is far harder
        to corrupt than a UUID, and a corrupted handle lands on a different real Fragment
        whose text won't support the claim (caught at the judge).
        """
        resolved: str | None
        if chunk_handle is not None:
            resolved = self._handles.resolve(workstream_id, chunk_handle)
            if resolved is None:
                raise GroundingError(
                    ReasonCode.UNKNOWN_FRAGMENT,
                    f"chunk_handle {chunk_handle!r} is not known in this workstream; "
                    "re-read the Fragment to get a fresh handle (do not retype the id).",
                )
        elif chunk_id is not None:
            resolved = chunk_id  # raw-id mode (no handle/current) — judge still verifies
        else:
            resolved = self._handles.current(workstream_id)
            if resolved is None:
                raise GroundingError(
                    ReasonCode.UNKNOWN_FRAGMENT,
                    "no chunk_handle and no current Fragment set for this workstream.",
                )

        # Redundant cross-check: an echoed chunk_id that disagrees signals corruption.
        if chunk_id is not None and chunk_handle is not None and chunk_id != resolved:
            raise GroundingError(
                ReasonCode.UNKNOWN_FRAGMENT,
                f"echoed chunk_id {chunk_id!r} disagrees with handle {chunk_handle!r} "
                f"-> {resolved!r}; cross-check failed (possible corruption).",
            )

        fragment = self._fragments.get(resolved)
        if fragment is None:
            raise GroundingError(
                ReasonCode.FRAGMENT_NOT_FOUND,
                f"no Fragment in claim_chunks for chunk_id {resolved!r}.",
            )
        return fragment

    # --- Steps 3-4: bounds-check + code-slice --------------------------------------
    def slice_span(self, fragment: Fragment, char_start: int, char_end: int) -> str:
        """Bounds-check then code-slice the Evidence Span from the Fragment text (steps 3-4).

        The span is ``fragment.text[char_start:char_end]`` — byte-exact from the corpus.
        Any model-supplied span text is irrelevant: this is the only source of the stored
        quote. Empty/whitespace-only -> REJECT empty_span.
        """
        text = fragment.text
        if not (0 <= char_start < char_end <= len(text)):
            raise GroundingError(
                ReasonCode.BAD_OFFSETS,
                f"need 0 <= char_start < char_end <= len(text)={len(text)}; "
                f"got char_start={char_start}, char_end={char_end}.",
            )
        span = text[char_start:char_end]
        if not span.strip():
            raise GroundingError(
                ReasonCode.EMPTY_SPAN, "the code-sliced span is empty or whitespace-only."
            )
        return span

    # --- Step 5: judge -------------------------------------------------------------
    def judge_record(self, tier: Tier, claim: str, span: str) -> JudgeResult:
        """Run the tier-aware judge for a record claim over its code-sliced span."""
        system, user = build_record_judge_messages(tier, claim, span)
        return self._judge.evaluate(system, user)

    def judge_link(
        self, tier: Tier, relation: str, span_a: str, span_b: str, rationale: str
    ) -> JudgeResult:
        """Run the tier-aware judge for a relation over both code-sliced spans."""
        system, user = build_link_judge_messages(tier, relation, span_a, span_b, rationale)
        return self._judge.evaluate(system, user)

    # --- Step 6: tier gate ---------------------------------------------------------
    @staticmethod
    def gate(
        tier: Tier,
        result: JudgeResult,
        *,
        fact_reason: ReasonCode,
        interp_reason: ReasonCode,
    ) -> GateOutcome:
        """Apply the strict-core / soft-rest tier gate (write_enrichment §5.6, codex §5.5).

        Reading of the contract's step 6 (recorded in findings as a clarification):
          * grounded                         -> accept.
          * partial, tier=fact               -> REJECT (strict core: every value must hold).
          * partial, tier=interpretation     -> accept + flagged (soft rest, SCOPE §6).
          * ungrounded                       -> REJECT (fact_reason / interp_reason).
        A rejection raises GroundingError; it never returns a GateOutcome.
        """
        verdict = result.verdict
        if verdict is Verdict.GROUNDED:
            return GateOutcome(flagged=False)
        failing = (
            f" failing_values={result.failing_values}" if result.failing_values else ""
        )
        if verdict is Verdict.PARTIAL:
            if tier is Tier.FACT:
                raise GroundingError(
                    fact_reason,
                    f"judge=partial; a fact requires every asserted value grounded.{failing} "
                    f"{result.reason}".strip(),
                )
            return GateOutcome(flagged=True)
        # ungrounded
        reason_code = fact_reason if tier is Tier.FACT else interp_reason
        raise GroundingError(
            reason_code, f"judge=ungrounded.{failing} {result.reason}".strip()
        )

    # --- Provenance Validation attestation (step 8) --------------------------------
    def build_attestation(
        self, result: JudgeResult, *, hashes: dict[str, str]
    ) -> dict:
        """Freeze the immutable Provenance Validation (verdict + judge id + hashes + time).

        ``hashes`` carries the SHA-256s of the exact bytes grounded against — the
        Evidence Span(s) and source Fragment text(s) — so the record is self-verifying and
        tamper-evident on audit. The caller supplies the hash set (records hash 1 span +
        source; links hash 2 spans + 2 sources).
        """
        attestation = {
            "verdict": str(result.verdict),
            "judge_model": self._judge.model_id,
            "judge_version": self._judge.version,
            "validated_at": datetime.now(UTC).isoformat(),
        }
        if result.failing_values:
            attestation["failing_values"] = result.failing_values
        attestation.update(hashes)
        return attestation
