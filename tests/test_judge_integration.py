from __future__ import annotations

"""Integration tests for the REAL grounding judge (Decision D2).

Marked ``integration`` — they hit the live LiteLLM ``judge`` alias (Qwen2.5-14B-Q6) and
are skipped by default (``addopts = -m 'not integration'``). Run explicitly with:
    pytest -m integration tests/test_judge_integration.py

These prove the heart's transport + defensive parser work against real model output —
not a fake — and that the judge catches value drift (the 89503-class failure).
"""

import pytest
import requests

from reliquary_enrichment.grounding.judge import JUDGE_MODEL_ALIAS, LITELLM_BASE_URL, LiteLLMGroundingJudge
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.types import Tier, Verdict

SPAN = "Supervisor B. Smith reversed the prior approval on 2025-02-18."

pytestmark = pytest.mark.integration


def _judge_available() -> bool:
    try:
        resp = requests.get(f"{LITELLM_BASE_URL}/v1/models", timeout=5)
        ids = [m["id"] for m in resp.json().get("data", [])]
        return JUDGE_MODEL_ALIAS in ids
    except Exception:
        return False


@pytest.fixture(scope="module")
def core() -> GroundingCore:
    if not _judge_available():
        pytest.skip(f"judge alias {JUDGE_MODEL_ALIAS!r} not live at {LITELLM_BASE_URL}")
    c = GroundingCore.__new__(GroundingCore)
    c._judge = LiteLLMGroundingJudge()
    return c


def test_real_judge_grounds_a_true_fact(core):
    r = core.judge_record(Tier.FACT, "B. Smith reversed the prior approval on 2025-02-18", SPAN)
    assert r.verdict is Verdict.GROUNDED


def test_real_judge_catches_date_drift(core):
    # 19th vs the span's 18th — the value the whole system exists to catch.
    r = core.judge_record(Tier.FACT, "B. Smith reversed the prior approval on 2025-02-19", SPAN)
    assert r.verdict is not Verdict.GROUNDED
    # the judge names the failing VALUE (or field) — either way the drift is surfaced.
    assert r.failing_values or "date" in r.reason.lower()


def test_real_judge_catches_word_drift(core):
    # "reversible" is not "reversed" — fabricated/altered word.
    r = core.judge_record(Tier.FACT, "The approval was deemed reversible by policy", SPAN)
    assert r.verdict is not Verdict.GROUNDED
