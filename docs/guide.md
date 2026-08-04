# promptconf

Git-like **prompt version control** for local AI engineering. Treat prompt text files like code modules: versioned paths, `{variable}` / Jinja substitution, tags and lockfiles, deterministic A/B routing, static lint, schema checks, and a local usage/outcome trail that closes the loop.

Requires **Python 3.10+**. Package version: **0.3.0**. Zero hard dependencies; Jinja2 / OpenAI are optional.

## Install

```bash
pip install -e .
pip install -e ".[jinja]"          # Jinja engine
pip install -e ".[embeddings]"     # OpenAI embedder for semantic search
pip install -e ".[git]"            # documents system git CLI (stdlib subprocess; no GitPython)
pip install -e ".[dev]"            # pytest + Jinja2 + hypothesis
```

| Extra | What you get |
|-------|----------------|
| *(none)* | Format-engine load/store/VCS/AB/lint/search/CLI/backends/cache/ledger |
| `[jinja]` | `engine="jinja"` (sandboxed Jinja2) |
| `[embeddings]` | `OpenAIEmbedder` for `semantic_search` |
| `[git]` | Documents git CLI for `GitStoreBackend` (no Python deps) |
| `[dev]` | `pytest` + Jinja2 + hypothesis |

## Directory layout

Default root is `./prompts` (override with `PROMPTCONF_ROOT` or `root=`):

```text
prompts/
  classifier/
    v1.txt
    v2.txt
    latest.txt              # optional; version="latest" prefers this
    v2.schema.json          # optional sidecar schema
  greeter/
    v1.txt
  .promptconf/
    tags.json               # named pointers (tag / resolve_tag)
    usage.jsonl             # load + ab_assignment events (keys only)
    outcomes.jsonl          # performance ledger (record_outcome)
    cache/                  # compile cache (use_cache=True)
  prompt.lock.json          # freeze pins
```

Supported extensions: `.txt`, `.md`, `.prompt` (priority when stems collide: `.txt` ≻ `.md` ≻ `.prompt`).

## Quickstart

```python
import promptconf

prompt = promptconf.load(
    "classifier",
    version="v2",
    vars={"language": "Python", "text": "Shipping this feels great."},
)
```

### Placeholders (`engine="format"`, default)

```text
You are a {language} code classifier.
```

- Missing variables raise `PromptFormatError` when `strict=True` (default).
- Pass `strict=False` to leave unmatched `{placeholders}` as-is.
- Pass `raw=True` to skip formatting (frontmatter still stripped).

### Jinja, includes, and frontmatter

```python
prompt = promptconf.load(
    "agent",
    version="v1",
    engine="jinja",
    vars={"name": "Ada", "items": ["a", "b"]},
)
```

- Expressions / control / macros; `{% include %}` / `{% extends %}` resolve under the prompts root.
- Rendering uses Jinja `SandboxedEnvironment` (unsafe attribute access blocked).
- Without Jinja2 installed → clear `ImportError` pointing at `pip install 'promptconf[jinja]'`.

Optional YAML frontmatter is stripped before render:

```text
---
model: gpt-4
temperature: 0.2
vars:
  name: string
---
Hello {{ name }}
```

```python
meta, body = promptconf.parse_frontmatter(open("prompts/agent/v1.txt").read())
info = promptconf.compile_prompt("agent", "v1", engine="jinja")  # dry-run parse
```

### Version resolution

| Request | Resolution |
|---------|------------|
| `version="v2"` | `{root}/{name}/v2.txt` (or `.md` / `.prompt`) |
| `version="latest"` | `latest.*` if present, else highest numeric `vN` |

Missing versions raise `PromptNotFoundError` with available versions listed. Tags and lock pins are **pointers** — resolve externally, then `load(name, version=…)`.

Worked examples (afternoon onboarding):

