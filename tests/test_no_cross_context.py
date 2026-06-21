from __future__ import annotations

"""Permanent guardrail — NO cross-context dependencies (codex refactor §12/§13, Joe's standing
invariant). This codifies "no cross-context deps" as a test, not a one-time grep: it FAILS the suite
if anyone ever reintroduces a `probe/` import (deprecated in full) or a `context_reliquary` PYTHON
import into the package. (SQL strings that name context_reliquary — the read-only corpus — are fine;
only Python-level imports across the context boundary are forbidden: a needed thing MOVES in.)
"""

import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "reliquary_enrichment"

_PROBE = re.compile(
    r"^\s*(from\s+reliquary_enrichment\.probe|import\s+reliquary_enrichment\.probe"
    r"|from\s+reliquary_enrichment\s+import\s+probe)\b", re.M)
_CONTEXT = re.compile(r"^\s*(from\s+context_reliquary|import\s+context_reliquary)\b", re.M)


def _offenders(pattern: re.Pattern) -> list[str]:
    return [str(p.relative_to(PKG)) for p in PKG.rglob("*.py") if pattern.search(p.read_text())]


def test_no_probe_imports_anywhere_in_package():
    assert _offenders(_PROBE) == [], "probe/ is deprecated in full (§13) — no imports allowed"


def test_no_context_reliquary_python_imports():
    assert _offenders(_CONTEXT) == [], "no cross-context Python imports (§12) — move it in instead"


def test_probe_package_is_gone():
    assert not (PKG / "probe").exists(), "probe/ must be deleted in full (§13)"


_EMBED_WRITE = re.compile(r"SET\s+embedding|::vector|\bembedding\s*=\s*%", re.I)


def test_bright_line_only_meaning_store_writes_an_embedding():
    # The bright line (brief §3.1/§5.3): enrichment_meaning.embedding is the ONLY embedded artifact, and
    # ONLY postgres/meaning_store.py may write it. Fails the suite if anything else embeds.
    writers = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py") if _EMBED_WRITE.search(p.read_text())]
    assert writers == ["postgres/meaning_store.py"], writers
