"""Tolerant JSON extraction for LLM output."""

import json
import re
from typing import Any

from app.core.errors import LLMResponseError

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM reply that should be a single JSON object.

    Tolerates markdown code fences and stray prose around the object.
    Raises LLMResponseError if no valid JSON object can be found.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMResponseError() from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            raise LLMResponseError() from None
    if not isinstance(value, dict):
        raise LLMResponseError()
    return value
