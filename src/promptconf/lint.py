"""Static lint rules for prompt text files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any, Iterable, Mapping, Sequence

from promptconf.loader import SUPPORTED_EXTENSIONS, list_prompts, resolve_root

Severity = str  # "error" | "warning"

_JSON_MODE_HINT_RE = re.compile(
    r"(?i)\b("
    r"json\s*mode|return\s+(only\s+)?json|respond\s+(only\s+)?(?:in\s+|with\s+)?json|"
    r"output\s+(only\s+)?json|as\s+json|valid\s+json|json\s+object|json\s+array"
    r")\b"
)


@dataclass(frozen=True)
class LintIssue:
    """A single lint finding."""

    rule: str
    message: str
    severity: Severity = "warning"
    name: str | None = None
    version: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
            "name": self.name,
            "version": self.version,
            "path": self.path,
        }


@dataclass
class LintRules:
    """Configurable lint rules for prompt text.

    Parameters
    ----------
    max_chars:
        If set, texts longer than this emit an error.
    banned_phrases:
        Substrings (case-insensitive) that must not appear.
    require_placeholders:
        Placeholder names that must appear as ``{name}`` in the text.
    no_trailing_whitespace:
        Flag lines that end with whitespace (excluding the final newline).
    json_mode_hint:
        If ``True``, warn when JSON-output language is detected without
        an explicit structured-output cue strength (informational).
        If ``"require"``, error when no JSON-mode hint is found.
        If ``"forbid"``, error when a JSON-mode hint is found.
        If ``False`` / ``None``, skip the rule.
    """

    max_chars: int | None = None
    banned_phrases: Sequence[str] = field(default_factory=tuple)
    require_placeholders: Sequence[str] = field(default_factory=tuple)
    no_trailing_whitespace: bool = True
    json_mode_hint: bool | str | None = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> LintRules:
        if not raw:
            return cls()
        return cls(
            max_chars=raw.get("max_chars"),
            banned_phrases=tuple(raw.get("banned_phrases") or ()),
            require_placeholders=tuple(raw.get("require_placeholders") or ()),
            no_trailing_whitespace=bool(raw.get("no_trailing_whitespace", True)),
            json_mode_hint=raw.get("json_mode_hint", False),
        )


DEFAULT_RULES = LintRules()


def lint_prompt(
    text: str,
    rules: LintRules | Mapping[str, Any] | None = None,
    *,
    name: str | None = None,
    version: str | None = None,
    path: str | Path | None = None,
) -> list[LintIssue]:
    """Lint a single prompt body and return findings."""
    resolved = (
        rules
        if isinstance(rules, LintRules)
        else LintRules.from_mapping(rules)
    )
    path_str = str(path) if path is not None else None
    issues: list[LintIssue] = []

    if resolved.max_chars is not None and len(text) > resolved.max_chars:
        issues.append(
            LintIssue(
                rule="max_chars",
                message=(
                    f"Prompt length {len(text)} exceeds max_chars={resolved.max_chars}"
                ),
                severity="error",
                name=name,
                version=version,
                path=path_str,
            )
        )

    lowered = text.lower()
    for phrase in resolved.banned_phrases:
        if phrase.lower() in lowered:
            issues.append(
                LintIssue(
                    rule="banned_phrases",
                    message=f"Banned phrase present: {phrase!r}",
                    severity="error",
                    name=name,
                    version=version,
                    path=path_str,
                )
            )

    present = _placeholder_names(text)
    for required in resolved.require_placeholders:
        if required not in present:
            issues.append(
                LintIssue(
                    rule="require_placeholders",
                    message=f"Required placeholder missing: {{{required}}}",
                    severity="error",
                    name=name,
                    version=version,
                    path=path_str,
                )
            )

    if resolved.no_trailing_whitespace:
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line != line.rstrip(" \t"):
                issues.append(
                    LintIssue(
                        rule="no_trailing_whitespace",
                        message=f"Trailing whitespace on line {lineno}",
                        severity="warning",
                        name=name,
                        version=version,
                        path=path_str,
                    )
                )

    hint_mode = resolved.json_mode_hint
    if hint_mode:
        has_hint = bool(_JSON_MODE_HINT_RE.search(text))
        if hint_mode is True:
            if has_hint:
                issues.append(
                    LintIssue(
                        rule="json_mode_hint",
                        message="JSON-mode language detected; ensure structured output is intended",
                        severity="warning",
                        name=name,
                        version=version,
                        path=path_str,
                    )
                )
        elif isinstance(hint_mode, str):
            mode = hint_mode.lower().strip()
            if mode == "require" and not has_hint:
                issues.append(
                    LintIssue(
                        rule="json_mode_hint",
                        message="Expected a JSON-mode hint but none was found",
                        severity="error",
                        name=name,
                        version=version,
                        path=path_str,
                    )
                )
            elif mode == "forbid" and has_hint:
                issues.append(
                    LintIssue(
                        rule="json_mode_hint",
                        message="JSON-mode hint is forbidden by lint rules",
                        severity="error",
                        name=name,
                        version=version,
                        path=path_str,
                    )
                )
            elif mode not in {"require", "forbid"} and has_hint:
                issues.append(
                    LintIssue(
                        rule="json_mode_hint",
                        message="JSON-mode language detected; ensure structured output is intended",
                        severity="warning",
                        name=name,
                        version=version,
                        path=path_str,
                    )
                )

    return issues


def lint_all(
    root: str | Path | None = None,
    rules: LintRules | Mapping[str, Any] | None = None,
    *,
    names: Iterable[str] | None = None,
) -> list[LintIssue]:
    """Lint every supported prompt file under ``root``."""
    root_path = resolve_root(root)
    target_names = list(names) if names is not None else list_prompts(root_path)
    issues: list[LintIssue] = []

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
            issues.extend(
                lint_prompt(
                    text,
                    rules=rules,
                    name=name,
                    version=entry.stem,
                    path=entry,
                )
            )
    return issues


def _placeholder_names(text: str) -> set[str]:
    names: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(text):
        if not field_name:
            continue
        root_key = field_name.split(".")[0].split("[")[0]
        if root_key:
            names.add(root_key)
    return names
