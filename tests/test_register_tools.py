from __future__ import annotations

"""register_tools mounts the four tools on a FastMCP instance and routes to the services.

Offline: fake services injected, so no DB/judge. Proves the spine's 3-line hook works and
the tools wire through to the grounding pipeline.
"""

import asyncio

from fastmcp import FastMCP

from reliquary_enrichment.entities import EntityResolver, EventMaterializer
from reliquary_enrichment.grounding.core import GroundingCore
from reliquary_enrichment.grounding.fragments import Fragment
from reliquary_enrichment.grounding.handles import HandleMap
from reliquary_enrichment.grounding.types import Verdict
from reliquary_enrichment.link_events import LinkEvents
from reliquary_enrichment.mcp import register_tools
from reliquary_enrichment.read_tools import ReadTools
from reliquary_enrichment.write_enrichment import WriteEnrichment
from tests.fakes.fake_fragment_reader import FakeFragmentReader
from tests.fakes.fake_judge import ConstantJudge
from tests.fakes.fake_stores import FakeEntityStore, FakeLinkStore, FakeRecordStore

CID = "11111111-1111-1111-1111-111111111111"
TEXT = "Supervisor B. Smith reversed the prior approval on 2025-02-18."


def _fake_services():
    reader = FakeFragmentReader({CID: Fragment(CID, TEXT, "denial.pdf", 7, "status_change")})
    hm = HandleMap()
    core = GroundingCore(fragment_reader=reader, handle_map=hm, judge=ConstantJudge(Verdict.GROUNDED))
    entities = FakeEntityStore()
    records = FakeRecordStore()
    return {
        "read": ReadTools(fragment_reader=reader, handle_map=hm),
        "write": WriteEnrichment(core=core, record_store=records, entity_resolver=EntityResolver(entities)),
        "link": LinkEvents(core=core, record_store=records, link_store=FakeLinkStore(),
                           event_materializer=EventMaterializer(entities)),
    }


def test_all_four_tools_registered():
    mcp = FastMCP("test")
    register_tools(mcp, services=_fake_services())
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_chunk", "get_neighbors", "write_enrichment", "link_events"} <= names


def test_get_chunk_then_write_through_mcp_call():
    mcp = FastMCP("test")
    register_tools(mcp, services=_fake_services())

    async def scenario():
        got = await mcp.call_tool("get_chunk", {"chunk_id": CID, "workstream_id": "w"})
        data = got.structured_content if hasattr(got, "structured_content") else got.data
        handle = data["chunk_handle"]
        wrote = await mcp.call_tool("write_enrichment", {
            "chunk_handle": handle, "char_start": 0, "char_end": 28,
            "record_type": "status_change", "tier": "fact", "actor": "B. Smith",
            "event_date": "2025-02-18", "workstream_id": "w",
        })
        return wrote.structured_content if hasattr(wrote, "structured_content") else wrote.data

    out = asyncio.run(scenario())
    assert out["ok"] is True and out["evidence_span"] == TEXT[0:28]
