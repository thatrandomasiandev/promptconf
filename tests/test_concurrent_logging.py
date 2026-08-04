"""Concurrency tests for usage JSONL integrity under parallel load(log=True)."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import promptconf

# Optional modules from parallel feature agents — skip cleanly if logging absent.
try:
    from promptconf.logging import append_usage_log  # noqa: F401
except ImportError:  # pragma: no cover
    pytest.skip("promptconf.logging unavailable", allow_module_level=True)


def _write_prompt(root: Path, name: str, version: str, content: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{version}.txt").write_text(content, encoding="utf-8")


def _parse_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    records = []
    for i, line in enumerate(lines):
        assert line.strip(), f"blank line at {i}"
        records.append(json.loads(line))
    return records


def test_bug_concurrent_usage_log_intact_jsonl(tmp_path: Path) -> None:
    """Parallel load(log=True) must not corrupt usage.jsonl (valid JSON per line)."""
    root = tmp_path / "prompts"
    _write_prompt(root, "greeter", "v1", "Hello, {name}!")

    n_threads = 8
    per_thread = 25
    barrier = threading.Barrier(n_threads)
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            barrier.wait()
            for i in range(per_thread):
                promptconf.load(
                    "greeter",
                    version="v1",
                    vars={"name": f"u{tid}-{i}"},
                    root=root,
                    log=True,
                )
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        list(pool.map(worker, range(n_threads)))

    assert not errors, f"worker errors: {errors!r}"

    log_path = root / ".promptconf" / "usage.jsonl"
    assert log_path.is_file()
    records = _parse_jsonl(log_path)
    assert len(records) == n_threads * per_thread
    assert all(r["name"] == "greeter" for r in records)
    assert all(r["vars_keys"] == ["name"] for r in records)
    # Secrets must never appear in the log.
    raw = log_path.read_text(encoding="utf-8")
    assert "u0-0" not in raw


def test_concurrent_loads_different_prompts(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    for name in ("a", "b", "c", "d"):
        _write_prompt(root, name, "v1", f"prompt-{name}")

    n = 40
    barrier = threading.Barrier(4)

    def worker(name: str) -> None:
        barrier.wait()
        for _ in range(n):
            promptconf.load(name, version="v1", root=root, log=True, raw=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, ["a", "b", "c", "d"]))

    records = _parse_jsonl(root / ".promptconf" / "usage.jsonl")
    assert len(records) == 4 * n
    counts = {name: 0 for name in ("a", "b", "c", "d")}
    for r in records:
        counts[r["name"]] += 1
    assert counts == {name: n for name in ("a", "b", "c", "d")}


def test_log_false_concurrent_creates_no_file(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    _write_prompt(root, "greeter", "v1", "Hi")

    def worker(_: int) -> None:
        promptconf.load("greeter", version="v1", root=root, log=False, raw=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(32)))

    assert not (root / ".promptconf" / "usage.jsonl").exists()
