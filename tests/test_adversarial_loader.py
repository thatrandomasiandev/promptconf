"""Adversarial and edge-case loader tests for promptconf."""

from __future__ import annotations

from pathlib import Path

import pytest

import promptconf
from promptconf import (
    PromptFormatError,
    PromptNotFoundError,
    PromptSizeError,
    PromptconfError,
    ValidationError,
)
from promptconf.loader import MAX_PROMPT_BYTES

# Optional symbols from parallel feature agents — stay green if absent.
try:
    from promptconf.loader import validate_prompt_name  # noqa: F401
except ImportError:  # pragma: no cover
    pass


def _write_prompt(root: Path, name: str, version: str, content: str, ext: str = ".txt") -> Path:
    prompt_dir = root / name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{version}{ext}"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Missing directories / empty files
# ---------------------------------------------------------------------------


def test_missing_root_dir_lists_empty(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-prompts"
    assert promptconf.list_prompts(root=missing) == []


def test_missing_prompt_dir_raises(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    root.mkdir()
    with pytest.raises(PromptNotFoundError, match="not found"):
        promptconf.load("ghost", root=root, log=False)


def test_empty_prompt_file_loads(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    _write_prompt(root, "blank", "v1", "")
    assert promptconf.load("blank", version="v1", root=root, log=False, raw=True) == ""


def test_prompt_dir_with_no_version_files(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    (root / "empty_dir").mkdir(parents=True)
    with pytest.raises(PromptNotFoundError, match="No 'latest'|not found"):
        promptconf.load("empty_dir", version="latest", root=root, log=False)


# ---------------------------------------------------------------------------
# Path traversal in prompt name / version
# ---------------------------------------------------------------------------


def test_bug_path_traversal_in_name_rejected(tmp_path: Path) -> None:
    """``../`` in prompt names must not escape the prompts root."""
    root = tmp_path / "prompts"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "v1.txt").write_text("LEAKED", encoding="utf-8")

    with pytest.raises((ValidationError, PromptNotFoundError), match=r"Invalid|separator|\.\."):
        promptconf.load("../secret", version="v1", root=root, log=False)

    with pytest.raises((ValidationError, PromptNotFoundError), match=r"Invalid|separator|\.\."):
        promptconf.list_versions("../secret", root=root)


def test_path_traversal_nested_name(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    root.mkdir()
    with pytest.raises((ValidationError, PromptNotFoundError)):
        promptconf.load("foo/../../etc", root=root, log=False)


def test_bug_path_traversal_in_version_rejected(tmp_path: Path) -> None:
    """Version stems must not contain path separators or ``..``."""
    root = tmp_path / "prompts"
    _write_prompt(root, "safe", "v1", "ok")
    with pytest.raises((ValidationError, PromptNotFoundError), match=r"\.\.|separator|stem"):
        promptconf.load("safe", version="../v1", root=root, log=False)
    with pytest.raises((ValidationError, PromptNotFoundError), match=r"\.\.|separator|stem"):
        promptconf.load("safe", version="a/b", root=root, log=False)


def test_null_byte_in_name_rejected(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    root.mkdir()
    with pytest.raises((ValidationError, PromptNotFoundError), match="null"):
        promptconf.load("bad\x00name", root=root, log=False)


# ---------------------------------------------------------------------------
# Binary / non-UTF-8 junk
# ---------------------------------------------------------------------------


def test_bug_binary_prompt_raises_clear_error(tmp_path: Path) -> None:
    """Binary (non-UTF-8) prompt files must raise PromptFormatError, not UnicodeDecodeError."""
    root = tmp_path / "prompts"
    prompt_dir = root / "bin"
    prompt_dir.mkdir(parents=True)
    path = prompt_dir / "v1.txt"
    path.write_bytes(b"\xff\xfe\x00\x01 binary junk \x80\x81")

    with pytest.raises(PromptFormatError, match="UTF-8"):
        promptconf.load("bin", version="v1", root=root, log=False, raw=True)


# ---------------------------------------------------------------------------
# Huge files / size cap
# ---------------------------------------------------------------------------


def test_bug_huge_file_exceeds_size_cap(tmp_path: Path) -> None:
    """Files larger than MAX_PROMPT_BYTES (or max_bytes=) raise PromptSizeError."""
    root = tmp_path / "prompts"
    prompt_dir = root / "huge"
    prompt_dir.mkdir(parents=True)
    path = prompt_dir / "v1.txt"
    path.write_text("x" * 200, encoding="utf-8")

    with pytest.raises(PromptSizeError, match="max size|exceeds"):
        promptconf.load("huge", version="v1", root=root, log=False, max_bytes=64)

    assert (
        promptconf.load("huge", version="v1", root=root, log=False, max_bytes=1024, raw=True)
        == "x" * 200
    )


def test_max_prompt_bytes_constant_documented() -> None:
    assert isinstance(MAX_PROMPT_BYTES, int)
    assert MAX_PROMPT_BYTES >= 1024
    assert promptconf.MAX_PROMPT_BYTES == MAX_PROMPT_BYTES


# ---------------------------------------------------------------------------
# Invalid version strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version",
    [
        "",
        " ",
        "..",
        ".",
        "../v1",
        "v1/../v2",
        "v\x00",
    ],
)
def test_invalid_version_strings(tmp_path: Path, version: str) -> None:
    root = tmp_path / "prompts"
    _write_prompt(root, "greeter", "v1", "Hello")
    with pytest.raises(PromptconfError):
        promptconf.load("greeter", version=version, root=root, log=False)


def test_unknown_but_well_formed_version(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    _write_prompt(root, "greeter", "v1", "Hello")
    with pytest.raises(PromptNotFoundError, match="v99"):
        promptconf.load("greeter", version="v99", root=root, log=False)


def test_empty_name_rejected(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    root.mkdir()
    with pytest.raises((ValidationError, PromptNotFoundError)):
        promptconf.load("", root=root, log=False)
