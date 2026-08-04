"""Filesystem-backed prompt store (default backend)."""

from __future__ import annotations

from pathlib import Path

from promptconf.exceptions import BackendUnavailableError, PromptNotFoundError
from promptconf.loader import (
    SUPPORTED_EXTENSIONS,
    _find_file_for_stem,
    _format_available,
    _resolve_version_path,
    list_prompts as _list_prompts,
    list_versions as _list_versions,
    resolve_root,
    validate_prompt_name,
    validate_prompt_version,
)


class FilesystemBackend:
    """Prompt backend that reads/writes versioned files under a local root.

    Wraps the same discovery and version-resolution rules as
    :func:`promptconf.loader.load`.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = resolve_root(root)

    def list_prompts(self) -> list[str]:
        return _list_prompts(root=self.root)

    def list_versions(self, name: str) -> list[str]:
        validate_prompt_name(name)
        return _list_versions(name, root=self.root)

    def read(self, name: str, version: str) -> str:
        validate_prompt_name(name)
        validate_prompt_version(version)
        prompt_dir = self.root / name
        if not prompt_dir.is_dir():
            raise PromptNotFoundError(
                f"Prompt '{name}' not found under '{self.root}'. "
                f"Available prompts: {_format_available(self.list_prompts())}"
            )
        path, _resolved = _resolve_version_path(prompt_dir, name, version)
        return path.read_text(encoding="utf-8")

    def resolve_path(self, name: str, version: str) -> tuple[Path, str]:
        """Return ``(path, resolved_version)`` for ``name``/``version``."""
        validate_prompt_name(name)
        validate_prompt_version(version)
        prompt_dir = self.root / name
        if not prompt_dir.is_dir():
            raise PromptNotFoundError(
                f"Prompt '{name}' not found under '{self.root}'. "
                f"Available prompts: {_format_available(self.list_prompts())}"
            )
        return _resolve_version_path(prompt_dir, name, version)

    def write(self, name: str, version: str, content: str) -> None:
        validate_prompt_name(name)
        validate_prompt_version(version)
        if version == "latest":
            # Allow writing an explicit latest.* file
            stem = "latest"
        else:
            stem = version

        prompt_dir = self.root / name
        prompt_dir.mkdir(parents=True, exist_ok=True)
        # Prefer .txt; overwrite existing stem with any supported extension
        existing = _find_file_for_stem(prompt_dir, stem)
        target = existing if existing is not None else prompt_dir / f"{stem}.txt"
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS and existing is None:
            target = prompt_dir / f"{stem}.txt"
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise BackendUnavailableError(
                f"Failed to write prompt '{name}' version '{version}': {exc}"
            ) from exc

    def __repr__(self) -> str:
        return f"FilesystemBackend(root={str(self.root)!r})"
