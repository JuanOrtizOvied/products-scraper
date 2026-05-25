"""Shared JSON parsing utilities for classifier and extractor agents."""
from __future__ import annotations

import json
import re
from typing import Any


def strip_fences(text: str) -> str:
    """Remove ```json...``` fences if present."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def try_parse_json(text: str) -> dict[str, Any] | None:
    """Attempt multiple strategies to extract a JSON object from possibly noisy text.

    Returns the parsed dict on first success, or None if all strategies fail.
    """
    text = text.strip()
    # Strategy 1: direct parse
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        return result if isinstance(result, dict) else None

    # Strategy 2: greedy match {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
        else:
            return result if isinstance(result, dict) else None

    # Strategy 3: truncate at last balanced brace
    depth = 0
    last_close = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_close = i
                break
    if last_close > 0:
        first_open = text.find("{")
        if first_open >= 0 and first_open < last_close:
            try:
                result = json.loads(text[first_open : last_close + 1])
            except json.JSONDecodeError:
                pass
            else:
                return result if isinstance(result, dict) else None

    return None
