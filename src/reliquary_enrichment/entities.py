from __future__ import annotations

"""Codex Entity resolution — code materializes Entities; the model never types one.

Normalize a judge-validated surface form (actor / date / code / location / document / provision)
to a canonical key and resolve-or-create the Entity (dedupe key = entity_type + canonical). Used
by write_enrichment step 9 (resolves EVERY typed entity) and link_events §6 (event, from same_event).

Canonicalization is per-type and REAL (brief §5.2 — the CRQ-001 dedupe lever): date -> ISO-8601,
code -> upper/whitespace-stripped, location/document/provision -> whitespace-normalized, actor ->
whitespace/separator-normalized. It stays alias-not-merge: surface variants of the SAME entity
collapse to one canonical (variants recorded as aliases), while GENUINELY ambiguous identities
("B. Smith" vs "Bruce Smith") are NEVER silently merged — they keep distinct canonicals and are
flagged for curation downstream (pass2_9_normalize). Dates assume the corpus's US M/D/Y convention.
"""

import datetime as _dt
import re
import unicodedata

from reliquary_enrichment.models import Entity, EntityRef
from reliquary_enrichment.stores import EntityStore

_WS = re.compile(r"\s+")

# Valid month tokens: full names + 3-letter abbreviations (+ 'sept'). The WHOLE captured word
# must match — a non-month word that merely STARTS with a month prefix (e.g. "Marbles" -> "mar")
# must NOT be read as a date, or a non-date surface would silently merge onto a real date node.
_MONTH_TOKENS: dict[str, int] = {}
for _i, (_abbr, _full) in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
    ("may", "may"), ("jun", "june"), ("jul", "july"), ("aug", "august"),
    ("sep", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
), start=1):
    _MONTH_TOKENS[_abbr] = _i
    _MONTH_TOKENS[_full] = _i
_MONTH_TOKENS["sept"] = 9

# Separators accepted: '-', '/', '.'. Year-first (ISO order) vs year-last (M/D/Y) are distinguished
# by which end carries the year. The corpus is US M/D/Y (verified on the slice — same date appears as
# 12/04/2023 = 12/04/23 = 12/4/23); 2-digit years are expanded by the standard convention. This does
# NOT over-merge: every distinct (month, day, year) still maps to a distinct ISO; only same-date
# different-format surfaces collapse.
_ISO_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
# Year is EXACTLY 2 or 4 digits — a 3-digit OCR year (e.g. "12/05/022") is garbage, not a date,
# and must return the surface unchanged rather than coerce to a confident-but-wrong ISO.
_NUM_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")
# "Feb 18 2025" / "February 18, 2025" / "Feb 18, 2025"
_MDY_NAME_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
# "18 Feb 2025" / "18 February, 2025"
_DMY_NAME_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$")


def _month_num(word: str) -> int | None:
    """Month number for a FULL month token (name or 3-letter abbrev), else None — strict, so a word
    that merely starts with a month prefix ('Marbles') is not mistaken for a month."""
    return _MONTH_TOKENS.get(word.strip().rstrip(".").lower())


def _iso(year, month, day) -> str | None:
    """Build an ISO date string, or None if (year, month, day) is not a real calendar date."""
    try:
        return _dt.date(int(year), int(month), int(day)).isoformat()
    except (ValueError, TypeError):
        return None


def _expand_year(y: str) -> int:
    """Expand a 2-digit year by the standard convention (00-68 -> 2000s, 69-99 -> 1900s); any other
    width (4-digit) passes through. The corpus is 2023-2025 claims data, so 23/24/25 -> 2023/2024/2025."""
    if len(y) == 2:
        n = int(y)
        return 2000 + n if n <= 68 else 1900 + n
    return int(y)


