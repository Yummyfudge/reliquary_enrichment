from __future__ import annotations

"""register_tools — mount the enrichment tools onto the EXISTING FastMCP server (D1).

The spine's mcp_server.py adds exactly:

    from reliquary_enrichment.mcp import register_tools
    register_tools(mcp)

One server, one port (9666). This wires the four tools to Postgres-backed stores, the
shared grounding-core, and the live LiteLLM ``judge``, all sharing one in-process,
workstream-keyed HandleMap (Decision C). Building the services opens no connections (psycopg
connects per call), so registration is import-safe.

Read tools (get_chunk/get_neighbors) are read-only (auto-approve). The write tools
(write_enrichment/link_events) are judge-checked write boundaries.
"""

from typing import Annotated, Any

from reliquary_enrichment.entities import EntityResolver, EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.judge import LiteLLMGroundingJudge
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.postgres.entity_store import PostgresEntityStore
from reliquary_enrichment.postgres.fragment_reader import PostgresFragmentReader
from reliquary_enrichment.postgres.link_store import PostgresLinkStore
from reliquary_enrichment.postgres.record_store import PostgresEnrichmentRecordStore
from reliquary_enrichment.read_tools import ReadTools
from reliquary_enrichment.write_enrichment import WriteEnrichment

# NOTE: workstream_id keys the in-process HandleMap (Decision C). For now the orchestrator
# passes it explicitly (defaults to "default"). Binding it to the Turnstone session is an
# integration detail to confirm — flagged in findings.
_DEFAULT_WS = "default"


def build_services(*, handle_map: HandleMap | None = None) -> dict[str, Any]:
    """Construct the runtime services (Postgres + live judge). No connections opened here."""
    handle_map = handle_map or HandleMap()
    reader = PostgresFragmentReader()
    core = GroundingCore(
        fragment_reader=reader, handle_map=handle_map, judge=LiteLLMGroundingJudge()
    )
    entities = PostgresEntityStore()
    records = PostgresEnrichmentRecordStore()
    return {
        "read": ReadTools(fragment_reader=reader, handle_map=handle_map),
        "write": WriteEnrichment(
            core=core, record_store=records, entity_resolver=EntityResolver(entities)
        ),
        "link": LinkEvents(
            core=core, record_store=records, link_store=PostgresLinkStore(),
            event_materializer=EventMaterializer(entities),
        ),
    }


def register_tools(mcp, *, services: dict[str, Any] | None = None) -> None:
    """Register get_chunk, get_neighbors, write_enrichment, link_events on ``mcp``."""
    svc = services or build_services()
    read, write, link = svc["read"], svc["write"], svc["link"]

    @mcp.tool()
    def get_chunk(
        chunk_id: Annotated[str, "The Fragment's claim_chunk_id (UUID), e.g. from search."],
        workstream_id: Annotated[str, "Session/workstream key for the handle map."] = _DEFAULT_WS,
    ) -> dict:
        """Read one Fragment (raw source chunk) and get a short Chunk Handle for it.

        Returns the Fragment's text + provenance tagged with a handle (F1, F2, …). Use the
        handle in write_enrichment/link_events — never retype the UUID. Sets this Fragment
        as the workstream's current Fragment (per-Fragment passes can then omit the ref).
        """
        return read.get_chunk(chunk_id, workstream_id=workstream_id)

    @mcp.tool()
    def get_neighbors(
        chunk_id: Annotated[str, "Anchor Fragment's claim_chunk_id (UUID)."],
        window: Annotated[int, "How many segments on each side to include."] = 1,
        workstream_id: Annotated[str, "Session/workstream key for the handle map."] = _DEFAULT_WS,
    ) -> dict:
        """Read a Fragment plus its adjacent Fragments (same document), each handle-tagged.

        For finding related-but-distant context to cross-link in Pass 3.
        """
        return read.get_neighbors(chunk_id, window=window, workstream_id=workstream_id)

    @mcp.tool()
    def write_enrichment(
        record_type: Annotated[str, "What kind of record (controlled/emergent vocab)."],
        tier: Annotated[str, "'fact' (must be literally grounded) | 'interpretation'."],
        char_start: Annotated[int, "Start offset of the Evidence Span in the Fragment text."],
        char_end: Annotated[int, "End offset (exclusive). Code slices [start:end]; you POINT."],
        chunk_handle: Annotated[str | None, "Chunk Handle from a read tool. Omit in per-Fragment mode."] = None,
        fields: Annotated[dict | None, "Structured meaning, shape per record_type."] = None,
        actor: Annotated[str | None, "Actor name; judge-verified vs the span; resolved to an Entity."] = None,
        event_date: Annotated[str | None, "Normalized date; judge-verified; resolved to an Entity."] = None,
        confidence: Annotated[float | None, "0..1."] = None,
        chunk_id: Annotated[str | None, "Optional echoed chunk_id — a cross-check ONLY, never the source of truth."] = None,
        workstream_id: Annotated[str, "Session/workstream key for the handle map."] = _DEFAULT_WS,
    ) -> dict:
        """Write ONE grounded Enrichment Record. The model POINTS (handle + offsets +
        reasoning); code COPIES the exact span; the judge CHECKS it; the row ATTESTS.

        You never transcribe source tokens or supply evidence_span/page/document/hashes —
        those are code-derived. On rejection, re-POINT (fix the handle/offsets); never
        re-transcribe. Returns {ok, record_id, source_chunk_id, evidence_span,
        provenance_validation} or {ok:false, reason_code, detail}.
        """
        payload = {
            "record_type": record_type, "tier": tier,
            "char_start": char_start, "char_end": char_end,
            "chunk_handle": chunk_handle, "fields": fields or {},
            "actor": actor, "event_date": event_date,
            "confidence": confidence,
        }
        if chunk_id is not None:
            payload["chunk_id"] = chunk_id
        return write.write(payload, workstream_id=workstream_id)

    @mcp.tool()
    def link_events(
        record_a: Annotated[str, "An existing Enrichment Record id (record_id)."],
        record_b: Annotated[str, "A second existing Enrichment Record id."],
        relation: Annotated[str, "Relation: precedes/follows/causes/results_from/corroborates/contradicts/elaborates/same_event/references."],
        tier: Annotated[str, "'fact' (explicit cross-ref) | 'interpretation' (inference)."],
        a_span: Annotated[list[int], "[start, end] cited span in record_a's Fragment. You POINT; code slices."],
        b_span: Annotated[list[int], "[start, end] cited span in record_b's Fragment."],
        rationale: Annotated[str, "Why the relation holds (judge-checked)."],
        confidence: Annotated[float | None, "0..1."] = None,
        workstream_id: Annotated[str, "Session/workstream key."] = _DEFAULT_WS,
    ) -> dict:
        """Write ONE grounded cross-record Link into the Codex. Same law as records: the
        judge checks the relation against both code-sliced spans; both spans are hashed.

        Propose SPECIFIC pairs you have evidence for — never all-pairs. same_event links
        materialize/merge an Event Entity (code-maintained cluster). Returns {ok, link_id,
        relation, provenance_validation} or {ok:false, reason_code, detail}.
        """
        payload = {
            "record_a": record_a, "record_b": record_b, "relation": relation, "tier": tier,
            "evidence": {"a_span": list(a_span), "b_span": list(b_span)},
            "rationale": rationale, "confidence": confidence,
        }
        return link.link(payload, workstream_id=workstream_id)
