"""CLI edge-case tests: bad args, missing prompts, via main()."""

from __future__ import annotations

from pathlib import Path

import pytest

from promptconf.cli import main


def _write_prompt(root: Path, name: str, version: str, content: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{version}.txt").write_text(content, encoding="utf-8")


@pytest.fixture
def prompts_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    _write_prompt(root, "greeter", "v1", "Hello, {name}!\n")
    return root


# ---------------------------------------------------------------------------
# Missing prompts / versions
# ---------------------------------------------------------------------------


def test_show_missing_prompt(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(prompts_root), "show", "nope"])
    assert code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_versions_missing_prompt(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(prompts_root), "versions", "missing"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_show_missing_version(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--root", str(prompts_root), "show", "greeter", "--version", "v99"]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_diff_missing_version(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "--root",
            str(prompts_root),
            "diff",
            "greeter",
            "--a",
            "v1",
            "--b",
            "v99",
        ]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_tag_missing_version(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--root", str(prompts_root), "tag", "greeter", "v99", "bad"]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_resolve_missing_tag(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(prompts_root), "resolve-tag", "ghost"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Bad args
# ---------------------------------------------------------------------------


def test_no_subcommand_returns_nonzero() -> None:
    code = main([])
    assert code != 0


def test_unknown_subcommand_returns_nonzero() -> None:
    code = main(["not-a-real-command"])
    assert code != 0


def test_show_bad_var_missing_equals(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
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
            "noequals",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "KEY=VALUE" in err or "Invalid" in err


def test_show_bad_var_empty_key(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
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
            "=value",
        ]
    )
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_diff_missing_required_flags(
    prompts_root: Path,
) -> None:
    # argparse exits non-zero when --a/--b missing
    code = main(["--root", str(prompts_root), "diff", "greeter"])
    assert code != 0


def test_show_path_traversal_name(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--root", str(prompts_root), "show", "../secret"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_list_missing_root_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """list on a non-existent root prints nothing and exits 0."""
    code = main(["--root", str(tmp_path / "absent"), "list"])
    assert code == 0
    assert capsys.readouterr().out == ""


def test_show_strict_missing_var(
    prompts_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--root", str(prompts_root), "show", "greeter", "--version", "v1"]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().err
