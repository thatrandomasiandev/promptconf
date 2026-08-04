"""Sandboxed Jinja2 rendering for prompt templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from promptconf.exceptions import PromptFormatError
from promptconf.includes import PromptIncludeLoader
from promptconf.meta import parse_frontmatter

_UNSAFE_ATTR_PREFIXES = ("__", "func_", "f_")
_UNSAFE_ATTR_NAMES = frozenset(
    {
        "mro",
        "gi_frame",
        "gi_code",
        "gi_running",
        "cr_frame",
        "cr_code",
        "ag_frame",
        "ag_code",
        "tb_frame",
        "tb_next",
        "format",
        "format_map",
    }
)


def require_jinja() -> None:
    """Raise a clear ImportError when Jinja2 is not installed."""
    try:
        import jinja2  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Jinja2 is required for engine='jinja'. "
            "Install it with: pip install 'promptconf[jinja]'"
        ) from exc


def create_environment(root: str | Path, *, strict: bool = True):
    """Build a :class:`jinja2.sandbox.SandboxedEnvironment` rooted at ``root``."""
    require_jinja()
    from jinja2.sandbox import SandboxedEnvironment

    loader = PromptIncludeLoader(root)
    env = SandboxedEnvironment(
        loader=loader,
        autoescape=False,
        keep_trailing_newline=True,
        undefined=_undefined_class(strict=strict),
    )
    env.is_safe_attribute = _is_safe_attribute  # type: ignore[method-assign]
    return env


def render_jinja(
    source: str,
    vars: Mapping[str, Any] | None = None,
    *,
    root: str | Path,
    name: str = "<string>",
    strict: bool = True,
) -> str:
    """Render ``source`` with a sandboxed Jinja environment.

    Frontmatter is stripped before rendering. Includes and extends resolve
    relative to ``root``.
    """
    require_jinja()
    from jinja2 import TemplateSyntaxError, UndefinedError
    from jinja2.exceptions import TemplateNotFound
    from jinja2.sandbox import SecurityError

    from promptconf.exceptions import PromptNotFoundError

    _, body = parse_frontmatter(source)
    env = create_environment(root, strict=strict)

    try:
        template = env.from_string(body)
        template.name = name
        return template.render(**dict(vars or {}))
    except SecurityError as exc:
        raise PromptFormatError(f"Unsafe template expression blocked: {exc}") from exc
    except UndefinedError as exc:
        raise PromptFormatError(f"Missing required prompt variable(s): {exc}") from exc
    except TemplateSyntaxError as exc:
        raise PromptFormatError(f"Invalid Jinja template syntax: {exc}") from exc
    except TemplateNotFound as exc:
        raise PromptNotFoundError(f"Included template not found: {exc}") from exc
    except PromptNotFoundError:
        raise
    except PromptFormatError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as format error
        raise PromptFormatError(f"Failed to render Jinja prompt: {exc}") from exc


def compile_template(
    source: str,
    *,
    root: str | Path | None = None,
    name: str = "<string>",
) -> dict[str, Any]:
    """Validate that a template parses without rendering.

    Returns
    -------
    dict
        ``metadata`` (frontmatter), ``body`` (template source after
        frontmatter strip), and ``name``.
    """
    require_jinja()
    from jinja2 import TemplateSyntaxError
    from jinja2.sandbox import SandboxedEnvironment

    metadata, body = parse_frontmatter(source)

    if root is not None:
        env = create_environment(root, strict=True)
    else:
        env = SandboxedEnvironment(
            autoescape=False,
            keep_trailing_newline=True,
        )
        env.is_safe_attribute = _is_safe_attribute  # type: ignore[method-assign]

    try:
        env.parse(body)
    except TemplateSyntaxError as exc:
        raise PromptFormatError(
            f"Invalid Jinja template syntax in {name}: {exc}"
        ) from exc

    return {
        "name": name,
        "metadata": metadata,
        "body": body,
    }


def _undefined_class(*, strict: bool):
    from jinja2 import StrictUndefined, Undefined

    if strict:
        return StrictUndefined

    class SoftUndefined(Undefined):
        """Non-strict undefined that preserves a ``{{ name }}`` placeholder."""

        def __str__(self) -> str:
            return "{{ " + (self._undefined_name or "") + " }}"

        def __iter__(self):
            return iter(())

        def __bool__(self) -> bool:
            return False

    return SoftUndefined


def _is_safe_attribute(obj: object, attr: str, value: object) -> bool:
    """Block dunder / internal attributes that enable sandbox escapes."""
    from jinja2.sandbox import is_internal_attribute

    if attr.startswith(_UNSAFE_ATTR_PREFIXES) or attr in _UNSAFE_ATTR_NAMES:
        return False
    if is_internal_attribute(obj, attr):
        return False
    return True
