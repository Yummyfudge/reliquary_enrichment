"""reliquary_enrichment — the claim-aware meaning layer's MCP tools.

What: grounded, cross-linked enrichment over the context_reliquary claim corpus —
the tools `write_enrichment`, `link_events`, `get_chunk`, `get_neighbors`, built on
one shared grounding-core.

Why: vector search alone can't surface the gold note (a supervisor reversal that
ranks ~30-47 under every embedder). Enrichment is the lever. The package enforces
ONE law mechanically at every write boundary — the model *points*, code *copies* the
exact tokens, a judge *checks*, the row *attests*; nothing reaches storage ungrounded.

This package is editable-installed into the `context-reliquary` conda env and its
tools are registered onto the EXISTING context_reliquary FastMCP server via
`reliquary_enrichment.mcp.register_tools` (Decision D1) — single server, one port.
"""

__version__ = "0.1.0"
