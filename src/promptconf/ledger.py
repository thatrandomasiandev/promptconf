"""Closed-loop performance ledger — which prompt version wins in production.

Combines version pins, A/B assignments, usage logs, and optional external
metric ingest into a local JSONL outcomes store. Use :func:`recommend` to
prefer empirically best versions when enough samples exist, else fall back
to :class:`~promptconf.ab.ABRouter`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from promptconf.ab import ABRouter
from promptconf.exceptions import ValidationError
from promptconf.loader import resolve_root

OUTCOMES_FILENAME = "outcomes.jsonl"
DEFAULT_METRIC_KEY = "reward"


class PerformanceLedger:
    """Append-only outcomes ledger under ``{root}/.promptconf/outcomes.jsonl``.

    Parameters
    ----------
    root:
        Prompts root (same resolution as :func:`promptconf.loader.load`).
    router:
        Optional :class:`~promptconf.ab.ABRouter` used by :meth:`recommend`
        when sample counts are below ``min_samples``.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        router: ABRouter | None = None,
    ) -> None:
        self.root = resolve_root(root)
        self.router = router

    @property
    def path(self) -> Path:
        return self.root / ".promptconf" / OUTCOMES_FILENAME

    def record_outcome(
        self,
        name: str,
        version: str,
        metric: float,
        *,
        user_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        metric_key: str = DEFAULT_METRIC_KEY,
    ) -> dict[str, Any]:
        """Append one outcome event and return the stored record."""
        return record_outcome(
            name,
            version,
            metric,
            root=self.root,
            user_id=user_id,
            metadata=metadata,
            metric_key=metric_key,
        )

    def best_version(
        self,
        name: str,
        metric_key: str = DEFAULT_METRIC_KEY,
        min_samples: int = 1,
    ) -> str | None:
        """Return the version with the highest mean ``metric_key``, or ``None``."""
        return best_version(
            name,
            root=self.root,
            metric_key=metric_key,
            min_samples=min_samples,
        )

    def recommend(
        self,
        name: str,
        user_id: str | None = None,
        *,
        metric_key: str = DEFAULT_METRIC_KEY,
        min_samples: int = 1,
    ) -> str:
        """Prefer :meth:`best_version` when enough data; else A/B router."""
        return recommend(
            name,
            root=self.root,
            user_id=user_id,
            router=self.router,
            metric_key=metric_key,
            min_samples=min_samples,
        )

    def read_outcomes(
        self,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return outcome records, optionally filtered by prompt ``name``."""
        return read_outcomes(root=self.root, name=name)

    def __repr__(self) -> str:
        return f"PerformanceLedger(root={str(self.root)!r})"


def record_outcome(
    name: str,
    version: str,
    metric: float,
    *,
    root: str | Path | None = None,
    user_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    metric_key: str = DEFAULT_METRIC_KEY,
) -> dict[str, Any]:
    """Append a production outcome to ``{root}/.promptconf/outcomes.jsonl``.

    Parameters
    ----------
    name:
        Prompt name.
    version:
        Concrete version that produced the outcome (e.g. ``"v2"``).
    metric:
        Numeric performance signal (reward, thumbs-up rate, latency inverse, …).
    user_id:
        Optional sticky user / session id (links to A/B assignments).
    metadata:
        Optional extra fields (never required). Stored as-is under ``metadata``.
    metric_key:
        Name of the metric field (default ``"reward"``). Enables multi-metric
        ledgers in the same JSONL file.
    """
    _validate_name_version(name, version)
    try:
        value = float(metric)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"metric must be a float, got {metric!r}") from exc

    root_path = resolve_root(root)
    log_dir = root_path / ".promptconf"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / OUTCOMES_FILENAME

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "version": version,
        "metric_key": metric_key,
        "metric": value,
        "user_id": user_id,
    }
    if metadata:
        record["metadata"] = dict(metadata)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def best_version(
    name: str,
    *,
    root: str | Path | None = None,
    metric_key: str = DEFAULT_METRIC_KEY,
    min_samples: int = 1,
) -> str | None:
    """Aggregate outcomes and return the version with the highest mean metric.

    Only versions with at least ``min_samples`` outcomes for ``metric_key``
    are considered. Returns ``None`` when no version qualifies.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Prompt name must be a non-empty string")
    if min_samples < 1:
        raise ValidationError("min_samples must be >= 1")

    aggregates: dict[str, list[float]] = defaultdict(list)
    for row in read_outcomes(root=root, name=name):
        if row.get("metric_key", DEFAULT_METRIC_KEY) != metric_key:
            continue
        version = row.get("version")
        metric = row.get("metric")
        if not isinstance(version, str) or version == "":
            continue
        try:
            aggregates[version].append(float(metric))
        except (TypeError, ValueError):
            continue

    eligible: list[tuple[str, float, int]] = []
    for version, values in aggregates.items():
        if len(values) < min_samples:
            continue
        mean = sum(values) / len(values)
        eligible.append((version, mean, len(values)))

    if not eligible:
        return None

    # Higher mean wins; tie-break by more samples, then version label.
    eligible.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return eligible[0][0]


def recommend(
    name: str,
    *,
    root: str | Path | None = None,
    user_id: str | None = None,
    router: ABRouter | None = None,
    experiments: Mapping[str, Mapping[str, float]] | None = None,
    metric_key: str = DEFAULT_METRIC_KEY,
    min_samples: int = 1,
) -> str:
    """Closed-loop version selection.

    If :func:`best_version` has enough data, return that winner. Otherwise
    fall back to ``router`` (or a temporary :class:`~promptconf.ab.ABRouter`
    built from ``experiments``).

    Raises
    ------
    ValidationError
        When neither ledger data nor an A/B router / experiments map can
        produce a recommendation.
    """
    winner = best_version(
        name,
        root=root,
        metric_key=metric_key,
        min_samples=min_samples,
    )
    if winner is not None:
        return winner

    active = router
    if active is None and experiments is not None:
        active = ABRouter(experiments, root=root, log=False)

    if active is None:
        raise ValidationError(
            f"No ledger winner for {name!r} (need min_samples={min_samples}) "
            "and no ABRouter / experiments provided for fallback"
        )

    return active.choose(name, user_id=user_id)


def read_outcomes(
    *,
    root: str | Path | None = None,
    name: str | None = None,
) -> list[dict[str, Any]]:
    """Load outcome records from the JSONL ledger."""
    root_path = resolve_root(root)
    path = root_path / ".promptconf" / OUTCOMES_FILENAME
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if name is not None and row.get("name") != name:
            continue
        rows.append(row)
    return rows


def _validate_name_version(name: str, version: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Prompt name must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValidationError("Prompt version must be a non-empty string")
