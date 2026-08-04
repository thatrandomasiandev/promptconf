#!/usr/bin/env python3
"""Deterministic A/B routing walkthrough — offline, no extras.

Shows sticky SHA-256 assignment for a stable user_id, random draws without
user_id, and ab_assignment rows in usage.jsonl.

Run from the promptconf package root:

    python docs/examples/02_ab_router.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from promptconf import ABRouter, log


def _write_tree(root: Path) -> None:
    classifier = root / "classifier"
    classifier.mkdir(parents=True)
    (classifier / "v1.txt").write_text("VARIANT_A: {text}\n", encoding="utf-8")
    (classifier / "v2.txt").write_text("VARIANT_B: {text}\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="promptconf-ex02-") as tmp:
        root = Path(tmp)
        _write_tree(root)

        router = ABRouter(
            {"classifier": {"v1": 0.5, "v2": 0.5}},
            root=root,
            log=True,
            seed=7,
        )

        sticky = [router.choose("classifier", user_id="user-42") for _ in range(5)]
        print("sticky choices for user-42:", sticky)
        assert len(set(sticky)) == 1, "same user_id must map to one variant"

        text = router.load(
            "classifier",
            user_id="user-42",
            vars={"text": "hello"},
            log=True,
        )
        print("rendered:", text.strip())

        random_draws = [router.choose("classifier") for _ in range(8)]
        print("random draws (no user_id):", random_draws)

        records = log("classifier", root=root)
        assignments = [r for r in records if r.get("event") == "ab_assignment"]
        print(f"\nab_assignment events: {len(assignments)}")
        if assignments:
            print(json.dumps(assignments[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
