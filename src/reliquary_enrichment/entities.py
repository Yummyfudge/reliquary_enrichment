from __future__ import annotations

"""Codex Entity resolution — code materializes Entities; the model never types one.

Normalize a judge-validated surface form (actor / date / code / location / document / provision)
to a canonical key and resolve-or-create the Entity (dedupe key = entity_type + canonical). Used
by write_enrichment step 9 (resolves EVERY typed entity) and link_events §6 (event, from same_event).

Canonicalization is per-type and REAL (brief §5.2 — the CRQ-001 dedupe lever): date -> ISO-8601,
code -> upper/whitespace-stripped, location/document/provision -> whitespace-normalized, actor ->
whitespace/separator-normalized. It stays alias-not-merge: surface variants of the SAME entity
collapse to one canonical (variants recorded as aliases), while GENUINELY ambiguous identities
("B. Smith" vs "Bruce Smith"; an all-numeric date that could be M/D or D/M) are NEVER silently
merged — they keep distinct canonicals and are flagged for curation downstream (pass2_9_normalize).
"""

import datetime as _dt
import re

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

# Separators accepted: '-', '/', '.'. Year-first (ISO order) vs year-last (M/D or D/M) are
# distinguished by which end carries the 4-digit year. 2-digit years are NOT expanded (the century
# is a guess) — they stay a distinct surface, never silently bucketed into a guessed year.
_ISO_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUM_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
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


def normalize_date(surface: str) -> str:
    """Canonicalize a date surface to ISO-8601 (YYYY-MM-DD) when UNAMBIGUOUS; otherwise return the
    cleaned surface unchanged (never guess — an ambiguous date must not silently merge).

    Handles ISO, ``M/D/Y`` / ``D/M/Y`` (disambiguated only when one component is > 12), and
    month-name forms (``Feb 18 2025`` / ``February 18, 2025`` / ``18 Feb 2025``).
    """
    s = _WS.sub(" ", surface).strip()
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
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if a > 12 and b <= 12:        # first component is the day -> D/M/Y
            return _iso(y, b, a) or s
        if b > 12 and a <= 12:        # second component is the day -> M/D/Y
            return _iso(y, a, b) or s
        return s                       # both <=12 (ambiguous) or both >12 (invalid) -> no guess
    return s


def normalize_code(surface: str) -> str:
    """Canonical code: strip ALL whitespace + uppercase (``f06.4`` / ``F 06.4`` -> ``F06.4``)."""
    return _WS.sub("", surface).strip().upper()


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
