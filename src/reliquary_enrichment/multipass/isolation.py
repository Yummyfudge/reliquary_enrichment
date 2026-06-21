from __future__ import annotations

"""Isolation proof — the prod-untouched evidence the §5 harness records every run.

Rehomed into `multipass/` from the retired `probe/` (codex refactor §13). The harness writes ONLY to a
throwaway probe_<label> schema; these read the PROD enrichment row counts before and after, so each run
proves prod was not mutated — or, if the probe role is even read-denied on prod enrichment, records that
denial as the stronger structural proof (the harness can't read prod, let alone write it).
"""

import psycopg

from reliquary_enrichment.postgres.connection import connect, qualified

_PROD_SCHEMA = "context_reliquary"
_ENRICHMENT_TABLES = ("enrichment_records", "codex_entities", "enrichment_links")


def prod_enrichment_counts() -> dict:
    """Row counts of the PROD enrichment tables for the isolation proof (never None).

    Returns ``{table: count, "_access": "ok"}`` when readable (needs SELECT on the prod enrichment
    tables — see schema/grants.probe_read.sql). If the probe role is permission-denied, returns
    ``{"_access": "permission_denied"}`` — itself proof the harness cannot even READ prod enrichment,
    let alone write it (the wall, stronger). Either way the run records its own isolation evidence
    rather than leaving nulls.
    """
    out: dict = {}
    try:
        with connect() as conn, conn.cursor() as cur:
            for t in _ENRICHMENT_TABLES:
                cur.execute(f"SELECT count(*) AS n FROM {qualified(_PROD_SCHEMA, t)}")
                out[t] = cur.fetchone()["n"]
        out["_access"] = "ok"
        return out
    except psycopg.errors.InsufficientPrivilege:
        return {"_access": "permission_denied"}
    except Exception as exc:  # pragma: no cover - operational
        return {"_access": f"error: {type(exc).__name__}"}


def _isolation_unchanged(before: dict, after: dict) -> bool:
    """True if prod enrichment is provably unchanged: equal counts, or read-denied both times."""
    return before == after
