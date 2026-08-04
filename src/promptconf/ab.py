"""Weighted A/B routing for prompt versions."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Mapping

from promptconf.exceptions import PromptconfError
from promptconf.loader import load, resolve_root
from promptconf.logging import append_usage_log


class ABRouter:
    """Route users to weighted prompt version variants.

    Example
    -------
    >>> router = ABRouter({"classifier": {"v1": 0.5, "v2": 0.5}}, root="./prompts")
    >>> version = router.choose("classifier", user_id="user-42")
    >>> text = router.load("classifier", user_id="user-42", vars={"text": "hi"})
    """

    def __init__(
        self,
        experiments: Mapping[str, Mapping[str, float]],
        *,
        root: str | Path | None = None,
        log: bool = True,
        seed: int | None = None,
    ) -> None:
        self.root = resolve_root(root)
        self.log = log
        self._rng = random.Random(seed)
        self.experiments: dict[str, dict[str, float]] = {
            name: _normalize_weights(weights)
            for name, weights in experiments.items()
        }

    def choose(self, name: str, user_id: str | None = None) -> str:
        """Select a variant version for ``name``.

        When ``user_id`` is provided, selection is deterministic via
        ``hash(name + ":" + user_id)``. Otherwise a random draw is used.
        """
        weights = self.experiments.get(name)
        if not weights:
            raise PromptconfError(
                f"No A/B experiment configured for prompt {name!r}. "
                f"Known experiments: {_format_keys(self.experiments)}"
            )

        if user_id is not None:
            variant = _deterministic_choice(name, user_id, weights)
        else:
            variant = _weighted_choice(weights, self._rng)

        if self.log:
            append_usage_log(
                self.root,
                name=name,
                version=variant,
                resolved_version=variant,
                path=self.root / name / variant,
                var_keys=[],
                extra={
                    "event": "ab_assignment",
                    "user_id": user_id,
                    "variants": dict(weights),
                },
            )
        return variant

    def load(
        self,
        name: str,
        vars: Mapping[str, object] | None = None,
        *,
        user_id: str | None = None,
        strict: bool = True,
        log: bool = True,
        raw: bool = False,
    ) -> str:
        """Choose a variant then load and format that prompt version."""
        version = self.choose(name, user_id=user_id)
        return load(
            name,
            version=version,
            vars=vars,
            root=self.root,
            strict=strict,
            log=log,
            raw=raw,
        )

    def __repr__(self) -> str:
        return (
            f"ABRouter(experiments={list(self.experiments)}, "
            f"root={str(self.root)!r})"
        )


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    if not weights:
        raise PromptconfError("A/B variant weights must not be empty")
    cleaned: dict[str, float] = {}
    for key, value in weights.items():
        w = float(value)
        if w < 0:
            raise PromptconfError(
                f"Variant weight for {key!r} must be >= 0, got {w}"
            )
        cleaned[str(key)] = w
    total = sum(cleaned.values())
    if total <= 0:
        raise PromptconfError("A/B variant weights must sum to a positive number")
    return {key: value / total for key, value in cleaned.items()}


def _deterministic_choice(
    name: str,
    user_id: str,
    weights: Mapping[str, float],
) -> str:
    digest = hashlib.sha256(f"{name}:{user_id}".encode("utf-8")).hexdigest()
    # Map first 8 hex chars to [0, 1)
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return _pick_from_bucket(weights, bucket)


def _weighted_choice(weights: Mapping[str, float], rng: random.Random) -> str:
    return _pick_from_bucket(weights, rng.random())


def _pick_from_bucket(weights: Mapping[str, float], bucket: float) -> str:
    cumulative = 0.0
    items = list(weights.items())
    for key, weight in items[:-1]:
        cumulative += weight
        if bucket < cumulative:
            return key
    return items[-1][0]


def _format_keys(mapping: Mapping[str, object]) -> str:
    if not mapping:
        return "(none)"
    return ", ".join(sorted(mapping))
