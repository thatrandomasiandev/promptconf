# Changelog

## 0.3.0

### Added

- **Pluggable store backends** (`promptconf.backends`): `PromptBackend` protocol (`list_prompts`, `list_versions`, `read`, optional `write`); `FilesystemBackend` (default); `GitStoreBackend` (git working-tree reads, optional `commit` / `auto_commit`; clone URL + `cache_dir`; `BackendUnavailableError` when git CLI missing). Extra: `[git]` (documents git CLI dependency; stdlib `subprocess`, no GitPython required).
- **`PromptStore(root=..., backend=...)`** and **`load(..., backend=...)`** additive kwargs (default remains filesystem).
- **Semantic search** (`promptconf.semantic_search`): `HashEmbedder` (stdlib, deterministic), optional `OpenAIEmbedder` behind `[embeddings]`; `semantic_search(query, root=..., top_k=5) → list[SearchHit]` with cosine `score`. Keyword/regex `search()` unchanged.
- **Compile cache** (`promptconf.cache`): `CompileCache(dir)` content-hash keyed (`source + engine + sorted vars + name + version`); `load_cached(...)` and `load(..., use_cache=True)` (optional `cache=` / `cache_dir=`). Invalidates when source content hash changes.
- **Performance ledger** (`promptconf.ledger`) — closed-loop differentiator: `record_outcome`, `best_version`, `recommend` (ledger winner else `ABRouter` fallback); `PerformanceLedger` helper; outcomes at `{root}/.promptconf/outcomes.jsonl`.
- **Exception hierarchy:** `ValidationError`, `BackendUnavailableError`, `PromptSizeError` under `PromptconfError`. Empty names / empty versions / path traversal raise `ValidationError`. Oversized files raise `PromptSizeError` (`MAX_PROMPT_BYTES` / `max_bytes=`).

### Changed

- Package version **0.3.0**.
- All prior public APIs preserved; new symbols and kwargs are additive.

## 0.2.0

- Jinja engine + includes, frontmatter, lint, A/B routing, schema validation, search, CLI (`diff` / `tag` / `freeze` / `log`).
