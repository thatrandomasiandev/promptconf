"""Protocol for pluggable prompt store backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PromptBackend(Protocol):
    """Minimal interface for listing and reading versioned prompts.

    ``write`` is optional — backends that are read-only may omit it or raise
    :class:`~promptconf.exceptions.BackendUnavailableError`.
    """

    def list_prompts(self) -> list[str]:
        """Return sorted prompt names available in this backend."""
        ...

    def list_versions(self, name: str) -> list[str]:
        """Return available version labels for ``name``."""
        ...

    def read(self, name: str, version: str) -> str:
        """Return raw file text for ``name`` at ``version`` (including frontmatter)."""
        ...

    def write(self, name: str, version: str, content: str) -> None:
        """Persist ``content`` for ``name``/``version`` (optional on read-only backends)."""
        ...
