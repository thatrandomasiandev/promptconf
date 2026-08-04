"""Git-like tag, log, and freeze operations for promptconf."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from promptconf.exceptions import PromptNotFoundError
from promptconf.loader import list_prompts, list_versions, load, resolve_root

TAGS_FILENAME = "tags.json"
LOCK_FILENAME = "prompt.lock.json"
USAGE_FILENAME = "usage.jsonl"


def _meta_dir(root: Path) -> Path:
    return root / ".promptconf"


def _tags_path(root: Path) -> Path:
    return _meta_dir(root) / TAGS_FILENAME


def _read_tags(root: Path) -> dict[str, Any]:
    path = _tags_path(root)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _write_tags(root: Path, tags: dict[str, Any]) -> Path:
    meta = _meta_dir(root)
    meta.mkdir(parents=True, exist_ok=True)
    path = _tags_path(root)
    path.write_text(
        json.dumps(tags, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def tag(
    name: str,
    version: str,
    tag_name: str,
    *,
    root: str | Path | None = None,
) -> dict[str, str]:
    """Associate ``tag_name`` with ``name`` at ``version``.

    Writes ``{root}/.promptconf/tags.json``. Returns the stored tag record.
    Validates that the prompt version exists before writing.
    """
    root_path = resolve_root(root)
    available = list_versions(name, root=root_path)
    if version not in available:
        raise PromptNotFoundError(
            f"Version '{version}' not found for prompt '{name}'. "
            f"Available versions: {', '.join(available) if available else '(none)'}"
        )

    record = {"name": name, "version": version}
    tags = _read_tags(root_path)
    tags[tag_name] = record
    _write_tags(root_path, tags)
    return record


def resolve_tag(
    tag_name: str,
    *,
    root: str | Path | None = None,
) -> dict[str, str]:
    """Resolve ``tag_name`` to ``{"name": ..., "version": ...}``.

    Raises :class:`PromptNotFoundError` if the tag is unknown.
    """
    root_path = resolve_root(root)
    tags = _read_tags(root_path)
    if tag_name not in tags:
        known = ", ".join(sorted(tags)) if tags else "(none)"
        raise PromptNotFoundError(
            f"Tag '{tag_name}' not found under '{root_path}'. Known tags: {known}"
        )
    record = tags[tag_name]
    if not isinstance(record, dict) or "name" not in record or "version" not in record:
        raise PromptNotFoundError(
            f"Tag '{tag_name}' has an invalid record in tags.json"
        )
    return {"name": str(record["name"]), "version": str(record["version"])}


def log(
    name: str,
    *,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return usage.jsonl records filtered to prompt ``name``.

    Reads ``{root}/.promptconf/usage.jsonl``. Missing log file yields ``[]``.
    """
    root_path = resolve_root(root)
    log_path = _meta_dir(root_path) / USAGE_FILENAME
    if not log_path.is_file():
        return []

    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("name") == name:
            records.append(record)
    return records


def freeze(*, root: str | Path | None = None) -> dict[str, str]:
    """Pin each prompt to its latest resolved version in ``prompt.lock.json``.

    Writes ``{root}/prompt.lock.json`` mapping prompt name → resolved version
    (``latest.*`` if present, otherwise highest numeric ``vN``).
    Returns the lock mapping.
    """
    root_path = resolve_root(root)
    pins: dict[str, str] = {}

    for name in list_prompts(root=root_path):
        # Resolve via load path machinery: request "latest", inspect resolved stem
        # by reusing list_versions + same preference as loader.
        versions = list_versions(name, root=root_path)
        if "latest" in versions:
            pins[name] = "latest"
        else:
            numeric = [v for v in versions if v.lower().startswith("v") and v[1:].isdigit()]
            if numeric:
                # list_versions already sorts numerically; take last numeric
                pins[name] = numeric[-1]
            elif versions:
                pins[name] = versions[-1]
            else:
                continue

        # Touch-resolve to confirm the pin is loadable (raises if broken)
        load(name, version=pins[name], root=root_path, raw=True, log=False)

    lock_path = root_path / LOCK_FILENAME
    lock_path.write_text(
        json.dumps(pins, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return pins
