from __future__ import annotations

"""Bounded LLM HTTP — a hard per-call deadline so one wedged request can't hang a run.

The first real audition hung for ~2h on an established-but-silent socket to LiteLLM: the
extraction call had no ``max_tokens`` cap, so a slow/streaming generation kept resetting the
read-gap timeout and never returned. The fix is two-fold and used by BOTH the candidate
extractor and the grounding judge:
  * ``max_tokens`` bounds total generation (root cause), and
  * a hard TOTAL wall-clock deadline (``post_json``) backstops any streaming/keepalive that
    a read timeout alone wouldn't catch. On the deadline we raise ``LLMTimeout`` so callers
    SKIP-and-LOG the unit (chunk bounces / proposal bounces) — never kill the whole run.
"""

import concurrent.futures as _futures

import requests

# Sequential probe -> at most a few in-flight at once; a timed-out request's worker keeps
# running until its read timeout fires (a blocking socket read can't be force-cancelled),
# so size the pool with headroom and let leaked workers retire on their own.
_POOL = _futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm_http")


class LLMTimeout(Exception):
    """Raised when a single LLM call exceeds its total wall-clock deadline."""


def post_json(
    url: str,
    payload: dict,
    *,
    connect_timeout: float = 10.0,
    read_timeout: float = 120.0,
    total_deadline: float = 180.0,
) -> dict:
    """POST ``payload`` as JSON and return the parsed response, under a hard total deadline.

    Raises ``LLMTimeout`` if the call exceeds ``total_deadline`` seconds, or
    ``requests.RequestException`` on transport/HTTP errors. ``read_timeout`` still guards
    idle gaps; ``total_deadline`` is the absolute cap regardless of streaming.
    """
    def _do() -> dict:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=(connect_timeout, read_timeout),
        )
        resp.raise_for_status()
        return resp.json()

    future = _POOL.submit(_do)
    try:
        return future.result(timeout=total_deadline)
    except _futures.TimeoutError:
        future.cancel()  # best-effort; the worker retires when its read timeout fires
        raise LLMTimeout(f"call to {url} exceeded the {total_deadline:.0f}s deadline")
