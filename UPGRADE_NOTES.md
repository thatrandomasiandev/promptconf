# Upgrade notes

## 0.2.x → 0.3.0

### Differentiator: Closed-loop performance ledger

**Closed-loop prompt selection** is promptconf’s production wedge. Version pins, A/B assignments, and usage logs alone tell you *what ran* — not *what won*. The performance ledger (`record_outcome` → `{root}/.promptconf/outcomes.jsonl`) ingests external metrics (reward, thumbs-up, task success) per `(name, version)`. `best_version` aggregates means; `recommend` prefers the empirical winner once `min_samples` is met and otherwise falls back to `ABRouter`. That is the closed loop: ship variants, measure outcomes, promote the prompt that wins in production — without a cloud prompt hub.

### Breaking / behavioral changes

| Change | Migration |
|--------|-----------|
| Empty / whitespace prompt `name` or `version` raises `ValidationError` | Pass non-empty strings; catch `ValidationError` or `PromptconfError`. |
| Path-like prompt names (`"a/b"`, `".."`, …) raise `ValidationError` | Use a single directory name under the prompts root. |
| Oversized prompt files raise `PromptSizeError` | Default cap is `MAX_PROMPT_BYTES` (1 MiB); pass `max_bytes=` to override, or catch `PromptSizeError`. |
| Missing git CLI for `GitStoreBackend` raises `BackendUnavailableError` | Install system `git`, or use `FilesystemBackend`. |

### Compatible additions

- All prior `__init__.py` exports remain; new symbols are additive.
- `load(...)` / `PromptStore` / `search()` signatures unchanged for existing callers; new kwargs default off (`backend=None`, `use_cache=False`, `max_bytes=None`).
- Keyword/regex `search()` behavior unchanged; use `semantic_search` for embedding ranking.
- Optional extras: `[git]` (documents git CLI), `[embeddings]` (`openai`), existing `[jinja]`.

### New optional features

```python
from promptconf import (
    FilesystemBackend,
    GitStoreBackend,
    CompileCache,
    HashEmbedder,
    PerformanceLedger,
    best_version,
    load,
    load_cached,
    recommend,
    record_outcome,
    semantic_search,
)

# Backend
store_text = load("classifier", version="v2", backend=FilesystemBackend("./prompts"), log=False)

# Semantic search
hits = semantic_search("sentiment analysis", root="./prompts", top_k=5)

# Compile cache
text = load("greeter", version="v1", vars={"name": "Ada"}, use_cache=True, log=False)
text = load_cached("greeter", version="v1", vars={"name": "Ada"}, cache=CompileCache("./.cache"), log=False)

# Closed-loop ledger
record_outcome("classifier", "v2", metric=0.91, user_id="u1")
assert best_version("classifier", min_samples=1) == "v2"
version = recommend(
    "classifier",
    user_id="u1",
    experiments={"classifier": {"v1": 0.5, "v2": 0.5}},
)
ledger = PerformanceLedger(root="./prompts")
ledger.record_outcome("classifier", "v1", 0.4)
```