from __future__ import annotations

"""MeaningWriter — the gated, GROUNDED, embedded side of the bright line (brief §5.4 #4/#7/#8/#10).

Writes the chunk's small, LOCAL, standalone-FACT meaning — the ONLY embedded artifact — into
enrichment_meaning. SEPARATE from write_enrichment: meaning NEVER routes through enrichment_records. The
pipeline, cheap checks first:
  1. META-PHRASE pre-filter (regex, ahead of the judge): kill the "this chunk indicates / the significance
     to the claim is / this is important because" family — a meta-description, not a local fact.
  2. HARD DISCRIMINATIVENESS gate (REJECT, not flag): the meaning must carry a NON-THEME entity (a
     discriminator). A grounded-but-generic meaning passes grounding clean (the judge only checks
     non-contradiction), so this gate is the ONLY defense against trivia — calibrated at BOTH poles:
     "Cheers, Joe" (no non-theme entity) OUT, the gold local fact ("Manager B. Smith placed the claim
     back under the Mental Health limitation") IN.
  3. GROUNDING at Tier.INTERPRETATION via the shared GroundingCore (point->copy->judge->attest).
  4. HOOK-resolution check (FLAG, not reject): a capitalized multi-token span or date-like token in the
     meaning that resolves to NONE of the chunk's grounded-entity surfaces surfaces a codex gap.
"""

import re

from reliquary_enrichment.grounding.core import GroundingCore, sha256_text
from reliquary_enrichment.grounding.types import GroundingError, ReasonCode, Tier

# Meta-description family — ANCHORED to a meta SUBJECT (this chunk/record, the significance, what this
# means). NOT a bare verb: "Dr. Smith shows that the MRI is normal" is a legit local fact, not meta.
_META = re.compile(
    r"\bthis (?:chunk|record|note|document|fact|entry|span|file)\b"
    r"|\bthis (?:indicates|shows|reflects|documents|demonstrates|represents|reveals|suggests|means)\b"
    r"|\bthe (?:note|record|chunk|document|entry) (?:indicates|shows|reflects|documents|demonstrates)\b"
    r"|\bthe significance (?:to|of|for|in)\b"
    r"|\bwhat this (?:means|indicates|shows|reflects|documents)\b"
    r"|\bthis (?:is|matters)\b[^.]*\bbecause\b",
    re.I,
)
_CAP_SPAN = re.compile(r"\b[A-Z][\w.]*(?:\s+[A-Z][\w.]*)+\b")           # >= 2 capitalized tokens
_DATE_TOK = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_TOK = re.compile(r"[a-z0-9]+")

# Common words that, even when they appear in an entity surface, are NOT distinctive enough to be a
# discriminative hook (so 'Smith' matches surname-only paraphrases, but 'may'/'back'/'claim' don't carry
# substance by themselves, and 'Smith' does NOT match the substring inside 'Blacksmith' — token, not infix).
_COMMON = frozenset(
    "a an the and or but of to in on at for with by from into under over off out up down this that these "
    "those is are was were be been being am has have had do does did will would shall should may might must "
    "can could it its it's he she his her him they them their we us our you your i me my as not no nor yes "
    "if then so than too very also just only more most some such any each all both either neither here "
    "there now when where what which who whom whose how why because about after before between during "
    "claim note date name type status review reviewed update updated sent send file form letter case body "
    "back place placed put set new old see prior attached please thanks regards best team correspondence "
    "request decision owner contact size view download last modified created action user".split()
)


def render_meaning_claim(meaning: str) -> str:
    """The local fact the judge verifies (non-contradicted) against the code-sliced span."""
    return meaning.strip()


def _name_tokens(s: str) -> set[str]:
    """Distinctive (>=3-char, non-common) word tokens of a surface/span — a name signal, not infixes."""
    return {t for t in _TOK.findall((s or "").lower()) if len(t) >= 3 and t not in _COMMON}


def is_meta_phrase(meaning: str) -> bool:
    """True if the meaning is a meta-description (forbidden family), not a local fact."""
    return bool(_META.search(meaning or ""))