| Artifact | Covers |
|----------|--------|
| [`docs/examples/01_load_versions.py`](docs/examples/01_load_versions.py) | Load, `latest`, listing, format strictness |
| [`docs/examples/02_ab_router.py`](docs/examples/02_ab_router.py) | Sticky A/B assignment + usage events |
| [`docs/examples/03_closed_loop.py`](docs/examples/03_closed_loop.py) | Tag, freeze, diff, ledger (`record_outcome` / `best_version` / `recommend`) |

Version-resolution algebra and design rationale: [`docs/theory.tex`](docs/theory.tex) ([PDF](docs/theory.pdf)). See [`UPGRADE_NOTES.md`](UPGRADE_NOTES.md) for the **closed-loop performance ledger** differentiator.

---

## Worked examples

### 1. Load and version resolution

```bash
python docs/examples/01_load_versions.py
```

Creates a temp store, loads `v1` / `v2` / `latest`, and shows strict vs non-strict formatting.

### 2. Deterministic A/B routing

```bash
python docs/examples/02_ab_router.py
```

Same `user_id` always maps to the same variant; omits `user_id` for random weighted draws. Assignments land in `usage.jsonl` with `event: "ab_assignment"`.

### 3. Closed loop (tag → freeze → diff → ledger)

```bash
python docs/examples/03_closed_loop.py
```

Tags a prod pin, freezes `prompt.lock.json`, diffs versions, records ledger outcomes, then prints `best_version` / `recommend` alongside the usage trail.

Also see [`examples/`](examples/) for a checked-in prompt tree:

```bash
cd examples && python load_example.py
```

---

## CLI reference

After install, the `promptconf` command is available:

```bash
promptconf [--version] [--root PATH] <command> ...
```

Global options:

| Flag | Description |
|------|-------------|
| `--root PATH` | Prompts root (default: `PROMPTCONF_ROOT` or `./prompts`) |
| `--version` | Print package version and exit |

### Commands

| Command | Description |
|---------|-------------|
| `list` | List prompt names |
| `versions <name>` | List versions for a prompt |
| `show <name>` | Load/print a prompt |
| `diff <name> --a A --b B` | Unified diff between two versions (raw bodies) |
| `tag <name> <version> <tag>` | Write tag → `{root}/.promptconf/tags.json` |
| `resolve-tag <tag>` | Print `name@version` for a tag |
| `freeze` | Pin each prompt's latest resolved version → `{root}/prompt.lock.json` |
| `log <name>` | Print `usage.jsonl` records for a prompt (JSON lines) |

### `show` options

| Flag | Default | Description |
|------|---------|-------------|
| `--version LABEL` | `latest` | Version stem or `latest` |
| `--var KEY=VALUE` | — | Template variable (repeatable) |
| `--raw` | off | Skip variable formatting |
| `--no-strict` | off | Leave missing placeholders unchanged |

`show` does **not** append usage log lines (`log=False`). Exit codes: `0` success, `1` `PromptconfError`, `2` bad CLI/`ValueError`.

```bash
promptconf list
promptconf versions classifier
promptconf show classifier --version v2 --var language=Python --var text=hello
promptconf diff classifier --a v1 --b v2
promptconf tag classifier v2 prod
promptconf resolve-tag prod
promptconf freeze
promptconf log classifier
```

---

## Library usage

```python
from promptconf import PromptStore, FilesystemBackend, load, list_prompts, list_versions

store = PromptStore(root="./prompts")
text = store.load("greeter", vars={"name": "Ada"})
print(list_prompts(root="./prompts"))
print(list_versions("classifier", root="./prompts"))

# Pluggable backend (default FilesystemBackend)
store = PromptStore(root="./prompts", backend=FilesystemBackend("./prompts"))
```

### Tags, freeze, diff, usage log

```python
from promptconf import diff_versions, freeze, log, resolve_tag, tag

diff_versions("classifier", "v1", "v2", root="./prompts")
tag("classifier", "v2", "prod", root="./prompts")
pin = resolve_tag("prod", root="./prompts")  # {"name": "classifier", "version": "v2"}
freeze(root="./prompts")                     # writes prompt.lock.json
records = log("classifier", root="./prompts")
```

### Lint, schema, A/B, search

