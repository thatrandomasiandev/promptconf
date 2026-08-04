"""Reusable prompt store bound to a configured root directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from promptconf import loader
from promptconf.loader import EngineName


class PromptStore:
    """Configured prompt loader with a fixed root directory.

    Example
    -------
    >>> store = PromptStore(root="./prompts")
    >>> store.load("classifier", version="v2", vars={"language": "Python"})

    Pass ``backend=`` to use a pluggable :class:`~promptconf.backends.base.PromptBackend`
    (filesystem by default when omitted — same behavior as before).
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        backend: Any | None = None,
    ) -> None:
        self.root = loader.resolve_root(root)
        if backend is None:
            from promptconf.backends.filesystem import FilesystemBackend

            self.backend = FilesystemBackend(root=self.root)
        else:
            self.backend = backend

    def load(
        self,
        name: str,
        version: str = "latest",
        vars: Mapping[str, Any] | None = None,
        *,
        strict: bool = True,
        log: bool = True,
        raw: bool = False,
        engine: EngineName = "format",
        use_cache: bool = False,
        cache: Any | None = None,
        cache_dir: str | Path | None = None,
    ) -> str:
        """Load a prompt relative to this store's root / backend."""
        return loader.load(
            name,
            version=version,
            vars=vars,
            root=self.root,
            strict=strict,
            log=log,
            raw=raw,
            engine=engine,
            backend=self.backend,
            use_cache=use_cache,
            cache=cache,
            cache_dir=cache_dir,
        )

    def compile_prompt(
        self,
        name: str,
        version: str = "latest",
        *,
        engine: EngineName = "jinja",
    ) -> dict[str, Any]:
        """Validate a prompt parses without rendering (dry-run)."""
        return loader.compile_prompt(
            name,
            version=version,
            root=self.root,
            engine=engine,
            backend=self.backend,
        )

    def list_prompts(self) -> list[str]:
        """List prompt names under this store's backend."""
        return list(self.backend.list_prompts())

    def list_versions(self, name: str) -> list[str]:
        """List available versions for ``name`` under this store's backend."""
        return list(self.backend.list_versions(name))

    def __repr__(self) -> str:
        return (
            f"PromptStore(root={str(self.root)!r}, "
            f"backend={type(self.backend).__name__})"
        )
