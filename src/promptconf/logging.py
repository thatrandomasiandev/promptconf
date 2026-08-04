"""Local JSONL usage logging for prompt loads."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows / non-POSIX
    fcntl = None  # type: ignore[assignment]


def append_usage_log(
    root: Path,
    *,
    name: str,
    version: str,
    resolved_version: str,
    path: Path,
    var_keys: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one usage event to ``{root}/.promptconf/usage.jsonl``.

    Only variable *keys* are recorded — never values — to avoid leaking secrets.
    Optional ``extra`` fields (e.g. A/B assignment metadata) are merged in.

    Writes are exclusive-locked (``fcntl.flock`` on POSIX) so concurrent
    ``load(log=True)`` callers do not interleave JSONL lines.
    """
    log_dir = root / ".promptconf"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "usage.jsonl"

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name,
        "version": version,
        "resolved_version": resolved_version,
        "path": str(path),
        "vars_keys": var_keys,
    }
    if extra:
        record.update(extra)

    line = json.dumps(record, ensure_ascii=False) + "\n"
    with log_path.open("a", encoding="utf-8") as fh:
        _lock_file(fh)
        try:
            fh.write(line)
            fh.flush()
        finally:
            _unlock_file(fh)


def _lock_file(fh: Any) -> None:
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        return
    if sys.platform == "win32":  # pragma: no cover
        try:
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            pass


def _unlock_file(fh: Any) -> None:
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return
    if sys.platform == "win32":  # pragma: no cover
        try:
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
