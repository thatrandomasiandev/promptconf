"""Prompt discovery, version resolution, and template formatting."""

from __future__ import annotations

import os
import re
from pathlib import Path
from string import Formatter
from typing import Any, Literal, Mapping

from promptconf.exceptions import (
    PromptFormatError,
    PromptNotFoundError,
    PromptSizeError,
    ValidationError,
)
from promptconf.logging import append_usage_log
from promptconf.meta import parse_frontmatter

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".txt", ".md", ".prompt")
DEFAULT_ROOT_ENV = "PROMPTCONF_ROOT"
DEFAULT_ROOT_NAME = "prompts"
# Soft cap on on-disk prompt size (bytes) before load/compile refuse to read.
MAX_PROMPT_BYTES = 1_048_576  # 1 MiB
EngineName = Literal["format", "jinja"]

_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)


class _MissingDefault(dict[str, Any]):
    """Mapping that preserves ``{key}`` placeholders for missing keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def resolve_root(root: str | Path | None = None) -> Path:
    """Resolve the prompts root directory.

    Precedence: explicit ``root`` → ``PROMPTCONF_ROOT`` env → ``./prompts``.
    """
    if root is not None:
        return Path(root).expanduser().resolve()

    env_root = os.environ.get(DEFAULT_ROOT_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()

    return (Path.cwd() / DEFAULT_ROOT_NAME).resolve()


def list_prompts(root: str | Path | None = None) -> list[str]:
    """Return sorted prompt names (subdirectories under the root)."""
    root_path = resolve_root(root)
    if not root_path.is_dir():
        return []

    return sorted(
        entry.name
        for entry in root_path.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def list_versions(name: str, root: str | Path | None = None) -> list[str]:
    """Return available version labels for ``name``, sorted sensibly.

    Numeric ``vN`` versions sort ascending; ``latest`` (if present) is last.
    """
    validate_prompt_name(name)
    root_path = resolve_root(root)
    prompt_dir = root_path / name
    if not prompt_dir.is_dir():
        raise PromptNotFoundError(
            f"Prompt '{name}' not found under '{root_path}'. "
            f"Available prompts: {_format_available(list_prompts(root_path))}"
        )

    versions: set[str] = set()
    for entry in prompt_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        versions.add(entry.stem)

    return _sort_versions(versions)


def load(
    name: str,
    version: str = "latest",
    vars: Mapping[str, Any] | None = None,
    *,
    root: str | Path | None = None,
    strict: bool = True,
    log: bool = True,
    raw: bool = False,
    engine: EngineName = "format",
    backend: Any | None = None,
    use_cache: bool = False,
    cache: Any | None = None,
    cache_dir: str | Path | None = None,
    max_bytes: int | None = None,
) -> str:
    """Load and optionally format a versioned prompt file.

    Parameters
    ----------
    name:
        Prompt directory name under the root (e.g. ``"classifier"``).
    version:
        Version label such as ``"v2"`` or ``"latest"``.
        ``"latest"`` prefers ``latest.*`` if present, otherwise the highest ``vN``.
    vars:
        Substitution values. For ``engine="format"`` these fill ``{placeholder}``
        fields (``str.format_map`` style). For ``engine="jinja"`` they become
        Jinja context variables (``{{ var }}``, ``{% if %}``, macros, etc.).
    root:
        Prompts root directory. Defaults to ``PROMPTCONF_ROOT`` or ``./prompts``.
    strict:
        If ``True`` (default), missing placeholders raise :class:`PromptFormatError`.
        If ``False``, missing placeholders are left unchanged in the output.
    log:
        If ``True`` (default), append a JSONL usage line under
        ``{root}/.promptconf/usage.jsonl`` (keys only, never values).
    raw:
        If ``True``, skip variable formatting and return file body as-is
        (frontmatter is still stripped).
    engine:
        ``"format"`` (default, backward compatible) or ``"jinja"`` (requires
        the ``[jinja]`` extra).
    backend:
        Optional :class:`~promptconf.backends.base.PromptBackend`. When set,
        prompt text is read via ``backend.read`` instead of the local filesystem
        layout under ``root`` (``root`` is still used for usage logging).
    use_cache:
        When ``True``, use a content-hash :class:`~promptconf.cache.CompileCache`
        keyed by source content + engine + sorted vars.
    cache:
        Optional :class:`~promptconf.cache.CompileCache` instance.
    cache_dir:
        Directory for a default cache when ``use_cache=True`` and ``cache`` is
        omitted (defaults to ``{root}/.promptconf/cache``).
    max_bytes:
        Optional override for :data:`MAX_PROMPT_BYTES`. Files larger than this
        raise :class:`PromptSizeError`.

    Returns
    -------
    str
        The loaded (and possibly formatted) prompt text.
    """
    if engine not in ("format", "jinja"):
        raise ValueError(f"Unsupported engine {engine!r}; expected 'format' or 'jinja'")

    validate_prompt_name(name)
    validate_prompt_version(version)

    root_path = resolve_root(root)
    text, path, resolved_version = _read_prompt_text(
        name,
        version,
        root_path=root_path,
        backend=backend,
        max_bytes=max_bytes,
    )

    if use_cache:
        rendered = _load_with_cache(
            name=name,
            version=version,
            resolved_version=resolved_version,
            path=path,
            text=text,
            vars=vars,
            root_path=root_path,
            strict=strict,
            raw=raw,
            engine=engine,
            cache=cache,
            cache_dir=cache_dir,
        )
    else:
        rendered = _render_text(
            text,
            vars=vars,
            root_path=root_path,
            name=name,
            resolved_version=resolved_version,
            strict=strict,
            raw=raw,
            engine=engine,
        )

    if log:
        append_usage_log(
            root_path,
            name=name,
            version=version,
            resolved_version=resolved_version,
            path=path,
            var_keys=sorted((vars or {}).keys()),
        )

    return rendered


def compile_prompt(
    name: str,
    version: str = "latest",
    *,
    root: str | Path | None = None,
    engine: EngineName = "jinja",
    backend: Any | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Dry-run: resolve a prompt and validate it parses without rendering.

    For ``engine="jinja"``, the template is parsed by Jinja (syntax check only).
    For ``engine="format"``, format fields are scanned for structural errors.

    Returns
    -------
    dict
        Keys include ``name``, ``version``, ``resolved_version``, ``path``,
        ``engine``, ``metadata`` (frontmatter), and ``body``.
    """
    if engine not in ("format", "jinja"):
        raise ValueError(f"Unsupported engine {engine!r}; expected 'format' or 'jinja'")

    validate_prompt_name(name)
    validate_prompt_version(version)

    root_path = resolve_root(root)
    text, path, resolved_version = _read_prompt_text(
        name,
        version,
        root_path=root_path,
        backend=backend,
        max_bytes=max_bytes,
    )
    metadata, body = parse_frontmatter(text)
    logical_name = f"{name}/{resolved_version}"

    if engine == "jinja":
        from promptconf.template import compile_template

        compile_template(text, root=root_path, name=logical_name)
    else:
        try:
            list(Formatter().parse(body))
        except ValueError as exc:
            raise PromptFormatError(
                f"Invalid format template in {logical_name}: {exc}"
            ) from exc

    return {
        "name": name,
        "version": version,
        "resolved_version": resolved_version,
        "path": str(path),
        "engine": engine,
        "metadata": metadata,
        "body": body,
    }