def has_discriminative_substance(meaning: str, resolved_entities: list[dict]) -> bool:
    """True iff the meaning carries discriminative substance (brief §5.4 #7): a concrete dated action tied
    to a NON-THEME date entity, OR a DISTINCTIVE word token shared with a NON-THEME entity surface (word-
    level, so a surname-only / no-space / titled paraphrase of B. Smith still resolves, while 'Smith' inside
    'Blacksmith' does NOT). A theme-only meaning — or one whose only date is a THEME date / a date the codex
    doesn't carry — names no discriminator and is rejected (the date check is gated on a non-theme date
    entity, never an unconditional pass)."""
    has_date = bool(_DATE_TOK.search(meaning or ""))
    mtok = set(_TOK.findall((meaning or "").lower()))
    for ent in resolved_entities:
        if ent.get("is_theme"):
            continue
        if has_date and ent.get("entity_type") == "date":              # concrete dated action (non-theme)
            return True
        for surface in (ent.get("canonical"), *ent.get("aliases", ())):
            if _name_tokens(surface) & mtok:
                return True
    return False


def hook_unresolved(meaning: str, resolved_surfaces: set[str]) -> bool:
    """FLAG (not reject): True if a NAME-LIKE capitalized span or date-like token in the meaning shares no
    distinctive token with any resolved-entity surface — a noun the codex doesn't carry. Spans that are
    only common words (e.g. an 'An Extension Request' document phrase) are not name-like and don't flag."""
    surface_tokens: set[str] = set()
    for s in resolved_surfaces:
        surface_tokens |= _name_tokens(s)
    for token in _CAP_SPAN.findall(meaning or "") + _DATE_TOK.findall(meaning or ""):
        ntoks = _name_tokens(token) or set(_TOK.findall(token.lower())) & {token.lower()}  # dates: keep
        if _DATE_TOK.fullmatch(token):
            ntoks = {token.lower()}
        if not ntoks:
            continue                                                    # not name-like -> don't flag
        if not (ntoks & surface_tokens) and not any(
                t in s for t in ntoks for s in surface_tokens):
            return True
    return False


class MeaningWriter:
    """Composes the shared GroundingCore + the meaning store. NEVER touches enrichment_records."""

    def __init__(self, *, core: GroundingCore, meaning_store) -> None:
        self._core = core
        self._store = meaning_store

    def write(
        self, *, chunk_id: str, meaning: str, char_start: int, char_end: int,
        resolved_entities: list[dict], workstream_id: str = "mp-meaning",
    ) -> dict:
        meaning = (meaning or "").strip()
        if is_meta_phrase(meaning):
            return {"ok": False, "reason_code": "meta_phrase"}
        if not has_discriminative_substance(meaning, resolved_entities):
            return {"ok": False, "reason_code": "non_discriminative"}

        try:
            fragment = self._core.load_fragment(chunk_id)
            span = self._core.slice_span(fragment, char_start, char_end)
            result = self._core.judge_record(Tier.INTERPRETATION, render_meaning_claim(meaning), span)
            gate = self._core.gate(
                Tier.INTERPRETATION, result,
                fact_reason=ReasonCode.UNSUPPORTED_INTERPRETATION,
                interp_reason=ReasonCode.UNSUPPORTED_INTERPRETATION,
            )
            attestation = self._core.build_attestation(result, hashes={
                "evidence_sha256": sha256_text(span),
                "source_sha256": sha256_text(fragment.text),
            })
        except GroundingError as exc:
            return {"ok": False, "reason_code": str(exc.reason_code), "detail": exc.detail}

        surfaces = {s for ent in resolved_entities
                    for s in (ent.get("canonical"), *ent.get("aliases", ())) if s}
        flagged = gate.flagged or hook_unresolved(meaning, surfaces)
        # The brief's enrichment_meaning row is (source_chunk_id, claim_meaning[, embedding]) — it carries
        # NO provenance column, so a meaning is STORED ONLY IF it grounded (this code path), and the
        # attestation + flag travel in the write RESULT / glass-box, not the row. (Provenance-on-the-row
        # for meanings, to mirror records/links, is flagged as an open question in the engineer-log.)
        meaning_id = self._store.insert(source_chunk_id=fragment.chunk_id, claim_meaning=meaning)
        return {"ok": True, "meaning_id": meaning_id, "flagged": flagged,
                "provenance_validation": attestation}
