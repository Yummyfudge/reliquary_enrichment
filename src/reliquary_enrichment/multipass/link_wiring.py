from __future__ import annotations

"""Real CrossChunkLink proposer — the model-asserted semantic class (brief §8b).

The candidate (proposer) names a relation + a verbatim span in EACH of the two records' chunk text +
a rationale; CODE owns the record ids (never free-typed by the model — the 89503 discipline) and injects
them. The proposal is then validated (advisory-on-relation) and grounded by LinkEvents (the judge rules).
The fixed judge inside LinkEvents is a DIFFERENT model from the candidate, by design.
"""

from reliquary_enrichment.multipass.pass_base import ModelClient
from reliquary_enrichment.multipass.parsing import safe_json_object

_LINK_SYSTEM = (
    "Two Enrichment Records from ONE insurance claim file share a specific entity. Propose the single "
    "best cross-record relation between them, if any. Reply with ONLY a JSON object: "
    '{"relation":"<precedes|follows|causes|results_from|corroborates|contradicts|elaborates|same_event|'
    'references, or a new short relation>","a_span":"<verbatim span copied from RECORD A\'s chunk>",'
    '"b_span":"<verbatim span copied from RECORD B\'s chunk>","rationale":"<why>"}. Each span MUST be '
    "copied verbatim from that record's chunk (code locates it). If the two records are NOT genuinely "
    "related, reply {} (no link)."
)


def make_link_proposer(model: ModelClient):
    def propose(rec_a, rec_b, text_a, text_b, anchor: str):
        user = (
            f"SHARED ENTITY: {anchor}\n\n"
            f"RECORD A — chunk text:\n{text_a}\n"
            f"RECORD A — grounded evidence: {rec_a.evidence_span!r}\n\n"
            f"RECORD B — chunk text:\n{text_b}\n"
            f"RECORD B — grounded evidence: {rec_b.evidence_span!r}"
        )
        obj = safe_json_object(model.complete(_LINK_SYSTEM, user)[0]) or {}
        # CODE owns the ids — the model never supplies them (the 89503 discipline / §12).
        obj["record_a"] = rec_a.record_id
        obj["record_b"] = rec_b.record_id
        return obj
    return propose
