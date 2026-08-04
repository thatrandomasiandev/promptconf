"""Include / extends resolution for Jinja prompt templates."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from collections.abc import Callable

from promptconf.exceptions import PromptNotFoundError
from promptconf.meta import parse_frontmatter

try:
    from jinja2 import BaseLoader, TemplateNotFound
except ImportError:  # pragma: no cover - exercised when jinja extra missing
    BaseLoader = object  # type: ignore[assignment,misc]

    class TemplateNotFound(Exception):  # type: ignore[no-redef]
        """Fallback when Jinja2 is not installed."""


class PromptIncludeLoader(BaseLoader):
    """Jinja loader that resolves templates relative to the prompts root.

    Paths in ``{% include %}`` / ``{% extends %}`` are treated as POSIX-style
    paths under ``root`` (e.g. ``partials/foo.txt``). Directory traversal
    outside the root is rejected. Optional YAML frontmatter is stripped from
    loaded sources so includes/extends see template body only.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def get_source(
        self,
        environment: object,
        template: str,
    ) -> tuple[str, str, Callable[[], bool]]:
        path = self.resolve(template)
        if not path.is_file():
            raise TemplateNotFound(template)

        raw = path.read_text(encoding="utf-8")
        _, source = parse_frontmatter(raw)
        mtime = path.stat().st_mtime

        def uptodate() -> bool:
            try:
                return path.stat().st_mtime == mtime
            except OSError:
                return False

        return source, str(path), uptodate

    def resolve(self, template: str) -> Path:
        """Resolve a template name to an absolute path under ``self.root``."""
        if not template or template.startswith(("/", "\\")):
            raise PromptNotFoundError(
                f"Include path must be relative to the prompts root: {template!r}"
            )

        # Normalize to POSIX so Windows separators don't sneak past checks
        rel = PurePosixPath(template.replace("\\", "/"))
        if ".." in rel.parts or rel.is_absolute():
            raise PromptNotFoundError(
                f"Include path escapes prompts root: {template!r}"
            )

        candidate = (self.root / Path(*rel.parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PromptNotFoundError(
                f"Include path escapes prompts root: {template!r}"
            ) from exc

        return candidate

    def list_templates(self) -> list[str]:
        """Return relative POSIX paths of readable template files under root."""
        if not self.root.is_dir():
            return []

        results: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            # Skip usage log / internal dirs
            try:
                rel = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            results.append(rel.as_posix())
        return results
