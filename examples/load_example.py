#!/usr/bin/env python3
"""Minimal example: load a versioned prompt and format variables."""

from __future__ import annotations

from pathlib import Path

import promptconf

ROOT = Path(__file__).resolve().parent / "prompts"


def main() -> None:
    prompt = promptconf.load(
        "classifier",
        version="v2",
        vars={"language": "Python", "text": "Shipping this package feels great."},
        root=ROOT,
        log=False,
    )
    print("--- classifier@v2 ---")
    print(prompt)

    latest = promptconf.load(
        "classifier",
        version="latest",
        vars={"language": "Python", "text": "meh"},
        root=ROOT,
        log=False,
    )
    print("--- classifier@latest ---")
    print(latest)

    print("prompts:", promptconf.list_prompts(root=ROOT))
    print("classifier versions:", promptconf.list_versions("classifier", root=ROOT))


if __name__ == "__main__":
    main()
