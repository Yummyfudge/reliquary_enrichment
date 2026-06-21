from __future__ import annotations

"""Pass 5 (slot) — MeaningWriterPass: the gated, GROUNDED, embedded LOCAL-FACT meaning (brief §5.4, §7).

Replaces the old meta-summary Pass 5. The bright line's embedded side: per chunk, assemble the chunk's
resolved codex entities (carrying the theme-flag from the discriminative pass), let the model PROPOSE a
local-fact meaning + the verbatim span that grounds it, CODE locates the span, and the gated MeaningWriter
does the rest — meta-phrase pre-filter -> HARD discriminativeness gate -> Tier.INTERPRETATION grounding ->
hook flag -> store into enrichment_meaning. The meaning is the ONLY embedded artifact and NEVER routes
through enrichment_records.

Runs LAST (§7): the codex (entities + theme-flags) must exist before the discriminativeness gate can tell
a discriminator from a theme. Injected via ctx.extras (meaning_writer, meaning_proposer, record_store,
entity_store), so it is unit-testable with fakes — no lane needed to build.
"""

from typing import Any

from reliquary_enrichment.multipass.locate import locate_quote
from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult


def resolved_entities_for_chunk(record_store, entity_store, chunk_id: str) -> list[dict]:
    """The chunk's resolved codex entities for the discriminativeness gate: {canonical, aliases, is_theme}.
    Sourced from the chunk's grounded records' entity_refs -> the codex Entity (theme-flag from §9). Falls
    back to the ref's own canonical (theme unknown -> False) if the entity isn't loadable."""
    out: list[dict] = []
    seen: set[str] = set()
    for rec in record_store.records_by_chunk(chunk_id):
        for ref in rec.entity_refs:
            if ref.entity_id in seen:
                continue
            seen.add(ref.entity_id)
            entity = entity_store.get(ref.entity_id) if entity_store else None
            if entity is None:
                out.append({"canonical": ref.canonical, "entity_type": ref.entity_type,
                            "aliases": [], "is_theme": False})
            else:
                out.append({"canonical": entity.canonical, "entity_type": entity.entity_type,
                            "aliases": list(entity.aliases),
                            "is_theme": bool(entity.metadata.get("is_theme"))})
    return out


class MeaningWriterPass(Pass):
    name = "5_meaning"
    per_chunk = True

    def process_chunk(
        self, chunk: ChunkRef, prior: dict[str, PassResult], ctx: PassContext
    ) -> tuple[Any, int]:
        writer = ctx.extras["meaning_writer"]
        propose = ctx.extras["meaning_proposer"]
        record_store = ctx.extras["record_store"]
        entity_store = ctx.extras.get("entity_store")
        ws = ctx.extras.get("meaning_workstream_id", "mp-meaning")

        resolved = resolved_entities_for_chunk(record_store, entity_store, chunk.chunk_id)
        obj, tokens = propose(chunk.text)
        meaning = str(obj.get("meaning", "")).strip()
        quote = str(obj.get("quote", "")).strip()
        if not meaning or not quote:
            return {"ok": False, "reason_code": "no_proposal"}, tokens
        span = locate_quote(chunk.text, quote)             # CODE COPIES the span (grounding law)
        if span is None:
            return {"ok": False, "reason_code": "locate_miss"}, tokens
        result = writer.write(
            chunk_id=chunk.chunk_id, meaning=meaning, char_start=span[0], char_end=span[1],
            resolved_entities=resolved, workstream_id=ws,
        )
        return result, tokens
