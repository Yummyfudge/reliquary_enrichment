from __future__ import annotations

"""Defensive JSON extraction shared by the passes — never raises on bad model output.

Both the direct parse AND the regex-extracted fallback are guarded (the fallback being
unguarded is what crashed the first scout run). Returns a sane empty value instead of raising,
so a single malformed reply degrades that one chunk, not the whole run.
"""

import json
import re


def safe_json_array(raw: str) -> list:
    """Parse a JSON array from text; return [] on anything unparseable (incl. the fallback)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        if not m:
            return []
        try:
            value = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def safe_json_object(raw: str) -> dict | None:
    """Parse a JSON object from text; return None on anything unparseable (incl. the fallback)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not m:
            return None
        try:
            value = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None
