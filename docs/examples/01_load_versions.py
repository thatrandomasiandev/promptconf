#!/usr/bin/env python3
"""Load & version resolution walkthrough — offline, no extras.

Demonstrates resolve_root-style stores, explicit versions, ``latest`` alias
preference, listing, and strict vs non-strict formatting.

Run from the promptconf package root:

    python docs/examples/01_load_versions.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import promptconf


def _write_tree(root: Path) -> None:
    classifier = root / "classifier"
    classifier.mkdir(parents=True)
    (classifier / "v1.txt").write_text(
        "Classify sentiment.\n\nText: {text}\n",
        encoding="utf-8",
    )
    (classifier / "v2.txt").write_text(
        "You are a precise {language} sentiment classifier.\n"
        "Return only one label: positive, negative, or neutral.\n\n"
        "Input:\n{text}\n",
        encoding="utf-8",
    )
    (classifier / "latest.txt").write_text(
        "You are a precise {language} sentiment classifier (latest).\n"
        "Return only one label: positive, negative, or neutral.\n\n"
        "Input:\n{text}\n",
        encoding="utf-8",
    )
    greeter = root / "greeter"
    greeter.mkdir()
    (greeter / "v1.txt").write_text("Hello, {name}!\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="promptconf-ex01-") as tmp:
        root = Path(tmp)
        _write_tree(root)

        print("prompts:", promptconf.list_prompts(root=root))
        print("classifier versions:", promptconf.list_versions("classifier", root=root))

        v2 = promptconf.load(
            "classifier",
            version="v2",
            vars={"language": "Python", "text": "Shipping this feels great."},
            root=root,
            log=False,
        )
        print("\n=== classifier@v2 ===")
        print(v2, end="")

        latest = promptconf.load(
            "classifier",
            version="latest",
            vars={"language": "Python", "text": "meh"},
            root=root,
            log=False,
        )
        print("=== classifier@latest (explicit latest.* wins) ===")
        print(latest, end="")

        soft = promptconf.load(
            "greeter",
            version="v1",
            vars={},
            root=root,
            strict=False,
            log=False,
        )
        print("=== greeter@v1 strict=False ===")
        print(soft, end="")

        info = promptconf.compile_prompt(
            "classifier",
            version="v2",
            root=root,
            engine="format",
        )
        print("compile_prompt keys:", sorted(info.keys()))
        print("resolved_version:", info["resolved_version"])


if __name__ == "__main__":
    main()
