"""Content-hash keyed cache for rendered / compiled prompts."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from promptconf.loader import EngineName


class CompileCache:
    """Filesystem cache of rendered prompts keyed by content + engine + vars.

    Cache entries are invalidated when the source content hash no longer
    matches (covers both content edits and mtime-driven rewrites that change
    bytes). Stale files are deleted on read miss.
    """

    def __init__(self, dir: str | Path) -> None:
        self.dir = Path(dir).expanduser().resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

    def cache_key(
        self,
        *,
        content: str,
        engine: str,
        vars: Mapping[str, Any] | None = None,
        name: str = "",
        version: str = "",
    ) -> str:
        """Return a stable SHA-256 hex digest for the compile inputs."""
        payload = {
            "content": content,
            "engine": engine,
            "vars": _canonical_vars(vars),
            "name": name,
            "version": version,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        """Return cached rendered text, or ``None`` on miss / corruption."""
        path = self._entry_path(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _unlink_quiet(path)
            return None
        if not isinstance(data, dict) or "rendered" not in data:
            _unlink_quiet(path)
            return None
        return str(data["rendered"])

    def put(
        self,
        key: str,
        rendered: str,
        *,
        meta: Mapping[str, Any] | None = None,
    ) -> Path:
        """Store ``rendered`` under ``key``. Returns the entry path."""
        path = self._entry_path(key)
        record: dict[str, Any] = {
            "key": key,
            "rendered": rendered,
            "stored_at": time.time(),
        }
        if meta:
            record["meta"] = dict(meta)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def invalidate(self, key: str) -> bool:
        """Delete a cache entry. Returns ``True`` if a file was removed."""
        path = self._entry_path(key)
        if path.is_file():
            _unlink_quiet(path)
            return True
        return False

    def clear(self) -> int:
        """Remove all cache entries. Returns count of deleted files."""
        removed = 0
        for entry in self.dir.glob("*.json"):
            _unlink_quiet(entry)
            removed += 1
        return removed

    def _entry_path(self, key: str) -> Path:
        safe = "".join(c for c in key if c.isalnum())
        return self.dir / f"{safe}.json"


def load_cached(
    name: str,
    version: str = "latest",
    vars: Mapping[str, Any] | None = None,
    *,
    root: str | Path | None = None,
    strict: bool = True,
    log: bool = True,
    raw: bool = False,
    engine: EngineName = "format",
    cache: CompileCache | None = None,
    cache_dir: str | Path | None = None,
) -> str:
    """Load a prompt using a :class:`CompileCache` (content-hash keyed).

    Equivalent to ``load(..., use_cache=True)`` when ``cache`` / ``cache_dir``
    are provided. Cache key = hash(source content + engine + sorted vars).
    """
    from promptconf.loader import load

    return load(
        name,
        version=version,
        vars=vars,
        root=root,
        strict=strict,
        log=log,
        raw=raw,
        engine=engine,
        use_cache=True,
        cache=cache,
        cache_dir=cache_dir,
    )


def default_cache_dir(root: str | Path | None = None) -> Path:
    """Return ``{root}/.promptconf/cache`` for the resolved prompts root."""
    from promptconf.loader import resolve_root

    return resolve_root(root) / ".promptconf" / "cache"


def _canonical_vars(vars: Mapping[str, Any] | None) -> list[list[Any]]:
    if not vars:
        return []
    items = sorted(vars.items(), key=lambda kv: str(kv[0]))
    return [[str(k), _jsonable(v)] for k, v in items]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
