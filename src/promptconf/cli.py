"""Command-line interface for promptconf."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from promptconf import __version__
from promptconf.diff import diff_versions
from promptconf.exceptions import PromptconfError
from promptconf.loader import list_prompts, list_versions, load, resolve_root
from promptconf.vcs import freeze, log, resolve_tag, tag


def _parse_vars(pairs: list[str] | None) -> dict[str, str]:
    """Parse ``KEY=VALUE`` pairs into a dict."""
    result: dict[str, str] = {}
    if not pairs:
        return result
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Invalid --var '{item}'; expected KEY=VALUE")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError(f"Invalid --var '{item}'; key must be non-empty")
        result[key] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser."""
    parser = argparse.ArgumentParser(
        prog="promptconf",
        description="Git-like prompt version control for local AI engineering",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Prompts root directory (default: PROMPTCONF_ROOT or ./prompts)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List prompt names under the root")

    p_versions = sub.add_parser("versions", help="List versions for a prompt")
    p_versions.add_argument("name", help="Prompt name")

    p_show = sub.add_parser("show", help="Show (load) a prompt")
    p_show.add_argument("name", help="Prompt name")
    p_show.add_argument(
        "--version",
        dest="prompt_version",
        default="latest",
        help="Version label (default: latest)",
    )
    p_show.add_argument(
        "--var",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Template variable (repeatable)",
    )
    p_show.add_argument(
        "--raw",
        action="store_true",
        help="Skip variable formatting",
    )
    p_show.add_argument(
        "--no-strict",
        action="store_true",
        help="Leave missing placeholders unchanged",
    )

    p_diff = sub.add_parser("diff", help="Unified diff between two versions")
    p_diff.add_argument("name", help="Prompt name")
    p_diff.add_argument("--a", required=True, dest="version_a", help="From version")
    p_diff.add_argument("--b", required=True, dest="version_b", help="To version")

    p_tag = sub.add_parser("tag", help="Tag a prompt version")
    p_tag.add_argument("name", help="Prompt name")
    p_tag.add_argument("version", help="Version label to tag")
    p_tag.add_argument("tag", help="Tag name")

    sub.add_parser("freeze", help="Write prompt.lock.json pinning latest versions")

    p_log = sub.add_parser("log", help="Show usage log entries for a prompt")
    p_log.add_argument("name", help="Prompt name")

    p_resolve = sub.add_parser(
        "resolve-tag",
        help="Resolve a tag name to prompt + version",
    )
    p_resolve.add_argument("tag", help="Tag name")

    return parser


def _cmd_list(root: Path) -> int:
    names = list_prompts(root=root)
    for name in names:
        print(name)
    return 0


def _cmd_versions(root: Path, name: str) -> int:
    for version in list_versions(name, root=root):
        print(version)
    return 0


def _cmd_show(
    root: Path,
    name: str,
    version: str,
    var_pairs: list[str] | None,
    *,
    raw: bool,
    no_strict: bool,
) -> int:
    vars_map = _parse_vars(var_pairs)
    text = load(
        name,
        version=version,
        vars=vars_map or None,
        root=root,
        strict=not no_strict,
        log=False,
        raw=raw,
    )
    # Print without adding an extra trailing newline if content already has one
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_diff(root: Path, name: str, a: str, b: str) -> int:
    result = diff_versions(name, a, b, root=root)
    if result:
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _cmd_tag(root: Path, name: str, version: str, tag_name: str) -> int:
    record = tag(name, version, tag_name, root=root)
    print(f"Tagged {tag_name} -> {record['name']}@{record['version']}")
    return 0


def _cmd_freeze(root: Path) -> int:
    pins = freeze(root=root)
    lock_path = root / "prompt.lock.json"
    print(f"Wrote {lock_path} ({len(pins)} prompt(s))")
    for name, version in sorted(pins.items()):
        print(f"  {name}: {version}")
    return 0


def _cmd_log(root: Path, name: str) -> int:
    records = log(name, root=root)
    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    return 0


def _cmd_resolve_tag(root: Path, tag_name: str) -> int:
    record = resolve_tag(tag_name, root=root)
    print(f"{record['name']}@{record['version']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else (1 if code else 0)

    root = resolve_root(args.root)

    try:
        if args.command == "list":
            return _cmd_list(root)
        if args.command == "versions":
            return _cmd_versions(root, args.name)
        if args.command == "show":
            return _cmd_show(
                root,
                args.name,
                args.prompt_version,
                args.var,
                raw=args.raw,
                no_strict=args.no_strict,
            )
        if args.command == "diff":
            return _cmd_diff(root, args.name, args.version_a, args.version_b)
        if args.command == "tag":
            return _cmd_tag(root, args.name, args.version, args.tag)
        if args.command == "freeze":
            return _cmd_freeze(root)
        if args.command == "log":
            return _cmd_log(root, args.name)
        if args.command == "resolve-tag":
            return _cmd_resolve_tag(root, args.tag)
    except PromptconfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
