"""Git-backed prompt store (working-tree reads; optional commit on write)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from promptconf.backends.filesystem import FilesystemBackend
from promptconf.exceptions import BackendUnavailableError, ValidationError


class GitStoreBackend:
    """Treat a git repository (local path or clone URL) as the prompt root.

    Reads always come from the working tree via an internal
    :class:`~promptconf.backends.filesystem.FilesystemBackend`. Writes update
    the working tree and may optionally ``git add`` + ``git commit``.

    Requires the ``git`` CLI on ``PATH``. Missing git raises
    :class:`~promptconf.exceptions.BackendUnavailableError`.

    Parameters
    ----------
    path_or_url:
        Local git repo path, or a remote clone URL (``https://…``, ``git@…``,
        ``ssh://…``, etc.).
    cache_dir:
        Required when ``path_or_url`` is a remote URL — directory used to clone
        or reuse a local checkout.
    branch:
        Optional branch to checkout after clone / before reads.
    auto_commit:
        When ``True``, :meth:`write` stages and commits changes.
    """

    def __init__(
        self,
        path_or_url: str | Path,
        *,
        cache_dir: str | Path | None = None,
        branch: str | None = None,
        auto_commit: bool = False,
    ) -> None:
        ensure_git_available()
        self.path_or_url = str(path_or_url)
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else None
        self.branch = branch
        self.auto_commit = auto_commit
        self.root = _resolve_repo_root(self.path_or_url, self.cache_dir, branch=branch)
        self._fs = FilesystemBackend(root=self.root)

    def list_prompts(self) -> list[str]:
        return self._fs.list_prompts()

    def list_versions(self, name: str) -> list[str]:
        return self._fs.list_versions(name)

    def read(self, name: str, version: str) -> str:
        return self._fs.read(name, version)

    def resolve_path(self, name: str, version: str):
        return self._fs.resolve_path(name, version)

    def write(self, name: str, version: str, content: str) -> None:
        self._fs.write(name, version, content)
        if self.auto_commit:
            self.commit(f"promptconf: update {name}/{version}")

    def commit(self, message: str, *, paths: list[str] | None = None) -> str:
        """Stage prompt files and create a git commit.

        Returns
        -------
        str
            The new commit SHA (empty string if nothing to commit).
        """
        ensure_git_available()
        if not message or not str(message).strip():
            raise ValidationError("Commit message must be a non-empty string")

        add_args = ["git", "-C", str(self.root), "add"]
        if paths:
            add_args.extend(paths)
        else:
            add_args.append(".")
        _run_git(add_args)

        status = _run_git(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            check=True,
        )
        if not status.stdout.strip():
            return ""

        _run_git(
            ["git", "-C", str(self.root), "commit", "-m", message],
            check=True,
        )
        sha = _run_git(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
        )
        return sha.stdout.strip()

    def __repr__(self) -> str:
        return (
            f"GitStoreBackend(root={str(self.root)!r}, "
            f"branch={self.branch!r}, auto_commit={self.auto_commit})"
        )


def ensure_git_available() -> None:
    """Raise :class:`BackendUnavailableError` when the git binary is missing."""
    if shutil.which("git") is None:
        raise BackendUnavailableError(
            "git binary not found on PATH. Install Git to use GitStoreBackend "
            "(stdlib subprocess; no GitPython required). "
            "See the [git] optional extra in pyproject.toml for documentation."
        )


def _is_remote_url(value: str) -> bool:
    if value.startswith("git@"):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "ssh", "git"}


def _resolve_repo_root(
    path_or_url: str,
    cache_dir: Path | None,
    *,
    branch: str | None,
) -> Path:
    if _is_remote_url(path_or_url):
        if cache_dir is None:
            raise ValidationError(
                "cache_dir is required when path_or_url is a remote git URL"
            )
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Derive a stable folder name from the URL
        name = _cache_name_for_url(path_or_url)
        dest = cache_dir / name
        if dest.is_dir() and (dest / ".git").exists():
            _run_git(["git", "-C", str(dest), "fetch", "--all"], check=False)
            if branch:
                _run_git(
                    ["git", "-C", str(dest), "checkout", branch],
                    check=True,
                )
            return dest.resolve()

        clone_cmd = ["git", "clone"]
        if branch:
            clone_cmd.extend(["--branch", branch])
        clone_cmd.extend([path_or_url, str(dest)])
        result = _run_git(clone_cmd, check=False)
        if result.returncode != 0:
            raise BackendUnavailableError(
                f"Failed to clone {path_or_url!r} into {dest}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return dest.resolve()

    root = Path(path_or_url).expanduser().resolve()
    if not root.is_dir():
        raise BackendUnavailableError(
            f"Git store path does not exist or is not a directory: {root}"
        )
    # Accept a prompts subdirectory inside a repo, or the repo root itself.
    git_dir = _find_git_dir(root)
    if git_dir is None:
        raise BackendUnavailableError(
            f"Path is not inside a git repository: {root}"
        )
    if branch:
        _run_git(["git", "-C", str(root), "checkout", branch], check=True)
    return root


def _find_git_dir(path: Path) -> Path | None:
    current = path
    for _ in range(64):
        candidate = current / ".git"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _cache_name_for_url(url: str) -> str:
    cleaned = url.rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    part = cleaned.split(":")[-1].split("/")[-1]
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in part)
    return safe or "promptconf-git-cache"


def _run_git(
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackendUnavailableError(
            "git binary not found on PATH. Install Git to use GitStoreBackend."
        ) from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise BackendUnavailableError(
            f"git command failed ({' '.join(args)}): {detail}"
        )
    return result
