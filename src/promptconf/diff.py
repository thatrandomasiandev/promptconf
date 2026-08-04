"""Unified diffs between prompt versions."""

from __future__ import annotations

import difflib
from pathlib import Path

from promptconf.loader import load, resolve_root


def diff_versions(
    name: str,
    a: str,
    b: str,
    *,
    root: str | Path | None = None,
) -> str:
    """Return a unified diff of prompt ``name`` between versions ``a`` and ``b``.

    Loads both versions as raw text (no variable substitution, no usage logging).
    Diff headers use ``{name}/{version}`` labels.
    """
    root_path = resolve_root(root)
    text_a = load(name, version=a, root=root_path, raw=True, log=False)
    text_b = load(name, version=b, root=root_path, raw=True, log=False)

    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    return "".join(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"{name}/{a}",
            tofile=f"{name}/{b}",
            lineterm="\n",
        )
    )
