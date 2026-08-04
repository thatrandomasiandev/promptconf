"""Tests for Jinja templating, includes/extends, frontmatter, and compile_prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

import promptconf
from promptconf import PromptFormatError, PromptNotFoundError, parse_frontmatter
from promptconf.includes import PromptIncludeLoader
from promptconf.template import compile_template, render_jinja, require_jinja


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def jinja_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    _write(
        root,
        "partials/greeting.txt",
        "Greetings, {{ name }}!",
    )
    _write(
        root,
        "layouts/base.txt",
        "HEADER\n{% block content %}DEFAULT{% endblock %}\nFOOTER",
    )
    _write(
        root,
        "agent/v1.txt",
        "---\nmodel: gpt-4\ntemperature: 0.2\n---\n"
        "Hello {{ name }}\n"
        "{% if premium %}VIP{% else %}standard{% endif %}\n"
        "{% for item in items %}- {{ item }}\n{% endfor %}",
    )
    _write(
        root,
        "agent/v2.txt",
        '{% include "partials/greeting.txt" %}\n'
        "Done.",
    )
    _write(
        root,
        "agent/v3.txt",
        '{% extends "layouts/base.txt" %}\n'
        "{% block content %}Body for {{ name }}{% endblock %}",
    )
    _write(
        root,
        "macros/v1.txt",
        "{% macro stamp(label) %}<{{ label }}>{% endmacro %}\n"
        "{{ stamp(name) }}",
    )
    return root


class TestFrontmatter:
    def test_parse_frontmatter_basic(self) -> None:
        text = "---\nmodel: gpt-4\ntemperature: 0.2\n---\nHello {{ name }}\n"
        meta, body = parse_frontmatter(text)
        assert meta == {"model": "gpt-4", "temperature": 0.2}
        assert body == "Hello {{ name }}\n"

    def test_parse_frontmatter_absent(self) -> None:
        meta, body = parse_frontmatter("plain text")
        assert meta == {}
        assert body == "plain text"

    def test_parse_types_and_lists(self) -> None:
        text = "---\nenabled: true\ntags: [a, b]\nnote: null\n---\nbody"
        meta, body = parse_frontmatter(text)
        assert meta["enabled"] is True
        assert meta["tags"] == ["a", "b"]
        assert meta["note"] is None
        assert body == "body"

    def test_format_engine_strips_frontmatter(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(root, "greeter/v1.txt", "---\nmodel: x\n---\nHello, {name}!")
        result = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=root,
            log=False,
            engine="format",
        )
        assert result == "Hello, Ada!"
        assert "model" not in result


class TestJinjaEngine:
    def test_jinja_vars_if_for(self, jinja_root: Path) -> None:
        result = promptconf.load(
            "agent",
            version="v1",
            engine="jinja",
            vars={"name": "Ada", "premium": True, "items": ["a", "b"]},
            root=jinja_root,
            log=False,
        )
        assert "Hello Ada" in result
        assert "VIP" in result
        assert "- a" in result
        assert "- b" in result
        assert "model" not in result
        assert "---" not in result

    def test_jinja_include(self, jinja_root: Path) -> None:
        result = promptconf.load(
            "agent",
            version="v2",
            engine="jinja",
            vars={"name": "Bob"},
            root=jinja_root,
            log=False,
        )
        assert result == "Greetings, Bob!\nDone."

    def test_jinja_extends_blocks(self, jinja_root: Path) -> None:
        result = promptconf.load(
            "agent",
            version="v3",
            engine="jinja",
            vars={"name": "Cara"},
            root=jinja_root,
            log=False,
        )
        assert result == "HEADER\nBody for Cara\nFOOTER"

    def test_jinja_macros(self, jinja_root: Path) -> None:
        result = promptconf.load(
            "macros",
            version="v1",
            engine="jinja",
            vars={"name": "X"},
            root=jinja_root,
            log=False,
        )
        assert result.strip() == "<X>"

    def test_strict_undefined_raises(self, jinja_root: Path) -> None:
        with pytest.raises(PromptFormatError, match="Missing required"):
            promptconf.load(
                "agent",
                version="v2",
                engine="jinja",
                vars={},
                root=jinja_root,
                log=False,
                strict=True,
            )

    def test_non_strict_leaves_placeholder(self, jinja_root: Path) -> None:
        result = promptconf.load(
            "agent",
            version="v2",
            engine="jinja",
            vars={},
            root=jinja_root,
            log=False,
            strict=False,
        )
        assert "{{ name }}" in result

    def test_default_engine_remains_format(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(root, "plain/v1.txt", "Hi {name}")
        result = promptconf.load(
            "plain",
            version="v1",
            vars={"name": "Zed"},
            root=root,
            log=False,
        )
        assert result == "Hi Zed"

    def test_invalid_syntax_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(root, "bad/v1.txt", "{% if true %}oops")
        with pytest.raises(PromptFormatError, match="syntax"):
            promptconf.load(
                "bad",
                version="v1",
                engine="jinja",
                root=root,
                log=False,
            )


class TestIncludesSecurity:
    def test_traversal_rejected(self, jinja_root: Path) -> None:
        loader = PromptIncludeLoader(jinja_root)
        with pytest.raises(PromptNotFoundError, match="escapes"):
            loader.resolve("../secret.txt")

    def test_missing_include_raises(self, jinja_root: Path) -> None:
        _write(jinja_root, "agent/v9.txt", '{% include "partials/missing.txt" %}')
        with pytest.raises(PromptNotFoundError, match="not found"):
            promptconf.load(
                "agent",
                version="v9",
                engine="jinja",
                root=jinja_root,
                log=False,
            )

    def test_sandbox_blocks_dunder(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(
            root,
            "evil/v1.txt",
            "{{ ''.__class__.__mro__ }}",
        )
        with pytest.raises(PromptFormatError, match="Unsafe|blocked|security|Sandbox"):
            promptconf.load(
                "evil",
                version="v1",
                engine="jinja",
                root=root,
                log=False,
            )


class TestCompilePrompt:
    def test_compile_jinja_ok(self, jinja_root: Path) -> None:
        info = promptconf.compile_prompt(
            "agent",
            version="v1",
            root=jinja_root,
            engine="jinja",
        )
        assert info["name"] == "agent"
        assert info["resolved_version"] == "v1"
        assert info["metadata"]["model"] == "gpt-4"
        assert "Hello {{ name }}" in info["body"]
        assert info["engine"] == "jinja"

    def test_compile_detects_syntax_error(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(root, "bad/v1.txt", "{% for x in %}")
        with pytest.raises(PromptFormatError, match="syntax"):
            promptconf.compile_prompt("bad", "v1", root=root, engine="jinja")

    def test_compile_format_engine(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write(root, "plain/v1.txt", "---\nk: v\n---\nHi {name}")
        info = promptconf.compile_prompt(
            "plain", "v1", root=root, engine="format"
        )
        assert info["metadata"] == {"k": "v"}
        assert info["body"] == "Hi {name}"

    def test_compile_template_helper(self) -> None:
        result = compile_template("Hello {{ name }}", name="inline")
        assert result["body"] == "Hello {{ name }}"
        assert result["metadata"] == {}


class TestJinjaImportError:
    def test_require_jinja_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins
        import sys

        # Drop cached jinja2 modules so the import path is exercised.
        cached = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "jinja2" or k.startswith("jinja2.")}
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "jinja2" or name.startswith("jinja2."):
                raise ImportError("No module named jinja2")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        try:
            with pytest.raises(ImportError, match=r"promptconf\[jinja\]"):
                require_jinja()
        finally:
            sys.modules.update(cached)

    def test_load_jinja_missing_dep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins
        import sys

        root = tmp_path / "prompts"
        _write(root, "x/v1.txt", "Hi {{ name }}")
        cached = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "jinja2" or k.startswith("jinja2.")}
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "jinja2" or name.startswith("jinja2."):
                raise ImportError("No module named jinja2")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        try:
            with pytest.raises(ImportError, match=r"promptconf\[jinja\]"):
                promptconf.load(
                    "x",
                    version="v1",
                    engine="jinja",
                    vars={"name": "A"},
                    root=root,
                    log=False,
                )
        finally:
            sys.modules.update(cached)


class TestRenderHelper:
    def test_render_jinja_direct(self, jinja_root: Path) -> None:
        out = render_jinja(
            "X={{ value }}",
            {"value": 7},
            root=jinja_root,
        )
        assert out == "X=7"
