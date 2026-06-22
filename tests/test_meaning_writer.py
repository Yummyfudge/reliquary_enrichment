from __future__ import annotations

"""Acceptance tests for the gated MeaningWriter (brief §5.4 #4/#7/#8/#10, build step 8).

THE GATE'S ACCEPTANCE IS TWO-POLE CALIBRATION (Joe), both poles BEFORE the first scored run:
  * REJECT "Cheers, Joe" — trivia, no non-theme entity (the negative pole).
  * ACCEPT a hand-authored gold local fact "Manager B. Smith placed the claim back under the Mental
    Health limitation" (the positive pole).
The judge only checks non-contradiction (a generic meaning grounds clean), so the discriminativeness gate
is the ONLY defense — a gate tuned to kill trivia must NOT also kill the gold note's discriminative-but-
paraphrased meaning. The hook check confirms the gold meaning's nouns (B. Smith, the MH limitation)
resolve to the codex entities that exist on that chunk's records.
"""

from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.meaning_writer import (
    MeaningWriter,
    has_discriminative_substance,
    hook_unresolved,
    is_meta_phrase,
)
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge
from tests.fakes.fake_meaning_store import FakeMeaningStore

GOLD_ID = "89503c71-5ca2-424b-9386-6698a8337dc3"
GOLD_TEXT = "Body Reviewed with manager B. Smith: Place claim back to a Mental Health limitation"
GOLD_MEANING = "Manager B. Smith placed the claim back under the Mental Health limitation"
GOLD_ENTITIES = [
    {"canonical": "B. Smith", "aliases": ["manager B. Smith"], "entity_type": "actor", "is_theme": False},
    {"canonical": "Mental Health limitation", "aliases": [], "entity_type": "provision", "is_theme": False},
    {"canonical": "the claim", "aliases": [], "entity_type": "event", "is_theme": True},   # a THEME
]


def _writer(judge=None):
    reader = FakeFragmentReader({GOLD_ID: Fragment(GOLD_ID, GOLD_TEXT, "denial.txt", 15, "note")})
    core = GroundingCore(fragment_reader=reader, handle_map=HandleMap(),
                         judge=judge or ConstantJudge(Verdict.GROUNDED))
    store = FakeMeaningStore()
    return MeaningWriter(core=core, meaning_store=store), store


def _write(w, meaning, entities=GOLD_ENTITIES):
    return w.write(chunk_id=GOLD_ID, meaning=meaning, char_start=0, char_end=len(GOLD_TEXT),
                   resolved_entities=entities)


# --- TWO-POLE discriminativeness calibration (the gate's acceptance) ---------
def test_gate_REJECTS_trivia_no_non_theme_entity():
    w, store = _writer()
    out = _write(w, "Cheers, Joe", entities=[])           # negative pole: no non-theme entity
    assert out["ok"] is False and out["reason_code"] == "non_discriminative"
    assert store.meanings == {}                           # nothing stored


def test_gate_ACCEPTS_gold_local_fact():
    w, store = _writer()
    out = _write(w, GOLD_MEANING)                         # positive pole: the gold local fact
    assert out["ok"] is True and out["flagged"] is False  # discriminative + grounded + hooks resolve
    assert store.meanings[GOLD_ID] == GOLD_MEANING        # the gold fact IS stored


def test_gate_rejects_theme_only_meaning():
    # a meaning that only restates the THEME ("the claim") names no DISCRIMINATOR -> rejected.
    w, store = _writer()
    out = _write(w, "The claim was reviewed")
    assert out["ok"] is False and out["reason_code"] == "non_discriminative" and store.meanings == {}


# --- meta-phrase pre-filter (ahead of the judge) ----------------------------
def test_meta_phrase_rejected_before_judge():
    w, store = _writer()
    out = _write(w, "This chunk indicates the claim was reviewed by B. Smith")
    assert out["ok"] is False and out["reason_code"] == "meta_phrase" and store.meanings == {}


def test_is_meta_phrase_family():
    assert is_meta_phrase("This record documents the denial")
    assert is_meta_phrase("The significance to the claim is the reversal")
    assert is_meta_phrase("This is important because the claim was reversed")
    assert is_meta_phrase("What this means for the denial is a reversal by B. Smith")  # the evader
    assert not is_meta_phrase(GOLD_MEANING)               # a real local fact is NOT meta


