from __future__ import annotations

"""Extraction driver — the CANDIDATE model proposes records; code turns them into
write_enrichment payloads (the candidate is the variable under test; P1).

Pointing interface (deliberate, flagged): the candidate emits a VERBATIM QUOTE of the span
it grounds on — LLMs quote far more reliably than they count characters — and code LOCATES
that quote in the source text to derive char_start/char_end. The stored Evidence Span is
still code-sliced from the corpus (write_enrichment, unchanged); a corrupted/paraphrased
quote simply fails to locate and is dropped — never stored. So the invariant holds: the model
points (the quote), code copies (the located offsets), the judge checks, the row attests.
"""

import json
import os
import re
from dataclasses import dataclass, field

from reliquary_enrichment.grounding.judge import LITELLM_BASE_URL
from reliquary_enrichment.llm_http import post_json

CANDIDATE_MODEL: str = os.getenv("PROBE_CANDIDATE_MODEL", "big-thinker")
# Bounds for the candidate call (root-cause fix for the 2h hang): cap generation + a hard
# total deadline. A chunk's JSON array of proposals fits comfortably in ~2k tokens.
CANDIDATE_MAX_TOKENS: int = int(os.getenv("PROBE_CANDIDATE_MAX_TOKENS", "2048"))
CANDIDATE_DEADLINE_S: float = float(os.getenv("PROBE_CANDIDATE_DEADLINE_S", "180"))

_SYSTEM = (
    "You extract grounded facts from a single chunk of an insurance claim file. For each "
    "fact you find, you must QUOTE the exact span of the text that proves it — copied "
    "character-for-character, verbatim, no paraphrase. "
    "CRITICAL: the quote MUST literally contain EVERY value you assert in that record — the "
    "actor, the event_date, and each field value must all appear inside the quoted span. Do "
    "NOT assert a value that is not inside your quote. If the values you want are spread "
    "across a sentence, quote the WHOLE sentence; if two facts live in different sentences, "
    "make SEPARATE records, each quoting the sentence that contains its own values. For a "
    "tier=fact record, only assert actor/date/fields that are literally present in the quote. "
    "You reason about WHAT a span means and WHY it matters to the denial; you never invent "
    "facts not in the text. Reply with ONLY a JSON array of objects, each: "
    '{"quote": "<verbatim substring>", "record_type": "<short_snake_case>", '
    '"tier": "fact|interpretation", "fields": {<structured meaning>}, '
    '"actor": "<person/org or null>", "event_date": "<YYYY-MM-DD or null>", '
    '"claim_relevance": "<why it matters, or null>", "confidence": <0..1>}. '
    "tier=fact for literal facts; tier=interpretation for inferences that cite the span. "
    "Return [] if the chunk contains nothing groundable."
)


@dataclass(slots=True)
class ExtractionProposal:
    """One record the candidate proposed (pre-grounding)."""

    quote: str
    record_type: str
    tier: str = "fact"
    fields: dict = field(default_factory=dict)
    actor: str | None = None
    event_date: str | None = None
    claim_relevance: str | None = None
    confidence: float | None = None


def build_extraction_messages(chunk_text: str) -> tuple[str, str]:
    user = (
        "Extract every groundable fact from this chunk. Quote spans verbatim.\n\n"
        f"CHUNK TEXT:\n{chunk_text}"
    )
    return _SYSTEM, user


def parse_proposals(content: str) -> list[ExtractionProposal]:
    """Defensively parse the candidate's JSON array into proposals (tolerant; drops junk).

    Unlike the judge (which fails closed), a malformed extraction reply yields fewer/zero
    proposals — that just lowers the candidate's score, it can never write anything ungrounded
    (write_enrichment still gates each proposal).
    """
    raw = content or ""
    arr = _extract_json_array(raw)
    proposals: list[ExtractionProposal] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote")
        record_type = item.get("record_type")
        if not isinstance(quote, str) or not quote.strip():
            continue
        if not isinstance(record_type, str) or not record_type.strip():
            record_type = "fact"
        tier = item.get("tier") if item.get("tier") in ("fact", "interpretation") else "fact"
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        conf = item.get("confidence")
        proposals.append(ExtractionProposal(
            quote=quote,
            record_type=record_type.strip(),
            tier=tier,
            fields=fields,
            actor=_str_or_none(item.get("actor")),
            event_date=_str_or_none(item.get("event_date")),
            claim_relevance=_str_or_none(item.get("claim_relevance")),
            confidence=float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None,
        ))
    return proposals


def _str_or_none(v) -> str | None:
    if isinstance(v, str) and v.strip() and v.strip().lower() != "null":
        return v
    return None


def _extract_json_array(raw: str) -> list:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(obj, dict):  # tolerate {"records": [...]} or a single object
        for key in ("records", "facts", "proposals", "items"):
            if isinstance(obj.get(key), list):
                return obj[key]
        return [obj]
    return obj if isinstance(obj, list) else []


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find the candidate's verbatim quote in the source text -> (char_start, char_end).

    Exact match first (the model is asked to copy verbatim). Falls back to a
    whitespace-normalized search so trivial spacing differences still locate a real span
    (offsets always index the ORIGINAL text; the stored span stays byte-exact from source).
    Returns None if the quote can't be located — that proposal is dropped, never stored.
    """
    q = quote.strip()
    if not q:
        return None
    idx = text.find(q)
    if idx != -1:
        return idx, idx + len(q)
    # whitespace-tolerant fallback: match the quote's tokens with any whitespace between.
    m = re.search(_ws_regex(q), text)
    if m:
        return m.start(), m.end()
    return None


def _ws_regex(q: str) -> str:
    """Build a regex matching the quote with any run of whitespace between non-space tokens."""
    parts = [re.escape(tok) for tok in q.split()]
    return r"\s+".join(parts)


class CandidateExtractor:
    """Calls the candidate model (LiteLLM alias) to propose records from a chunk."""

    def __init__(
        self,
        *,
        model: str = CANDIDATE_MODEL,
        base_url: str = LITELLM_BASE_URL,
        max_tokens: int = CANDIDATE_MAX_TOKENS,
        deadline_s: float = CANDIDATE_DEADLINE_S,
    ) -> None:
        self._model = model
        self._endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._max_tokens = max_tokens
        self._deadline_s = deadline_s

    @property
    def model(self) -> str:
        return self._model

    def extract(self, chunk_text: str) -> list[ExtractionProposal]:
        """Call the candidate under a hard deadline. Raises LLMTimeout/RequestException on
        failure — the runner catches it, logs, and SKIPS the chunk (never kills the run)."""
        system, user = build_extraction_messages(chunk_text)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": self._max_tokens,
        }
        body = post_json(
            self._endpoint, payload,
            read_timeout=min(self._deadline_s, 120.0), total_deadline=self._deadline_s,
        )
        return parse_proposals(body["choices"][0]["message"]["content"])
