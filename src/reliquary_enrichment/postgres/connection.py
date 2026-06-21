from __future__ import annotations

"""Postgres connection — reliquary_enrichment's OWN cert-auth config, env-overridable for tests.

Connection defaults are this context's own — NO cross-context import (§12/§13: a needed thing moves
IN, never imports across the boundary). ``RELIQUARY_ENRICHMENT_PG*`` env vars override every field (the
probe role's creds + its own client cert), so real runs are fully env-driven; the bare defaults below
are only the env-unset prod fallback. The ephemeral scratch Postgres (password auth, sslmode=disable)
is targeted via the same env vars in integration tests — the engineer never points this at prod. The
DB is the llm-db that also holds the read-only claim_chunks corpus.
"""

import os
import re
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

# Default schema for enrichment WRITES. The probe overrides this per run to a throwaway
# probe_<label> schema (isolation); claim_chunks reads always stay in context_reliquary.
DEFAULT_WRITE_SCHEMA: str = "context_reliquary"

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def qualified(schema: str, table: str) -> str:
    """Return a validated ``schema.table`` identifier.

    Schema/table names are operator-controlled (never model input), but we still validate
    them against a strict identifier pattern so a malformed schema (e.g. a probe label)
    can never inject SQL. Raises ValueError on anything that isn't a plain lowercase ident.
    """
    for part in (schema, table):
        if not _IDENT.match(part):
            raise ValueError(f"invalid SQL identifier {part!r} (expected ^[a-z_][a-z0-9_]*$)")
    return f"{schema}.{table}"

# reliquary_enrichment's OWN connection defaults — no cross-context import (§12/§13). Real runs set
# RELIQUARY_ENRICHMENT_PG* (host/port/db/user/sslmode + the probe role's own cert paths) which override
# every field; these are only the env-unset prod fallback (cert paths then come from env alone).
_PROD = {
    "host": "192.168.1.53", "port": 5432, "dbname": "context_reliquary",
    "user": "context_reliquary_app", "sslmode": "verify-full",
}


def connection_kwargs() -> dict:
    """Build psycopg connect kwargs: prod cert-auth defaults, overridden by env vars."""
    env = os.getenv
    kwargs: dict = {
        "host": env("RELIQUARY_ENRICHMENT_PGHOST", _PROD["host"]),
        "port": int(env("RELIQUARY_ENRICHMENT_PGPORT", str(_PROD["port"]))),
        "dbname": env("RELIQUARY_ENRICHMENT_PGDATABASE", _PROD["dbname"]),
        "user": env("RELIQUARY_ENRICHMENT_PGUSER", _PROD["user"]),
        "sslmode": env("RELIQUARY_ENRICHMENT_PGSSLMODE", _PROD.get("sslmode", "prefer")),
    }
    password = env("RELIQUARY_ENRICHMENT_PGPASSWORD")
    if password:  # scratch/password auth
        kwargs["password"] = password
    if kwargs["sslmode"] not in ("disable", "allow", "prefer"):
        # cert paths: RELIQUARY_ENRICHMENT_* env wins (the probe role uses its OWN client
        # cert, distinct from the app role's), else fall back to the app config defaults.
        env_certs = {
            "sslrootcert": env("RELIQUARY_ENRICHMENT_PGSSLROOTCERT"),
            "sslcert": env("RELIQUARY_ENRICHMENT_PGSSLCERT"),
            "sslkey": env("RELIQUARY_ENRICHMENT_PGSSLKEY"),
        }
        for k in ("sslrootcert", "sslcert", "sslkey"):
            v = env_certs[k] or _PROD.get(k)
            if v:
                kwargs[k] = v
    return kwargs


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Yield an autocommit, dict-row psycopg connection; closes on exit."""
    conn = psycopg.connect(autocommit=True, row_factory=dict_row, **connection_kwargs())
    try:
        yield conn
    finally:
        conn.close()