def test_meta_phrase_does_not_over_reject_real_subject_with_verb():
    # the meta filter must anchor on a META SUBJECT (this chunk / what this means), NOT a bare verb — a
    # legit local fact whose REAL subject uses 'shows that' / 'reflects that' is a fact, not meta.
    assert not is_meta_phrase("Dr. Smith shows that the MRI is normal")
    assert not is_meta_phrase("Manager B. Smith reflects that the claim should reopen")


def test_meta_phrase_evader_rejected_end_to_end():
    # 'What this means for the denial is ...' carries a non-theme entity + grounds clean, yet is meta —
    # it must die at the meta gate BEFORE storage (the high-severity false-store the review found).
    w, store = _writer()
    out = _write(w, "What this means for the denial is a reversal by B. Smith")
    assert out["ok"] is False and out["reason_code"] == "meta_phrase" and store.meanings == {}


# --- grounding at Tier.INTERPRETATION ---------------------------------------
def test_ungrounded_meaning_rejected_by_judge():
    w, store = _writer(judge=ConstantJudge(Verdict.UNGROUNDED))
    out = _write(w, GOLD_MEANING)
    assert out["ok"] is False and store.meanings == {}    # passes the gates but the judge rejects it


def test_partial_meaning_accepted_but_flagged():
    w, store = _writer(judge=ConstantJudge(Verdict.PARTIAL))
    out = _write(w, GOLD_MEANING)
    assert out["ok"] is True and out["flagged"] is True and store.meanings[GOLD_ID] == GOLD_MEANING


# --- hook-resolution check (FLAG, not reject) -------------------------------
def test_hook_flags_unresolved_capitalized_noun():
    w, store = _writer()
    out = _write(w, "B. Smith consulted Dr. Frankenstein")   # B. Smith resolves; Dr. Frankenstein does NOT
    assert out["ok"] is True and out["flagged"] is True       # stored, but flagged for curation


def test_hook_does_not_flag_when_all_nouns_resolve():
    assert hook_unresolved(GOLD_MEANING,
                           {"B. Smith", "manager B. Smith", "Mental Health limitation", "the claim"}) is False


def test_hook_does_not_flag_titlecase_common_words():
    # ordinary sentence-initial / document Title-Case of COMMON words ('The Claim') is not a name-like
    # span — it must NOT pollute the curation queue when the real entity (B. Smith) resolves.
    assert hook_unresolved("The Claim was reviewed by B. Smith", {"B. Smith"}) is False


def test_has_discriminative_substance_pure():
    assert has_discriminative_substance("B. Smith reversed it", GOLD_ENTITIES) is True
    assert has_discriminative_substance("the claim was reviewed", GOLD_ENTITIES) is False   # theme only


def test_discriminativeness_accepts_actor_surface_paraphrases():
    # the gate must resolve the SAME B. Smith codex entity through natural surface paraphrases even when
    # the provision phrase is absent — the false-reject the review flagged HIGH (surname / no-space / title).
    assert has_discriminative_substance("Smith reopened the claim", GOLD_ENTITIES) is True   # surname-only
    assert has_discriminative_substance("B.Smith reopened the file", GOLD_ENTITIES) is True  # no-space
    assert has_discriminative_substance("Determination by Dr. Smith", GOLD_ENTITIES) is True  # title


def test_discriminativeness_rejects_substring_coincidence():
    # word-level, not infix: 'Smith' inside 'Blacksmith' is NOT the B. Smith entity (the MED false-accept).
    assert has_discriminative_substance("Blacksmith tools were noted", GOLD_ENTITIES) is False


def test_discriminativeness_date_is_gated_on_a_non_theme_date_entity():
    # a concrete dated action counts ONLY when tied to a NON-THEME date entity — a THEME date, or a date
    # the codex doesn't carry, is NOT substance (the step-10 review's date-token hole).
    THEME_DATE = [{"canonical": "2025-01-01", "entity_type": "date", "aliases": [], "is_theme": True}]
    DISCRIM_DATE = [{"canonical": "2024-02-18", "entity_type": "date", "aliases": [], "is_theme": False}]
    assert has_discriminative_substance("Status note dated 2025-01-01", THEME_DATE) is False   # theme date
    assert has_discriminative_substance("Reversed on 2025-01-01", []) is False                 # no date entity
    assert has_discriminative_substance("Reversed on 2024-02-18", DISCRIM_DATE) is True         # non-theme date


# --- the bright line: MeaningWriter never embeds ----------------------------
def test_meaning_writer_stores_text_never_embeds():
    w, store = _writer()
    _write(w, GOLD_MEANING)
    assert store.embedded == {}                           # claim_meaning written; NO embedding (deferred)
