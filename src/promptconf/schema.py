"""Variable schema declaration and validation for prompts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from promptconf.exceptions import PromptSchemaError
from promptconf.loader import _resolve_version_path, load, resolve_root
from promptconf.meta import parse_frontmatter

_SIMPLE_TYPES = {
    "string": str,
    "str": str,
    "integer": int,
    "int": int,
    "number": (int, float),
    "float": float,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "list": list,
    "object": dict,
    "dict": dict,
    "null": type(None),
}


def load_schema_for(
    name: str,
    version: str = "latest",
    *,
    root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load a variable schema for a prompt version.

    Resolution order:
    1. Sidecar ``{version}.schema.json`` next to the prompt file
    2. Frontmatter ``vars:`` (or ``schema:``) in the prompt body
    """
    root_path = resolve_root(root)
    prompt_dir = root_path / name
    path, resolved_version = _resolve_version_path(prompt_dir, name, version)

    sidecar = prompt_dir / f"{resolved_version}.schema.json"
    if sidecar.is_file():
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        return _normalize_schema(raw)

    # Also accept stem matching the requested version label when latest resolved
    if version != resolved_version:
        alt = prompt_dir / f"{version}.schema.json"
        if alt.is_file():
            raw = json.loads(alt.read_text(encoding="utf-8"))
            return _normalize_schema(raw)

    text = path.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    if "schema" in meta and meta["schema"] is not None:
        return _normalize_schema(meta["schema"])
    if "vars" in meta and meta["vars"] is not None:
        return _normalize_schema(meta["vars"])
    return None


def validate_vars(
    vars: Mapping[str, Any] | None,
    schema: Mapping[str, Any] | None,
    *,
    strict: bool = True,
) -> list[str]:
    """Validate ``vars`` against a schema.

    ``schema`` may be:
    - a simple ``{name: type}`` mapping (``type`` is a string like ``"string"``)
    - a JSON Schema object with ``type: object`` and ``properties`` / ``required``

    Returns a list of human-readable error messages (empty if valid).
    When ``strict=True`` and errors exist, raises :class:`PromptSchemaError`.
    """
    if schema is None:
        return []

    normalized = _normalize_schema(schema)
    provided = dict(vars or {})
    errors: list[str] = []

    required = list(normalized.get("required") or [])
    properties: dict[str, Any] = dict(normalized.get("properties") or {})

    # Simple dict form was normalized into properties; also accept bare dict
    if not properties and _looks_like_simple_type_map(normalized):
        properties = {
            key: _type_to_property(value)
            for key, value in normalized.items()
            if key not in {"type", "properties", "required", "additionalProperties"}
        }
        required = list(properties.keys())

    for key in required:
        if key not in provided:
            errors.append(f"Missing required variable: {key!r}")

    for key, value in provided.items():
        if key not in properties:
            if normalized.get("additionalProperties", True) is False:
                errors.append(f"Unexpected variable: {key!r}")
            continue
        prop = properties[key]
        type_error = _check_type(key, value, prop)
        if type_error:
            errors.append(type_error)

    if strict and errors:
        raise PromptSchemaError("; ".join(errors))
    return errors


def load_validated(
    name: str,
    version: str = "latest",
    vars: Mapping[str, Any] | None = None,
    *,
    root: str | Path | None = None,
    strict: bool = True,
    log: bool = True,
    raw: bool = False,
    schema: Mapping[str, Any] | None = None,
) -> str:
    """Load a prompt after validating ``vars`` against its schema.

    If ``schema`` is omitted, attempts sidecar / frontmatter discovery.
    When no schema is found, behaves like :func:`promptconf.loader.load`.
    """
    resolved_schema = schema if schema is not None else load_schema_for(
        name, version=version, root=root
    )
    validate_vars(vars, resolved_schema, strict=True)

    return load(
        name,
        version=version,
        vars=vars,
        root=root,
        strict=strict,
        log=log,
        raw=raw,
    )


def _normalize_schema(raw: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise PromptSchemaError(f"Schema must be a mapping, got {type(raw).__name__}")

    data = dict(raw)

    # Full JSON Schema object
    if data.get("type") == "object" or "properties" in data:
        properties = dict(data.get("properties") or {})
        required = list(data.get("required") or [])
        return {
            "type": "object",
            "properties": {
                key: _coerce_property(value) for key, value in properties.items()
            },
            "required": required,
            "additionalProperties": data.get("additionalProperties", True),
        }

    # Simple {name: type} map
    if _looks_like_simple_type_map(data):
        properties = {key: _type_to_property(value) for key, value in data.items()}
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
            "additionalProperties": True,
        }

    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": True,
        **data,
    }


def _looks_like_simple_type_map(data: Mapping[str, Any]) -> bool:
    if not data:
        return False
    reserved = {"type", "properties", "required", "additionalProperties"}
    keys = [k for k in data if k not in reserved]
    if not keys:
        return False
    return all(
        isinstance(data[k], str)
        or (isinstance(data[k], Mapping) and "type" in data[k])
        for k in keys
    )


def _type_to_property(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return _coerce_property(value)
    if isinstance(value, str):
        return {"type": value.lower()}
    raise PromptSchemaError(f"Unsupported schema type declaration: {value!r}")


def _coerce_property(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"type": value.lower()}
    if isinstance(value, Mapping):
        return dict(value)
    raise PromptSchemaError(f"Invalid property schema: {value!r}")


def _check_type(key: str, value: Any, prop: Mapping[str, Any]) -> str | None:
    expected = prop.get("type")
    if expected is None:
        return None
    if isinstance(expected, list):
        for option in expected:
            if _matches_type(value, option):
                return None
        return (
            f"Variable {key!r} has type {type(value).__name__}, "
            f"expected one of {expected}"
        )
    if not _matches_type(value, expected):
        return (
            f"Variable {key!r} has type {type(value).__name__}, "
            f"expected {expected}"
        )
    return None


def _matches_type(value: Any, expected: str) -> bool:
    expected_l = str(expected).lower()
    if expected_l == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_l in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    py_type = _SIMPLE_TYPES.get(expected_l)
    if py_type is None:
        return True
    if expected_l in {"boolean", "bool"}:
        return isinstance(value, bool)
    if expected_l in {"string", "str"}:
        return isinstance(value, str)
    return isinstance(value, py_type)
