from __future__ import annotations

"""Postgres connection — reuses the spine's cert-auth config, env-overridable for tests.

Prod defaults come from ``context_reliquary.config`` (cert-auth to llm-db, the SAME DB the
runtime app role already uses to read claim_chunks). ``RELIQUARY_ENRICHMENT_PG*`` env vars
override every field so the ephemeral scratch Postgres (password auth, sslmode=disable) can
be targeted in integration tests — the engineer never points this at prod.
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

try:  # the spine is co-installed in the runtime env; fall back to env-only for tests.
    from context_reliquary import config as _cr
    _PROD = {
        "host": _cr.POSTGRES_HOST,
        "port": _cr.POSTGRES_PORT,
        "dbname": _cr.POSTGRES_DBNAME,
        "user": _cr.POSTGRES_USER,
        "sslmode": _cr.POSTGRES_SSLMODE,
        "sslrootcert": _cr.POSTGRES_SSLROOTCERT or None,
        "sslcert": _cr.POSTGRES_SSLCERT or None,
        "sslkey": _cr.POSTGRES_SSLKEY or None,
    }
except Exception:  # pragma: no cover - exercised only when spine is absent
    _PROD = {"host": "192.168.1.53", "port": 5432, "dbname": "context_reliquary",
             "user": "context_reliquary_app", "sslmode": "verify-full"}


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
        for k in ("sslrootcert", "sslcert", "sslkey"):
            v = _PROD.get(k)
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
