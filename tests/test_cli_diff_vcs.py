"""Tests for promptconf CLI, diff, and VCS helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import promptconf
from promptconf import PromptNotFoundError
from promptconf.cli import main
from promptconf.diff import diff_versions
from promptconf.vcs import freeze, log, resolve_tag, tag


def _write_prompt(root: Path, name: str, version: str, content: str, ext: str = ".txt") -> Path:
    prompt_dir = root / name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{version}{ext}"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def prompts_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    _write_prompt(root, "classifier", "v1", "Classify: {text}\n")
    _write_prompt(root, "classifier", "v2", "You are a {language} classifier.\n{text}\n")
    _write_prompt(root, "classifier", "v10", "v10 {language}\n")
    _write_prompt(root, "greeter", "v1", "Hello, {name}!\n")
    return root


class TestDiff:
    def test_diff_versions_unified(self, prompts_root: Path) -> None:
        result = diff_versions("classifier", "v1", "v2", root=prompts_root)
        assert result.startswith("--- classifier/v1")
        assert "+++ classifier/v2" in result
        assert "-Classify: {text}" in result or "-Classify: {text}\n" in result
        assert "+You are a {language} classifier." in result

    def test_diff_identical_empty(self, prompts_root: Path) -> None:
        result = diff_versions("classifier", "v1", "v1", root=prompts_root)
        assert result == ""

    def test_diff_missing_version(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError):
            diff_versions("classifier", "v1", "v99", root=prompts_root)

    def test_diff_exported(self) -> None:
        assert promptconf.diff_versions is diff_versions


class TestVcs:
    def test_tag_and_resolve(self, prompts_root: Path) -> None:
        record = tag("classifier", "v2", "prod", root=prompts_root)
        assert record == {"name": "classifier", "version": "v2"}

        tags_path = prompts_root / ".promptconf" / "tags.json"
        assert tags_path.is_file()
        data = json.loads(tags_path.read_text(encoding="utf-8"))
        assert data["prod"] == {"name": "classifier", "version": "v2"}

        assert resolve_tag("prod", root=prompts_root) == {
            "name": "classifier",
            "version": "v2",
        }

    def test_tag_overwrites(self, prompts_root: Path) -> None:
        tag("classifier", "v1", "stable", root=prompts_root)
        tag("classifier", "v2", "stable", root=prompts_root)
        assert resolve_tag("stable", root=prompts_root)["version"] == "v2"

    def test_tag_invalid_version(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError, match="v99"):
            tag("classifier", "v99", "bad", root=prompts_root)

    def test_resolve_missing_tag(self, prompts_root: Path) -> None:
        with pytest.raises(PromptNotFoundError, match="missing"):
            resolve_tag("missing", root=prompts_root)

    def test_log_filters_by_name(self, prompts_root: Path) -> None:
        promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=True,
        )
        promptconf.load(
            "classifier",
            version="v1",
            vars={"text": "x"},
            root=prompts_root,
            log=True,
        )
        greeter_logs = log("greeter", root=prompts_root)
        assert len(greeter_logs) == 1
        assert greeter_logs[0]["name"] == "greeter"
        assert greeter_logs[0]["vars_keys"] == ["name"]

        classifier_logs = log("classifier", root=prompts_root)
        assert len(classifier_logs) == 1
        assert classifier_logs[0]["name"] == "classifier"

    def test_log_empty_when_missing(self, prompts_root: Path) -> None:
        assert log("greeter", root=prompts_root) == []

    def test_freeze_pins_highest_vn(self, prompts_root: Path) -> None:
        pins = freeze(root=prompts_root)
        assert pins["classifier"] == "v10"
        assert pins["greeter"] == "v1"

        lock_path = prompts_root / "prompt.lock.json"
        assert lock_path.is_file()
        locked = json.loads(lock_path.read_text(encoding="utf-8"))
        assert locked == pins

    def test_freeze_prefers_latest_file(self, prompts_root: Path) -> None:
        _write_prompt(prompts_root, "classifier", "latest", "LATEST\n")
        pins = freeze(root=prompts_root)
        assert pins["classifier"] == "latest"


class TestCli:
    def test_list(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--root", str(prompts_root), "list"])
        assert code == 0
        out = capsys.readouterr().out
        assert "classifier" in out
        assert "greeter" in out

    def test_versions(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--root", str(prompts_root), "versions", "classifier"])
        assert code == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines == ["v1", "v2", "v10"]

    def test_show_with_vars(
        self, prompts_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "--root",
                str(prompts_root),
                "show",
                "greeter",
                "--version",
                "v1",
                "--var",
                "name=Ada",
            ]
        )
        assert code == 0
        assert "Hello, Ada!" in capsys.readouterr().out

    def test_diff(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(
            [
                "--root",
                str(prompts_root),
                "diff",
                "classifier",
                "--a",
                "v1",
                "--b",
                "v2",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "--- classifier/v1" in out
        assert "+++ classifier/v2" in out

    def test_tag(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(
            ["--root", str(prompts_root), "tag", "classifier", "v2", "prod"]
        )
        assert code == 0
        assert "prod" in capsys.readouterr().out
        assert resolve_tag("prod", root=prompts_root)["version"] == "v2"

    def test_freeze(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--root", str(prompts_root), "freeze"])
        assert code == 0
        out = capsys.readouterr().out
        assert "prompt.lock.json" in out
        locked = json.loads((prompts_root / "prompt.lock.json").read_text(encoding="utf-8"))
        assert locked["classifier"] == "v10"

    def test_log(self, prompts_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=True,
        )
        code = main(["--root", str(prompts_root), "log", "greeter"])
        assert code == 0
        out = capsys.readouterr().out.strip()
        record = json.loads(out)
        assert record["name"] == "greeter"

    def test_show_missing_returns_error(
        self, prompts_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--root", str(prompts_root), "show", "nope"])
        assert code == 1
        err = capsys.readouterr().err
        assert "error:" in err

    def test_env_root(
        self,
        prompts_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("PROMPTCONF_ROOT", str(prompts_root))
        code = main(["list"])
        assert code == 0
        assert "classifier" in capsys.readouterr().out
