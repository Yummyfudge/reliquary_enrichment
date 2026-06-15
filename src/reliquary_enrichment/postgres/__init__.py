"""Postgres implementations of the store protocols + the Fragment reader.

Concrete persistence against the `context_reliquary` schema (beside claim_chunks). The
tools depend on the protocols in ``stores.py`` / ``grounding.fragments``; these are the
runtime bindings. Connection settings reuse the spine's cert-auth pattern.
"""