def validate_prompt_name(name: str) -> None:
    """Raise :class:`ValidationError` for empty or structurally invalid names."""
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Prompt name must be a non-empty string")
    if "\x00" in name:
        raise ValidationError(f"Prompt name must not contain null bytes: {name!r}")
    if "/" in name or "\\" in name or name.strip() in {".", ".."} or ".." in name.split("/"):
        raise ValidationError(f"Invalid prompt name: {name!r}")


def validate_prompt_version(version: str) -> None:
    """Raise :class:`ValidationError` for empty or traversal version labels."""
    if not isinstance(version, str) or not version.strip():
        raise ValidationError("Prompt version must be a non-empty string")
    if "\x00" in version:
        raise ValidationError(f"Version label must not contain null bytes: {version!r}")
    normalized = version.replace("\\", "/")
    if (
        "/" in normalized
        or version.strip() in {".", ".."}
        or ".." in normalized.split("/")
    ):
        raise ValidationError(
            f"Version label must be a single file stem "
            f"(no path separators or '..'): {version!r}"
        )


def _read_prompt_text(
    name: str,
    version: str,
    *,
    root_path: Path,
    backend: Any | None,
    max_bytes: int | None = None,
) -> tuple[str, Path, str]:
    """Return ``(raw_text, path, resolved_version)``."""
    limit = MAX_PROMPT_BYTES if max_bytes is None else max_bytes
    if limit < 0:
        raise ValidationError(f"max_bytes must be non-negative, got {limit!r}")

    if backend is not None:
        text = backend.read(name, version)
        if len(text.encode("utf-8")) > limit:
            raise PromptSizeError(
                f"Prompt content exceeds max size of {limit} bytes "
                f"({len(text.encode('utf-8'))} bytes)"
            )
        if hasattr(backend, "resolve_path"):
            path, resolved_version = backend.resolve_path(name, version)
            return text, Path(path), resolved_version
        # Best-effort path for logging when backend has no resolve_path
        return text, Path(str(getattr(backend, "root", root_path))) / name / version, version

    prompt_dir = root_path / name
    if not prompt_dir.is_dir():
        raise PromptNotFoundError(
            f"Prompt '{name}' not found under '{root_path}'. "
            f"Available prompts: {_format_available(list_prompts(root_path))}"
        )
    path, resolved_version = _resolve_version_path(prompt_dir, name, version)

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PromptNotFoundError(f"Cannot read prompt file: {path}") from exc
    if size > limit:
        raise PromptSizeError(
            f"Prompt file exceeds max size of {limit} bytes "
            f"({size} bytes): {path}"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PromptFormatError(f"Prompt file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise PromptNotFoundError(f"Cannot read prompt file: {path}") from exc

    return text, path, resolved_version


def _render_text(
    text: str,
    *,
    vars: Mapping[str, Any] | None,
    root_path: Path,
    name: str,
    resolved_version: str,
    strict: bool,
    raw: bool,
    engine: EngineName,
) -> str:
    _, body = parse_frontmatter(text)
    if raw:
        return body
    if engine == "jinja":
        from promptconf.template import render_jinja

        return render_jinja(
            text,
            vars,
            root=root_path,
            name=f"{name}/{resolved_version}",
            strict=strict,
        )
    return _format_prompt(body, vars or {}, strict=strict)


def _load_with_cache(
    *,
    name: str,
    version: str,
    resolved_version: str,
    path: Path,
    text: str,
    vars: Mapping[str, Any] | None,
    root_path: Path,
    strict: bool,
    raw: bool,
    engine: EngineName,
    cache: Any | None,
    cache_dir: str | Path | None,
) -> str:
    from promptconf.cache import CompileCache, default_cache_dir

    active: CompileCache
    if cache is not None:
        active = cache
    else:
        active = CompileCache(cache_dir if cache_dir is not None else default_cache_dir(root_path))

    key = active.cache_key(
        content=text,
        engine=engine,
        vars=vars,
        name=name,
        version=resolved_version,
    )
    hit = active.get(key)
    if hit is not None:
        return hit

    rendered = _render_text(
        text,
        vars=vars,
        root_path=root_path,
        name=name,
        resolved_version=resolved_version,
        strict=strict,
        raw=raw,
        engine=engine,
    )
    active.put(
        key,
        rendered,
        meta={
            "name": name,
            "version": version,
            "resolved_version": resolved_version,
            "path": str(path),
            "engine": engine,
        },
    )
    return rendered


def _resolve_version_path(
    prompt_dir: Path,
    name: str,
    version: str,
) -> tuple[Path, str]:
    """Resolve ``version`` to a concrete file path and stem label."""
    available = list_versions(name, root=prompt_dir.parent)

    if version == "latest":
        latest_path = _find_file_for_stem(prompt_dir, "latest")
        if latest_path is not None:
            return latest_path, "latest"

        numeric = [v for v in available if _VERSION_RE.match(v)]
        if not numeric:
            raise PromptNotFoundError(
                f"No 'latest' or versioned prompt file for '{name}' in '{prompt_dir}'. "
                f"Available versions: {_format_available(available)}"
            )
        best = max(numeric, key=_version_number)
        path = _find_file_for_stem(prompt_dir, best)
        assert path is not None
        return path, best

    path = _find_file_for_stem(prompt_dir, version)
    if path is None:
        raise PromptNotFoundError(
            f"Version '{version}' not found for prompt '{name}' in '{prompt_dir}'. "
            f"Available versions: {_format_available(available)}"
        )
    return path, version


def _find_file_for_stem(prompt_dir: Path, stem: str) -> Path | None:
    """Find a prompt file by stem, preferring extension order in SUPPORTED_EXTENSIONS."""
    for ext in SUPPORTED_EXTENSIONS:
        candidate = prompt_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate

    # Case-insensitive fallback for stem match with supported extensions
    stem_lower = stem.lower()
    matches = [
        entry
        for entry in prompt_dir.iterdir()
        if entry.is_file()
        and entry.stem.lower() == stem_lower
        and entry.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not matches:
        return None
    # Prefer canonical extension order
    ext_rank = {ext: i for i, ext in enumerate(SUPPORTED_EXTENSIONS)}
    matches.sort(key=lambda p: ext_rank.get(p.suffix.lower(), len(ext_rank)))
    return matches[0]


def _format_prompt(
    template: str,
    vars: Mapping[str, Any],
    *,
    strict: bool,
) -> str:
    """Apply ``str.format_map``-style substitution with clear errors."""
    if strict:
        missing = _missing_fields(template, vars)
        if missing:
            raise PromptFormatError(
                "Missing required prompt variable(s): "
                + ", ".join(repr(m) for m in missing)
                + f". Provided: {_format_available(sorted(vars.keys()))}"
            )
        try:
            return template.format_map(dict(vars))
        except (KeyError, ValueError, IndexError) as exc:
            raise PromptFormatError(f"Failed to format prompt: {exc}") from exc

    try:
        return template.format_map(_MissingDefault(vars))
    except (ValueError, IndexError) as exc:
        raise PromptFormatError(f"Failed to format prompt: {exc}") from exc


def _missing_fields(template: str, vars: Mapping[str, Any]) -> list[str]:
    """Return format field names present in ``template`` but absent from ``vars``."""
    missing: list[str] = []
    seen: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if not field_name:
            continue
        # Support dotted/indexed names by checking the root key
        root_key = field_name.split(".")[0].split("[")[0]
        if root_key not in vars and root_key not in seen:
            missing.append(root_key)
            seen.add(root_key)
    return missing


def _version_number(label: str) -> int:
    match = _VERSION_RE.match(label)
    if not match:
        return -1
    return int(match.group(1))


def _sort_versions(versions: set[str]) -> list[str]:
    numeric = sorted(
        (v for v in versions if _VERSION_RE.match(v)),
        key=_version_number,
    )
    others = sorted(v for v in versions if not _VERSION_RE.match(v) and v != "latest")
    result = numeric + others
    if "latest" in versions:
        result.append("latest")
    return result


def _format_available(items: list[str]) -> str:
    if not items:
        return "(none)"
    return ", ".join(items)
