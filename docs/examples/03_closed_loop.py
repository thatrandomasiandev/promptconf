#!/usr/bin/env python3
"""Closed-loop versioning + AB + performance ledger — offline, no extras.

Walks tag → freeze → diff → sticky A/B load → usage trail → ledger
(`record_outcome` / `best_version` / `recommend`), the product loop
described in UPGRADE_NOTES.md.

Run from the promptconf package root:

    python docs/examples/03_closed_loop.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from promptconf import (
    ABRouter,
    best_version,
    diff_versions,
    freeze,
    load,
    log,
    recommend,
    record_outcome,
    resolve_tag,
    tag,
)


def _write_tree(root: Path) -> None:
    classifier = root / "classifier"
    classifier.mkdir(parents=True)
    (classifier / "v1.txt").write_text(
        "You classify text.\n\n{text}\n",
        encoding="utf-8",
    )
    (classifier / "v2.txt").write_text(
        "You are a precise sentiment classifier.\n\nInput:\n{text}\n",
        encoding="utf-8",
    )
    greeter = root / "greeter"
    greeter.mkdir()
    (greeter / "v1.txt").write_text("Hello, {name}!\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="promptconf-ex03-") as tmp:
        root = Path(tmp)
        _write_tree(root)

        # --- Versioning: tag + freeze ---
        record = tag("classifier", "v2", "prod", root=root)
        print("tagged prod ->", record)
        pin = resolve_tag("prod", root=root)
        print("resolve_tag(prod):", pin)

        locks = freeze(root=root)
        print("freeze pins:", locks)
        lock_path = root / "prompt.lock.json"
        print("lock file:", lock_path.read_text(encoding="utf-8"), end="")

        # --- Diff for review ---
        delta = diff_versions("classifier", "v1", "v2", root=root)
        print("=== diff v1 → v2 ===")
        print(delta, end="" if delta.endswith("\n") else "\n")

        # --- Load pinned prod version ---
        text = load(
            pin["name"],
            version=pin["version"],
            vars={"text": "great product"},
            root=root,
            log=True,
        )
        print("=== load prod pin ===")
        print(text, end="")

        # --- A/B onto versioned stems + outcome trail ---
        router = ABRouter(
            {"classifier": {"v1": 0.4, "v2": 0.6}},
            root=root,
            log=True,
        )
        variant = router.choose("classifier", user_id="cohort-a")
        routed = router.load(
            "classifier",
            user_id="cohort-a",
            vars={"text": "great product"},
        )
        print(f"=== AB user cohort-a → {variant} ===")
        print(routed, end="")

        trail = log("classifier", root=root)
        print(f"\nusage trail ({len(trail)} events):")
        for row in trail:
            summary = {
                "event": row.get("event", "load"),
                "version": row.get("version"),
                "resolved_version": row.get("resolved_version"),
                "vars_keys": row.get("vars_keys"),
                "user_id": row.get("user_id"),
            }
            print(json.dumps(summary, ensure_ascii=False))

        # --- Performance ledger: which version wins ---
        record_outcome("classifier", "v1", 0.4, root=root, user_id="cohort-a")
        record_outcome("classifier", "v2", 0.9, root=root, user_id="cohort-a")
        winner = best_version("classifier", root=root, min_samples=1)
        chosen = recommend(
            "classifier",
            root=root,
            user_id="cohort-a",
            router=router,
            min_samples=1,
        )
        print(f"ledger best_version={winner} recommend={chosen}")


if __name__ == "__main__":
    main()