```python
from promptconf import (
    ABRouter,
    LintRules,
    lint_all,
    lint_prompt,
    load_validated,
    search,
    validate_vars,
)

issues = lint_prompt(
    text,
    rules={
        "max_chars": 4000,
        "banned_phrases": ["ignore previous instructions"],
        "require_placeholders": ["text"],
        "no_trailing_whitespace": True,
        "json_mode_hint": True,  # or "require" / "forbid"
    },
)
lint_all(root="./prompts", rules=LintRules(max_chars=8000))

validate_vars({"name": "Ada"}, {"name": "string"})
load_validated("greeter", version="v1", vars={"name": "Ada"})

router = ABRouter({"classifier": {"v1": 0.5, "v2": 0.5}}, root="./prompts")
version = router.choose("classifier", user_id="user-42")  # sticky
text = router.load("classifier", user_id="user-42", vars={"text": "hi"})

hits = search("sentiment", root="./prompts")
hits = search(r"sentim\w+", root="./prompts", regex=True, limit=10)
```

### Backends, semantic search, cache, ledger

```python
from promptconf import (
    CompileCache,
    FilesystemBackend,
    GitStoreBackend,
    HashEmbedder,
    PerformanceLedger,
    best_version,
    load,
    load_cached,
    recommend,
    record_outcome,
    semantic_search,
)

# Backend-backed load
text = load("classifier", version="v2", backend=FilesystemBackend("./prompts"), log=False)

# Git working tree (requires `git` on PATH)
git = GitStoreBackend("/path/to/prompts-repo")
git.commit("message")  # after write(...)

# Semantic search (HashEmbedder default; OpenAI via [embeddings])
hits = semantic_search("sentiment analysis", root="./prompts", top_k=5)

# Compile cache
text = load("greeter", version="v1", vars={"name": "Ada"}, use_cache=True, log=False)
text = load_cached("greeter", version="v1", vars={"name": "Ada"}, cache=CompileCache("./.cache"), log=False)

# Closed-loop performance ledger
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

Schema sources (first match wins for `load_schema_for`):

1. Sidecar `{version}.schema.json` next to the prompt file
2. Frontmatter `vars:` or `schema:`

---

## API reference

Every public symbol from `promptconf.__all__`.

### Version

| Symbol | Description |
|--------|-------------|
| `__version__` | Package version string (`"0.3.0"`). |

### Load & discovery

| Symbol | Description |
|--------|-------------|
| `resolve_root` | Resolve prompts root: explicit `root` → `PROMPTCONF_ROOT` → `./prompts`. |
| `list_prompts` | Sorted prompt directory names (skip `.`-prefixed dirs). |
| `list_versions` | Version stems for a prompt; numeric `vN` ascending, then other stems, `latest` last. |
| `MAX_PROMPT_BYTES` | Default max prompt file size (**1 MiB**). Override per call with `max_bytes=`. |
| `load` | Resolve, strip frontmatter, format/render; optional usage log. Args: `name`, `version="latest"`, `vars`, `root`, `strict=True`, `log=True`, `raw=False`, `engine="format"|"jinja"`, `backend=None`, `use_cache=False`, `cache=None`, `cache_dir=None`, `max_bytes=None`. Oversized files → `PromptSizeError`. |
| `compile_prompt` | Dry-run parse validation; returns `name`, `version`, `resolved_version`, `path`, `engine`, `metadata`, `body`. Default engine `"jinja"`. Optional `backend=`. |
| `PromptStore` | Bound loader with fixed `root` and optional `backend=` (defaults to `FilesystemBackend`); methods `load`, `compile_prompt`, `list_prompts`, `list_versions`. |

### Frontmatter & schema

| Symbol | Description |
|--------|-------------|
| `parse_frontmatter` | Split leading `---` YAML subset → `(metadata, body)`. |
| `load_schema_for` | Discover schema from sidecar JSON or frontmatter `vars`/`schema`; `None` if absent. |
| `validate_vars` | Validate `vars` against simple `{name: type}` or JSON Schema object form; raises `PromptSchemaError` when `strict=True`. |
| `load_validated` | `validate_vars` then `load`; discovers schema when `schema=` omitted. |

### VCS helpers

| Symbol | Description |
|--------|-------------|
| `tag` | Associate `tag_name` with `name`@`version` in `.promptconf/tags.json`; validates version exists. |
| `resolve_tag` | Look up tag → `{"name", "version"}`; raises `PromptNotFoundError` if unknown. |
| `freeze` | Write `prompt.lock.json` pins (`latest` stem if present, else highest `vN`); touch-loads each pin. |
| `log` | Filter `.promptconf/usage.jsonl` to records for one prompt name. |
| `diff_versions` | Unified diff of raw bodies between two versions (`log=False`). |

### A/B routing

| Symbol | Description |
|--------|-------------|
| `ABRouter` | Weighted experiments map; `choose(name, user_id=None)` sticky via SHA-256 when `user_id` set, else seeded random; `load(...)` chooses then calls `load`. Logs `event: "ab_assignment"` when `log=True`. |

### Lint

| Symbol | Description |
|--------|-------------|
| `LintRules` | Config: `max_chars`, `banned_phrases`, `require_placeholders`, `no_trailing_whitespace`, `json_mode_hint`. |
| `LintIssue` | Finding: `rule`, `message`, `severity`, optional `name`/`version`/`path`; `to_dict()`. |
| `lint_prompt` | Lint one body → `list[LintIssue]`. |
| `lint_all` | Lint every supported file under root (optional `names=` filter). |

### Search

| Symbol | Description |
|--------|-------------|
| `SearchHit` | Ranked hit: `name`, `version`, `path`, `snippet`, `score`, `match_start`, `match_end`; `to_dict()`. |
| `search` | Substring or `regex=True` search; `case_sensitive`, `names`, `limit`, `context`. |
| `semantic_search` | Embedding cosine ranking → `list[SearchHit]`; `top_k`, optional `embedder`. |
| `HashEmbedder` | Deterministic stdlib bag-of-words embedder. |
| `OpenAIEmbedder` | OpenAI embeddings (`[embeddings]` extra). |
| `EmbeddingClient` | Protocol for custom embedders. |

### Backends

| Symbol | Description |
|--------|-------------|
| `PromptBackend` | Protocol: `list_prompts`, `list_versions`, `read`, optional `write`. |
| `FilesystemBackend` | Default local filesystem store. |
| `GitStoreBackend` | Git working-tree store; optional `commit` / clone URL + `cache_dir`. |

### Cache & ledger

| Symbol | Description |
|--------|-------------|
| `CompileCache` | Content-hash keyed render cache (`source + engine + sorted vars + name + version`). |
| `load_cached` | `load(..., use_cache=True)` helper. |
| `record_outcome` | Append metric to `.promptconf/outcomes.jsonl`. |
| `best_version` | Highest mean metric version (respects `min_samples`). |
| `recommend` | Ledger winner else `ABRouter` fallback. |
| `PerformanceLedger` | Bound helper around the outcomes API. |

### Exceptions

| Symbol | Description |
|--------|-------------|
| `PromptconfError` | Base exception. |
| `PromptNotFoundError` | Unknown prompt, version, or tag. |
| `PromptFormatError` | Format/Jinja substitution or template failure. |
| `PromptSchemaError` | Variable schema validation failure. |
| `PromptLintError` | Reserved for hard-fail lint workflows (subclass of `PromptconfError`; not auto-raised by `lint_prompt` / `lint_all`, which return issues). |
| `PromptSizeError` | Prompt file exceeds `MAX_PROMPT_BYTES` (or `max_bytes=`). |
| `ValidationError` | Empty / invalid name or version; also a `ValueError`. Path traversal / null bytes rejected the same way. |
| `BackendUnavailableError` | Backend missing or unusable (e.g. git CLI not on `PATH`). |

---

## Troubleshooting / FAQ

### Prompt not found

**Symptom:** `PromptNotFoundError: Prompt '…' not found under '…'` or version missing (exit `1` on CLI).

**Fix:** Confirm `--root` / `PROMPTCONF_ROOT` / `root=` points at the directory that contains prompt **folders**. Run `promptconf list` and `promptconf versions <name>`. Supported files are `.txt` / `.md` / `.prompt` only.

### Missing variables / leftover `{placeholders}`

**Symptom:** `PromptFormatError: Missing required prompt variable(s): …` or output still contains `{name}`.

**Cause:** `strict=True` (default) requires every format field root key; `strict=False` leaves missing keys literal; `raw=True` skips formatting entirely.

**Fix:** Pass all keys in `vars=` / `--var`, or use `--no-strict` / `strict=False` deliberately. For Jinja, missing names use `StrictUndefined` when strict.

### `latest` is not the highest `vN`

**Symptom:** `version="latest"` loads `latest.txt` even though `v10` exists.

**Cause:** An explicit `latest.*` file **wins** over max numeric `vN`. This is intentional (alias, not semver max).

**Fix:** Remove or update `latest.*`, or pass an explicit `version="v10"`. `freeze` pins the same preference.

### Tags do not change `load("…", version="latest")`

**Symptom:** After `promptconf tag classifier v2 prod`, `load("classifier")` still resolves via `latest` algebra.

**Cause:** Tags are named pointers stored in `tags.json`; they are **not** auto-applied inside `load()`.

**Fix:**

```python
pin = resolve_tag("prod", root=root)
text = load(pin["name"], version=pin["version"], root=root, vars=…)
```

Same pattern for `prompt.lock.json` pins from `freeze()`.

### Jinja ImportError

**Symptom:** `ImportError: Jinja2 is required for engine='jinja'…`

**Fix:** `pip install 'promptconf[jinja]'` (or `.[dev]`). Format engine needs no extra.

### Usage log has keys but not values

**Symptom:** `.promptconf/usage.jsonl` shows `vars_keys` only.

**Cause:** By design — values are never written, to reduce PII/secret leakage.

**Fix:** Correlate externally if you need value-level analytics; do not expect secrets in the trail.

### A/B assignment not sticky

**Symptom:** Same user gets different variants across calls.

**Cause:** Sticky hashing requires `user_id=`; without it, `ABRouter` draws from its RNG (seedable via `seed=`).

**Fix:** Pass a stable `user_id` string. Rebuild `ABRouter` with the same `seed` only if you need reproducible *random* draws without user IDs.

### Schema / lint confusion

**Symptom:** `PromptSchemaError` vs empty lint issue list.

**Cause:** Schema (`validate_vars` / `load_validated`) checks **variable types**; lint (`lint_prompt`) checks **prose/static** rules on text. They are independent. `PromptLintError` is not raised automatically — callers decide whether to hard-fail on error-severity `LintIssue`s.

### Prompt file too large

**Symptom:** `PromptSizeError: … exceeds max size …`

**Cause:** Files larger than `MAX_PROMPT_BYTES` (1 MiB) or an explicit `max_bytes=` are rejected before render.

**Fix:** Split the prompt, pass a higher `max_bytes=` deliberately for known-large assets, or catch `PromptSizeError` / `PromptconfError`.

### Backend unavailable

**Symptom:** `BackendUnavailableError` when constructing or using `GitStoreBackend`.

**Cause:** System `git` binary missing from `PATH`, or clone/working-tree setup failed.

**Fix:** Install git / ensure it is on `PATH`. Prefer `FilesystemBackend` when you do not need a git working tree.

---

## Documentation map

| Doc | Description |
|-----|-------------|
| [`docs/theory.tex`](docs/theory.tex) ([PDF](docs/theory.pdf)) | Resolution algebra, templates, A/B hash, lint, design justifications |
| [`docs/examples/`](docs/examples/) | Load, A/B, and closed-loop worked examples |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`UPGRADE_NOTES.md`](UPGRADE_NOTES.md) | Upgrade guidance and product differentiator |
| [`docs/README.md`](docs/README.md) | Docs index |

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
