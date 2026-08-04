"""Property-based tests for version sorting and latest resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

from promptconf.loader import (
    _sort_versions,
    _version_number,
    list_versions,
    load,
)

# Keep examples snappy for CI / full-suite runs.
_SETTINGS = settings(max_examples=40, deadline=None)

_VERSION_NUM = st.integers(min_value=0, max_value=500)
_OTHER_STEM = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=12,
).filter(lambda s: s not in {".", ".."} and not s.startswith("v") or not s[1:].isdigit() if s.startswith("v") and len(s) > 1 else True)


def _write(root: Path, name: str, stem: str, body: str = "x") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.txt").write_text(body, encoding="utf-8")


@_SETTINGS
@given(nums=st.lists(_VERSION_NUM, min_size=1, max_size=12, unique=True))
def test_sort_versions_numeric_ascending(nums: list[int]) -> None:
    labels = {f"v{n}" for n in nums}
    sorted_labels = _sort_versions(labels)
    assert sorted_labels == [f"v{n}" for n in sorted(nums)]
    assert [_version_number(v) for v in sorted_labels] == sorted(nums)


@_SETTINGS
@given(
    nums=st.lists(_VERSION_NUM, min_size=1, max_size=8, unique=True),
    include_latest=st.booleans(),
)
def test_sort_versions_latest_always_last(nums: list[int], include_latest: bool) -> None:
    labels = {f"v{n}" for n in nums}
    if include_latest:
        labels.add("latest")
    ordered = _sort_versions(labels)
    if include_latest:
        assert ordered[-1] == "latest"
        assert ordered.count("latest") == 1
    else:
        assert "latest" not in ordered


@_SETTINGS
@given(
    nums=st.lists(_VERSION_NUM, min_size=1, max_size=10, unique=True),
    others=st.lists(
        st.text(alphabet="abcdefghijk", min_size=1, max_size=6),
        min_size=0,
        max_size=4,
        unique=True,
    ),
)
def test_sort_versions_partition_order(nums: list[int], others: list[str]) -> None:
    """Numeric ascending, then other stems alpha, then optional latest."""
    # Avoid colliding with numeric / latest reserved patterns
    clean_others = {
        o for o in others if o not in {"latest", "."} and not o.startswith("v")
    }
    labels = {f"v{n}" for n in nums} | clean_others
    ordered = _sort_versions(labels)
    numeric = [v for v in ordered if v.startswith("v") and v[1:].isdigit()]
    rest = [v for v in ordered if v not in numeric and v != "latest"]
    assert numeric == [f"v{n}" for n in sorted(nums)]
    assert rest == sorted(clean_others)


@_SETTINGS
@given(nums=st.lists(_VERSION_NUM, min_size=1, max_size=10, unique=True))
def test_latest_resolves_to_max_vn(tmp_path: Path, nums: list[int]) -> None:
    # Unique subdir per Hypothesis example — pytest tmp_path is shared across draws.
    root = tmp_path / f"prompts-{'-'.join(str(n) for n in nums)}"
    name = "p"
    for n in nums:
        _write(root, name, f"v{n}", f"body-{n}")
    result = load(name, version="latest", root=root, log=False, raw=True)
    assert result == f"body-{max(nums)}"
    versions = list_versions(name, root=root)
    assert versions == [f"v{n}" for n in sorted(nums)]


@_SETTINGS
@given(nums=st.lists(_VERSION_NUM, min_size=1, max_size=8, unique=True))
def test_latest_file_beats_max_vn(tmp_path: Path, nums: list[int]) -> None:
    root = tmp_path / f"alias-{'-'.join(str(n) for n in nums)}"
    name = "alias"
    for n in nums:
        _write(root, name, f"v{n}", f"vbody-{n}")
    _write(root, name, "latest", "ALIAS")
    assert load(name, version="latest", root=root, log=False, raw=True) == "ALIAS"
    assert list_versions(name, root=root)[-1] == "latest"


@_SETTINGS
@given(n=_VERSION_NUM)
def test_explicit_version_round_trip(tmp_path: Path, n: int) -> None:
    root = tmp_path / f"one-{n}"
    _write(root, "one", f"v{n}", f"content-{n}")
    assert load("one", version=f"v{n}", root=root, log=False, raw=True) == f"content-{n}"
