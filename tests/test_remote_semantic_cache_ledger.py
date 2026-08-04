"""Tests for backends, semantic search, compile cache, and performance ledger."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import promptconf
from promptconf import (
    ABRouter,
    BackendUnavailableError,
    CompileCache,
    FilesystemBackend,
    GitStoreBackend,
    HashEmbedder,
    PerformanceLedger,
    PromptStore,
    SearchHit,
    ValidationError,
    best_version,
    load_cached,
    recommend,
    record_outcome,
    semantic_search,
)
from promptconf.backends.git_store import ensure_git_available


def _write_prompt(root: Path, name: str, version: str, content: str) -> Path:
    prompt_dir = root / name
    prompt_dir.mkdir(parents=True, exist_ok=True)
    path = prompt_dir / f"{version}.txt"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def prompts_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    _write_prompt(root, "classifier", "v1", "Classify sentiment of: {text}")
    _write_prompt(root, "classifier", "v2", "You are a sentiment analysis classifier.\n{text}")
    _write_prompt(root, "greeter", "v1", "Hello, {name}!")
    _write_prompt(root, "docs", "v1", "Write API documentation for endpoints.")
    return root


# ---------------------------------------------------------------------------
# Validation / errors
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_name_raises(self, prompts_root: Path) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            promptconf.load("", version="v1", root=prompts_root, log=False)

    def test_whitespace_name_raises(self, prompts_root: Path) -> None:
        with pytest.raises(ValidationError):
            promptconf.load("   ", version="v1", root=prompts_root, log=False)

    def test_empty_version_raises(self, prompts_root: Path) -> None:
        with pytest.raises(ValidationError, match="version"):
            promptconf.load("greeter", version="", root=prompts_root, log=False)

    def test_path_like_name_raises(self, prompts_root: Path) -> None:
        with pytest.raises(ValidationError, match="Invalid prompt name"):
            promptconf.load("a/b", version="v1", root=prompts_root, log=False)

    def test_error_hierarchy(self) -> None:
        assert issubclass(ValidationError, promptconf.PromptconfError)
        assert issubclass(BackendUnavailableError, promptconf.PromptconfError)
        assert issubclass(ValidationError, ValueError)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class TestFilesystemBackend:
    def test_list_and_read(self, prompts_root: Path) -> None:
        backend = FilesystemBackend(root=prompts_root)
        assert "classifier" in backend.list_prompts()
        assert backend.list_versions("classifier") == ["v1", "v2"]
        text = backend.read("classifier", "v1")
        assert "Classify sentiment" in text

    def test_write_roundtrip(self, prompts_root: Path) -> None:
        backend = FilesystemBackend(root=prompts_root)
        backend.write("greeter", "v2", "Hi {name}")
        assert backend.read("greeter", "v2") == "Hi {name}"

    def test_load_with_backend(self, prompts_root: Path) -> None:
        backend = FilesystemBackend(root=prompts_root)
        text = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            backend=backend,
            log=False,
        )
        assert text == "Hello, Ada!"

    def test_prompt_store_default_backend(self, prompts_root: Path) -> None:
        store = PromptStore(root=prompts_root)
        assert isinstance(store.backend, FilesystemBackend)
        assert store.list_prompts() == sorted(["classifier", "docs", "greeter"])
        assert "Ada" in store.load("greeter", version="v1", vars={"name": "Ada"}, log=False)

    def test_prompt_store_custom_backend(self, prompts_root: Path) -> None:
        backend = FilesystemBackend(root=prompts_root)
        store = PromptStore(root=prompts_root, backend=backend)
        assert store.backend is backend


class TestGitStoreBackend:
    def test_local_repo_read(self, tmp_path: Path) -> None:
        try:
            ensure_git_available()
        except BackendUnavailableError:
            pytest.skip("git not available")

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        _write_prompt(repo, "agent", "v1", "Act as {role}")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        backend = GitStoreBackend(repo)
        assert backend.read("agent", "v1") == "Act as {role}"
        backend.write("agent", "v2", "Be a {role}")
        sha = backend.commit("add v2")
        assert sha
        assert backend.read("agent", "v2") == "Be a {role}"

    def test_missing_git_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(shutil, "which", lambda _cmd: None)
        with pytest.raises(BackendUnavailableError, match="git binary"):
            GitStoreBackend(tmp_path)

    def test_remote_url_requires_cache_dir(self) -> None:
        try:
            ensure_git_available()
        except BackendUnavailableError:
            pytest.skip("git not available")
        with pytest.raises(ValidationError, match="cache_dir"):
            GitStoreBackend("https://example.com/prompts.git")


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    def test_returns_search_hits(self, prompts_root: Path) -> None:
        hits = semantic_search("sentiment analysis", root=prompts_root, top_k=3)
        assert hits
        assert all(isinstance(h, SearchHit) for h in hits)
        assert hits[0].score >= hits[-1].score
        # classifier/v2 is the closest semantic match for this query
        assert hits[0].name == "classifier"

    def test_hash_embedder_deterministic(self) -> None:
        emb = HashEmbedder(dim=64)
        a = emb.embed(["hello world"])[0]
        b = emb.embed(["hello world"])[0]
        assert a == b

    def test_empty_query(self, prompts_root: Path) -> None:
        assert semantic_search("", root=prompts_root) == []

    def test_keyword_search_unchanged(self, prompts_root: Path) -> None:
        hits = promptconf.search("sentiment", root=prompts_root)
        assert hits
        assert any(h.name == "classifier" for h in hits)


# ---------------------------------------------------------------------------
# Compile cache
# ---------------------------------------------------------------------------


class TestCompileCache:
    def test_load_use_cache(self, prompts_root: Path, tmp_path: Path) -> None:
        cache = CompileCache(tmp_path / "cache")
        text1 = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
            use_cache=True,
            cache=cache,
        )
        assert text1 == "Hello, Ada!"
        assert list(cache.dir.glob("*.json"))

        text2 = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
            use_cache=True,
            cache=cache,
        )
        assert text2 == text1

    def test_load_cached_helper(self, prompts_root: Path, tmp_path: Path) -> None:
        cache = CompileCache(tmp_path / "c2")
        text = load_cached(
            "greeter",
            version="v1",
            vars={"name": "Bob"},
            root=prompts_root,
            log=False,
            cache=cache,
        )
        assert text == "Hello, Bob!"

    def test_invalidate_on_content_change(self, prompts_root: Path, tmp_path: Path) -> None:
        cache = CompileCache(tmp_path / "c3")
        promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
            use_cache=True,
            cache=cache,
        )
        _write_prompt(prompts_root, "greeter", "v1", "Hey, {name}!")
        text = promptconf.load(
            "greeter",
            version="v1",
            vars={"name": "Ada"},
            root=prompts_root,
            log=False,
            use_cache=True,
            cache=cache,
        )
        assert text == "Hey, Ada!"

    def test_different_vars_different_keys(self, tmp_path: Path) -> None:
        cache = CompileCache(tmp_path / "c4")
        k1 = cache.cache_key(content="Hi {name}", engine="format", vars={"name": "A"})
        k2 = cache.cache_key(content="Hi {name}", engine="format", vars={"name": "B"})
        assert k1 != k2


# ---------------------------------------------------------------------------
# Performance ledger
# ---------------------------------------------------------------------------


class TestPerformanceLedger:
    def test_record_and_best_version(self, prompts_root: Path) -> None:
        record_outcome("classifier", "v1", 0.4, root=prompts_root)
        record_outcome("classifier", "v1", 0.5, root=prompts_root)
        record_outcome("classifier", "v2", 0.9, root=prompts_root)
        record_outcome("classifier", "v2", 0.8, root=prompts_root)

        assert best_version("classifier", root=prompts_root, min_samples=2) == "v2"

        path = prompts_root / ".promptconf" / "outcomes.jsonl"
        assert path.is_file()
        lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert len(lines) == 4
        assert lines[0]["metric_key"] == "reward"

    def test_best_version_respects_min_samples(self, prompts_root: Path) -> None:
        record_outcome("classifier", "v2", 1.0, root=prompts_root)
        assert best_version("classifier", root=prompts_root, min_samples=2) is None
        assert best_version("classifier", root=prompts_root, min_samples=1) == "v2"

    def test_recommend_prefers_ledger(self, prompts_root: Path) -> None:
        record_outcome("classifier", "v2", 0.95, root=prompts_root)
        record_outcome("classifier", "v1", 0.1, root=prompts_root)
        version = recommend(
            "classifier",
            root=prompts_root,
            experiments={"classifier": {"v1": 0.9, "v2": 0.1}},
            min_samples=1,
        )
        assert version == "v2"

    def test_recommend_falls_back_to_ab(self, prompts_root: Path) -> None:
        router = ABRouter(
            {"classifier": {"v1": 1.0, "v2": 0.0}},
            root=prompts_root,
            log=False,
            seed=1,
        )
        version = recommend(
            "classifier",
            root=prompts_root,
            user_id="user-1",
            router=router,
            min_samples=5,
        )
        assert version == "v1"

    def test_ledger_class(self, prompts_root: Path) -> None:
        ledger = PerformanceLedger(root=prompts_root)
        ledger.record_outcome("greeter", "v1", 0.7, user_id="u1", metadata={"src": "test"})
        assert ledger.best_version("greeter") == "v1"
        assert ledger.read_outcomes("greeter")[0]["metadata"]["src"] == "test"

    def test_record_outcome_validation(self, prompts_root: Path) -> None:
        with pytest.raises(ValidationError):
            record_outcome("", "v1", 1.0, root=prompts_root)
        with pytest.raises(ValidationError):
            record_outcome("classifier", "", 1.0, root=prompts_root)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_version(self) -> None:
        assert promptconf.__version__ == "0.3.0"

    def test_new_symbols_exported(self) -> None:
        for name in (
            "FilesystemBackend",
            "GitStoreBackend",
            "CompileCache",
            "HashEmbedder",
            "OpenAIEmbedder",
            "PerformanceLedger",
            "ValidationError",
            "BackendUnavailableError",
            "semantic_search",
            "load_cached",
            "record_outcome",
            "best_version",
            "recommend",
        ):
            assert hasattr(promptconf, name)
