"""Search prompt bodies by substring or regular expression."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from promptconf.loader import SUPPORTED_EXTENSIONS, list_prompts, resolve_root


@dataclass(frozen=True)
class SearchHit:
    """A ranked search match against a prompt file."""

    name: str
    version: str
    path: str
    snippet: str
    score: float
    match_start: int
    match_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "snippet": self.snippet,
            "score": self.score,
            "match_start": self.match_start,
            "match_end": self.match_end,
        }


def search(
    query: str,
    root: str | Path | None = None,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    names: Iterable[str] | None = None,
    limit: int | None = None,
    context: int = 40,
) -> list[SearchHit]:
    """Search prompt bodies under ``root``.

    Parameters
    ----------
    query:
        Substring to find, or a regular expression when ``regex=True``.
    regex:
        Interpret ``query`` as a regular expression.
    case_sensitive:
        Match case exactly when ``True``.
    names:
        Optional subset of prompt names to search.
    limit:
        Maximum number of hits to return (best scores first).
    context:
        Characters of surrounding context included in each snippet.

    Returns
    -------
    list[SearchHit]
        Ranked hits (higher score first). Score prefers denser / earlier matches.
    """
    if not query:
        return []

    root_path = resolve_root(root)
    target_names = list(names) if names is not None else list_prompts(root_path)
    flags = 0 if case_sensitive else re.IGNORECASE

    if regex:
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            raise ValueError(f"Invalid search regex: {exc}") from exc
    else:
        pattern = re.compile(re.escape(query), flags)

    hits: list[SearchHit] = []
    for name in target_names:
        prompt_dir = root_path / name
        if not prompt_dir.is_dir():
            continue
        for entry in sorted(prompt_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            text = entry.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                snippet = _make_snippet(text, start, end, context=context)
                score = _score_match(text, start, end, query)
                hits.append(
                    SearchHit(
                        name=name,
                        version=entry.stem,
                        path=str(entry),
                        snippet=snippet,
                        score=score,
                        match_start=start,
                        match_end=end,
                    )
                )

    hits.sort(key=lambda h: (-h.score, h.name, h.version, h.match_start))
    if limit is not None:
        return hits[: max(0, limit)]
    return hits


def _make_snippet(text: str, start: int, end: int, *, context: int) -> str:
    left = max(0, start - context)
    right = min(len(text), end + context)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    chunk = text[left:right].replace("\n", " ")
    return f"{prefix}{chunk}{suffix}"


def _score_match(text: str, start: int, end: int, query: str) -> float:
    """Higher is better: longer matches, earlier offsets, shorter documents."""
    span = max(1, end - start)
    length_bonus = span / max(1, len(query))
    early_bonus = 1.0 - (start / max(1, len(text)))
    density = span / max(1, len(text))
    return (2.0 * length_bonus) + early_bonus + density
