"""Unit tests for promptconf (tmp_path fixtures, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import promptconf
from promptconf import PromptFormatError, PromptNotFoundError, PromptStore


def _write_prompt(root: Path, name: str, version: str, content: str, ext: str = ".txt") -> Path:
    prompt_dir = root / name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{version}{ext}"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def prompts_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    _write_prompt(root, "classifier", "v1", "Classify: {text}")
    _write_prompt(root, "classifier", "v2", "You are a {language} classifier.\n{text}")
    _write_prompt(root, "classifier", "v10", "v10 {language}")
    _write_prompt(root, "greeter", "v1", "Hello, {name}!")
    return root


class TestLoad:
    def test_load_specific_version(self, prompts_root: Path) -> None:
        result = promptconf.load(
            "classifier",
            version="v2",
            vars={"language": "Python", "text": "hi"},
            root=prompts_root,
            log=False,
        )
        assert "Python classifier" in result
        assert "hi" in result

    def test_load_latest_file_preferred(self, prompts_root: Path) -> None:
        _write_prompt(prompts_root, "classifier", "latest", "LATEST {language}")
        result = promptconf.load(
            "classifier",
            version="latest",
            vars={"language": "Go"},
            root=prompts_root,
            log=False,
        )
        assert result == "LATEST Go"

    def test_load_latest_falls_back_to_highest_vn(self, prompts_root: Path) -> None:
        result = promptconf.load(
            "classifier",
            version="latest",
            vars={"language": "Rust"},
            root=prompts_root,
            log=False,
        )
        assert result == "v10 Rust"

    def test_md_and_prompt_extensions(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "docs", "v1", "# Hello {name}", ext=".md")
        _write_prompt(root, "agent", "v1", "Act as {role}", ext=".prompt")

        assert "Alice" in promptconf.load(
            "docs", version="v1", vars={"name": "Alice"}, root=root, log=False
        )
        assert "reviewer" in promptconf.load(
            "agent", version="v1", vars={"role": "reviewer"}, root=root, log=False
        )

    def test_extension_preference_txt_over_md(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "dual", "v1", "from-txt", ext=".txt")
        _write_prompt(root, "dual", "v1", "from-md", ext=".md")
        assert (
            promptconf.load("dual", version="v1", root=root, log=False, raw=True)
            == "from-txt"
        )

    def test_raw_skips_formatting(self, prompts_root: Path) -> None:
        result = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
            raw=True,
        )
        assert result == "Hello, {name}!"

    def test_strict_missing_var_raises(self, prompts_root: Path) -> None:
        with pytest.raises(PromptFormatError, match="Missing required"):
            promptconf.load(
                "greeter",
                version="v1",
                vars={},
                root=prompts_root,
                log=False,
                strict=True,
            )

    def test_non_strict_leaves_placeholders(self, prompts_root: Path) -> None:
        result = promptconf.load(
            "greeter",
            version="v1",
            vars={},
            root=prompts_root,
            log=False,
            strict=False,
        )
        assert result == "Hello, {name}!"

    def test_missing_version_lists_available(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError, match="v1") as exc_info:
            promptconf.load("classifier", version="v99", root=prompts_root, log=False)
        assert "v2" in str(exc_info.value)

    def test_missing_prompt_lists_available(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError, match="classifier"):
            promptconf.load("nope", root=prompts_root, log=False)

    def test_literal_braces_in_template(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        _write_prompt(root, "json", "v1", 'Use {{"key": "{value}"}}')
        result = promptconf.load(
            "json",
            version="v1",
            vars={"value": "x"},
            root=root,
            log=False,
        )
        assert result == 'Use {"key": "x"}'


class TestListing:
    def test_list_prompts(self, prompts_root: Path) -> None:
        assert promptconf.list_prompts(root=prompts_root) == ["classifier", "greeter"]

    def test_list_versions_sorts_numerically(self, prompts_root: Path) -> None:
        versions = promptconf.list_versions("classifier", root=prompts_root)
        assert versions == ["v1", "v2", "v10"]

    def test_list_versions_includes_latest_last(self, prompts_root: Path) -> None:
        _write_prompt(prompts_root, "classifier", "latest", "x")
        versions = promptconf.list_versions("classifier", root=prompts_root)
        assert versions[-1] == "latest"

    def test_list_versions_missing_prompt(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError):
            promptconf.list_versions("missing", root=prompts_root)


class TestLogging:
    def test_usage_log_appends_keys_only(self, prompts_root: Path) -> None:
        promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "secret-value"},
            root=prompts_root,
            log=True,
        )
        log_path = prompts_root / ".promptconf" / "usage.jsonl"
        assert log_path.is_file()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["name"] == "greeter"
        assert record["version"] == "v1"
        assert record["resolved_version"] == "v1"
        assert record["vars_keys"] == ["name"]
        assert "secret-value" not in log_path.read_text(encoding="utf-8")
        assert "path" in record
        assert "timestamp" in record

    def test_log_false_skips_file(self, prompts_root: Path) -> None:
        promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
        )
        assert not (prompts_root / ".promptconf" / "usage.jsonl").exists()


class TestRootResolution:
    def test_env_root(self, prompts_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROMPTCONF_ROOT", str(prompts_root))
        result = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Env"},
            log=False,
        )
        assert result == "Hello, Env!"

    def test_explicit_root_overrides_env(
        self, prompts_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        other = tmp_path / "other"
        _write_prompt(other, "greeter", "v1", "Other {name}")
        monkeypatch.setenv("PROMPTCONF_ROOT", str(other))
        result = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "X"},
            root=prompts_root,
            log=False,
        )
        assert result == "Hello, X!"


class TestPromptStore:
    def test_store_load_and_list(self, prompts_root: Path) -> None:
        store = PromptStore(root=prompts_root)
        assert store.list_prompts() == ["classifier", "greeter"]
        assert "Ada" in store.load("greeter", vars={"name": "Ada"}, log=False)
        assert "v2" in store.list_versions("classifier")