def normalize_date(surface: str) -> str:
    """Canonicalize a date surface to ISO-8601 (YYYY-MM-DD). Handles ISO, US ``M/D/Y`` (the corpus
    convention — 2-digit years expanded), and month-name forms (``Feb 18 2025`` / ``February 18,
    2025`` / ``18 Feb 2025``). A non-date / unparseable surface returns unchanged (``Marbles 5 2025``
    is not a date — strict month tokens). Distinct dates always map to distinct ISO, so this never
    over-merges; only same-date different-format surfaces (``12/4/23`` / ``12/04/2023``) collapse.
    """
    s = _WS.sub(" ", unicodedata.normalize("NFKC", surface)).strip()
    m = _ISO_RE.match(s)
    if m:
        return _iso(*m.groups()) or s
    m = _MDY_NAME_RE.match(s)
    if m:
        mon = _month_num(m.group(1))
        return (_iso(m.group(3), mon, m.group(2)) or s) if mon else s
    m = _DMY_NAME_RE.match(s)
    if m:
        mon = _month_num(m.group(2))
        return (_iso(m.group(3), mon, m.group(1)) or s) if mon else s
    m = _NUM_RE.match(s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        y = _expand_year(m.group(3))
        if a <= 12:                    # US M/D/Y (the corpus convention; b>12 just confirms order)
            return _iso(y, a, b) or s
        if b <= 12:                    # a>12, so a must be the day -> D/M/Y
            return _iso(y, b, a) or s
        return s                       # both >12 -> not a valid calendar date
    return s


def normalize_code(surface: str) -> str:
    """Canonical code: NFKC-fold (full-width OCR digits ``F0６.４`` -> ``F06.4``) + strip ALL
    whitespace + uppercase (``f06.4`` / ``F 06.4`` -> ``F06.4``). Distinct codes (``F07.4`` vs
    ``F06.4``) stay distinct — no over-merge."""
    return _WS.sub("", unicodedata.normalize("NFKC", surface)).strip().upper()


def normalize_location(surface: str) -> str:
    """Collapse whitespace; keep casing (conservative — distinct places must not merge)."""
    return _WS.sub(" ", surface).strip()


def normalize_document(surface: str) -> str:
    """Collapse whitespace; keep casing (conservative — distinct documents must not merge)."""
    return _WS.sub(" ", surface).strip()


def normalize_provision(surface: str) -> str:
    """Collapse whitespace; keep casing (conservative — distinct provisions must not merge)."""
    return _WS.sub(" ", surface).strip()


def normalize_actor(surface: str) -> str:
    """Collapse whitespace and strip surrounding separators (``B. Smith:`` -> ``B. Smith``); keep
    casing/identity. Alias-not-merge: distinct names ("B. Smith" vs "Bruce Smith") are NEVER
    collapsed — fuzzy name identity is a curation-gated task (codex §9-B)."""
    return _WS.sub(" ", surface).strip().strip(" :;,")


_NORMALIZERS = {
    "actor": normalize_actor,
    "date": normalize_date,
    "code": normalize_code,
    "location": normalize_location,
    "document": normalize_document,
    "provision": normalize_provision,
}


class EntityResolver:
    """Resolve-or-create Entities against an EntityStore, recording aliases."""

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    def resolve_or_create(
        self,
        entity_type: str,
        surface: str,
        *,
        first_seen_record: str | None = None,
    ) -> Entity:
        """Return the Entity for (type, normalized surface), creating it if new.

        On a hit, record the surface form as an alias when it differs from canonical (so
        the registry learns variants without merging). On a miss, create with
        ``first_seen_record`` set.
        """
        normalize = _NORMALIZERS.get(entity_type, lambda s: s.strip())
        canonical = normalize(surface)
        existing = self._store.find(entity_type, canonical)
        if existing is not None:
            if surface != canonical and surface not in existing.aliases:
                self._store.add_alias(existing.entity_id, surface)
            return existing
        entity = Entity(
            entity_type=entity_type,
            canonical=canonical,
            aliases=[] if surface == canonical else [surface],
            first_seen_record=first_seen_record,
        )
        self._store.insert(entity)
        return entity

    def ref_for(self, role: str, entity: Entity) -> EntityRef:
        """Build the EntityRef a record stores at this Entity."""
        return EntityRef(
            role=role,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            canonical=entity.canonical,
        )


class EventMaterializer:
    """Materialize/merge Event Entities from grounded same_event Links (codex §6).

    The ONLY way an Event Entity is born. The model asserts pairwise same_event + grounded;
    CODE maintains the cluster (union-find over record_ids), including transitive merges
    (A~B, B~C => one event). Membership is stored on the Event Entity (metadata.member_records)
    — records are write-once and are never mutated; their event is found by membership.
    """

    def __init__(self, store: EntityStore) -> None:
        self._store = store

    @staticmethod
    def _members(event: Entity) -> list[str]:
        return list(event.metadata.get("member_records", []))

    def materialize(self, record_a: str, record_b: str) -> Entity:
        """Place record_a and record_b in one Event cluster; return the surviving Entity."""
        ea = self._store.event_for_record(record_a)
        eb = self._store.event_for_record(record_b)

        if ea is not None and eb is not None:
            if ea.entity_id == eb.entity_id:
                return ea                                   # already the same cluster
            return self._merge(ea, eb)                      # transitive merge
        if ea is not None:
            self._add_member(ea, record_b)
            return ea
        if eb is not None:
            self._add_member(eb, record_a)
            return eb
        return self._create(record_a, record_b)

    def _create(self, record_a: str, record_b: str) -> Entity:
        members = sorted({record_a, record_b})
        # canonical is a stable label; membership (metadata) is the authoritative identity.
        event = Entity(
            entity_type="event",
            canonical=f"event:{members[0]}",
            metadata={"member_records": members},
            first_seen_record=record_a,
        )
        self._store.insert(event)
        return event

    def _add_member(self, event: Entity, record_id: str) -> None:
        members = sorted(set(self._members(event)) | {record_id})
        event.metadata["member_records"] = members
        self._store.set_event_members(event.entity_id, members)

    def _merge(self, survivor: Entity, absorbed: Entity) -> Entity:
        members = sorted(set(self._members(survivor)) | set(self._members(absorbed)))
        survivor.metadata["member_records"] = members
        self._store.set_event_members(survivor.entity_id, members)
        self._store.mark_event_merged(absorbed.entity_id, survivor.entity_id)
        return survivor
