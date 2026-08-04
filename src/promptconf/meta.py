"""YAML frontmatter parsing for prompt files."""

from __future__ import annotations

import re
from typing import Any

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?\r?\n)---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)

_BOOLS = {
    "true": True,
    "false": False,
    "yes": True,
    "no": False,
    "on": True,
    "off": False,
}
_NULLS = frozenset({"null", "~", ""})


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML frontmatter from prompt body.

    Recognizes a leading ``---`` fenced block::

        ---
        model: gpt-4
        temperature: 0.2
        vars:
          name: string
        ---
        Hello {{ name }}

    Returns
    -------
    tuple[dict[str, Any], str]
        ``(metadata, body)``. When no frontmatter is present, metadata is
        an empty dict and body is the original text (unchanged).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml = match.group(1)
    body = text[match.end() :]
    metadata = _parse_simple_yaml(raw_yaml)
    return metadata, body


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse a minimal YAML subset used in prompt frontmatter.

    Supports flat ``key: value`` mappings, nested indented mappings,
    strings, ints, floats, bools, nulls, inline lists (``[a, b]``),
    and quoted strings.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"Invalid frontmatter line (expected key: value): {line!r}")

        key, _, value = stripped.partition(":")
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid frontmatter line (empty key): {line!r}")
        value = value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if value == "":
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
        else:
            current[key] = _coerce_scalar(value)

    return root


def _coerce_scalar(value: str) -> Any:
    lower = value.lower()
    if lower in _NULLS:
        return None
    if lower in _BOOLS:
        return _BOOLS[lower]

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(part.strip()) for part in _split_csv(inner)]

    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)

    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", value) or re.fullmatch(
        r"[+-]?\d+[eE][+-]?\d+", value
    ):
        return float(value)

    return value


def _split_csv(text: str) -> list[str]:
    """Split a comma-separated list respecting simple quoted segments."""
    parts: list[str] = []
    current: list[str] = []
    in_quote: str | None = None
    for ch in text:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in {'"', "'"}:
            in_quote = ch
            current.append(ch)
            continue
        if ch == ",":
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current or parts:
        parts.append("".join(current))
    return parts
