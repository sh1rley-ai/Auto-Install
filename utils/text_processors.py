"""
Text Processing Utilities
Extracts structured blocks from LLM output shared by the Planner / Executor / Verifier.
"""

import json
import re
from typing import Any


def extract_tagged_json(text: str, tag: str) -> Any:
    """Parse the JSON payload wrapped in <tag>...</tag> from an LLM response.

    Only the first matching block is used. Raises ValueError when the tag is
    missing or the payload is not valid JSON (json.JSONDecodeError is a
    ValueError subclass), so callers can handle both cases with one except.
    """
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text or "", re.DOTALL)
    if not match:
        raise ValueError(f"no <{tag}> block found in LLM output")
    return json.loads(match.group(1).strip())
