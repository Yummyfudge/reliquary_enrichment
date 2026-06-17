from __future__ import annotations

"""Unit tests for the isolation-proof helpers (no DB)."""

import psycopg

import reliquary_enrichment.probe.cli as cli


class _Cur:
    def execute(self, *a, **k):
        raise psycopg.errors.InsufficientPrivilege("permission denied for table enrichment_records")
    def fetchone(self):
        return {"n": 0}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _Conn:
    def cursor(self):
        return _Cur()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_prod_counts_permission_denied_is_recorded(monkeypatch):
    # The wall: probe role can't read prod enrichment -> recorded as proof, never None.
    monkeypatch.setattr(cli, "connect", lambda: _Conn())
    assert cli.prod_enrichment_counts() == {"_access": "permission_denied"}


def test_isolation_unchanged_logic():
    denied = {"_access": "permission_denied"}
    assert cli._isolation_unchanged(denied, denied) is True            # structurally unchanged
    ok5 = {"enrichment_records": 5, "_access": "ok"}
    assert cli._isolation_unchanged(ok5, dict(ok5)) is True            # count-verified equal
    assert cli._isolation_unchanged(ok5, {"enrichment_records": 6, "_access": "ok"}) is False  # breach
