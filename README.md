# promptconf

Formal **theory** document for `promptconf` v0.3.0.

| | |
|---|---|
| **Usage & API guide** | [docs/guide.md](docs/guide.md) |
| **Theory PDF** | [docs/theory.pdf](docs/theory.pdf) |
| **LaTeX source** | [docs/theory.tex](docs/theory.tex) |
| **Examples** | [docs/examples/](docs/examples/) · [examples/](examples/) |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |

---
# Problem statement

Prompts are software artifacts: edited often, A/B tested, and easy to lose track of when inlined as string literals. `promptconf` provides an offline, git-friendly store:
``` math
\begin{equation}
  \mathrm{load}(n,\, v,\, x;\; R,\, e,\, B) \;\longrightarrow\; \text{string}
\end{equation}
```
where $`n`$ is the prompt name, $`v`$ a version selector, $`x`$ template variables, $`R`$ the root, $`e \in \{\texttt{format},\texttt{jinja}\}`$ the engine, and $`B`$ an optional `PromptBackend`.

Root resolution precedence: explicit `root` $`\rightarrow`$ env `PROMPTCONF_ROOT` $`\rightarrow`$ `./prompts`. Bound API: `PromptStore(root=…, backend=…)`.

# Store geometry

    R / n /  {v}.{txt,md,prompt}

- Prompt **names** $`=`$ immediate subdirectories of $`R`$ (skip `.`–prefixed dirs).

- Version **stems** are file stems under $`R/n/`$.

- Extension priority when stems collide: `.txt` $`\succ`$ `.md` $`\succ`$ `.prompt`.

- Optional YAML frontmatter (`---` … `---`) is stripped before render; `compile_prompt` exposes metadata $`+`$ body.

- Empty / path-like names and empty versions $`\rightarrow`$ `ValidationError`.

- Files larger than `MAX_PROMPT_BYTES` (1 MiB, overridable via `max_bytes=`) $`\rightarrow`$ `PromptSizeError`.

Version stem classes:

1.  Numeric releases matching `^v(\d+)$` (case-insensitive): `v1`, `v2`, `v10`.

2.  Alias file stem `latest` (optional).

3.  Arbitrary other stems (listed alphabetically between numerics and `latest`).

# Version resolution algebra

Define $`V(n)`$ as the set of available stems for prompt $`n`$.

## Explicit version

``` math
\begin{equation}
  \mathrm{resolve}(n,\, v) \;=\;
  \begin{cases}
    \mathrm{path}(v) & \text{if } v \in V(n) \\
    \bot& \text{otherwise (raises \texttt{PromptNotFoundError})}
  \end{cases}
\end{equation}
```

## `version="latest"` (floating alias)

``` math
\begin{equation}
  \mathrm{resolve}(n,\, \texttt{latest}) \;=\;
  \begin{cases}
    \mathrm{path}(\texttt{latest})
      & \text{if } \texttt{latest} \in V(n) \\[0.4em]
    \mathrm{path}(v_{k^{*}})
      & \text{if } k^{*} = \max\{k : v_k \in V(n)\} \\[0.4em]
    \bot
      & \text{otherwise}
  \end{cases}
\end{equation}
```

An explicit `latest.*` file **wins** over the highest numeric `vN`. This is intentional: `latest` is an alias, not “max semver.”

## Tags (named pointers)

`tag(name, version, tag_name)` writes `{root}/.promptconf/tags.json`:
``` math
\begin{equation}
  \mathrm{tags}[\textit{tag\_name}] \;=\; \{\textit{name}: n,\;
  \textit{version}: v\}
\end{equation}
```
`resolve_tag(tag_name)` returns that record. Tags are **not** auto-applied inside `load()`; callers resolve then `load(name, version=…)`. Validation ensures the target version exists before writing.

## Lock file (`freeze`)

`freeze(root=…)` writes `{root}/prompt.lock.json` mapping each prompt name $`\rightarrow`$ a pin:

1.  Prefer stem `"latest"` if present in $`V(n)`$,

2.  Else highest numeric $`vN`$,

3.  Else last listed version.

Each pin is touch-resolved via `load(…, raw=True)` so broken pins fail at freeze time. The lock is a **reproducibility artifact** for CI and deploys; `load()` itself still takes an explicit `version=` (or `"latest"`) — use lock pins as the version argument at call sites or in wrappers.

<figure id="fig:version-flow" data-latex-placement="htbp">

<figcaption>Version selectors funnel into path resolution, then template rendering. Tags and lock pins resolve externally to a concrete <code>version=</code> before <code>load</code>.</figcaption>
</figure>

## Listing order

Numeric $`v_k`$ ascending $`\rightarrow`$ other non-`latest` stems alpha $`\rightarrow`$ `latest` last. Used by `list_versions` and error messages.

# Pluggable backends

`PromptBackend` protocol:

| **Method** | **Role** |
|:---|:---|
| `list_prompts()` | Sorted names |
| `list_versions(name)` | Sorted stems |
| `read(name, version)` | Raw file text (incl. frontmatter) |
| `write(name, version, content)` | Optional; read-only backends may omit / error |

`PromptBackend` protocol methods. {#tab:backend-protocol}

#### FilesystemBackend.

Default; wraps the geometry in Section <a href="#sec:store" data-reference-type="ref" data-reference="sec:store">2</a>.

#### GitStoreBackend.

Treat a local git path (or clone URL $`+`$ `cache_dir`) as prompt root; `read` from working tree; optional `commit` / `auto_commit`. Missing `git` CLI $`\rightarrow`$ `BackendUnavailableError` (stdlib `subprocess`; `[git]` extra documents the dependency).

`load(…, backend=B)` and `PromptStore(…, backend=B)` are additive. When `backend` is omitted, `load` uses the filesystem path directly; `PromptStore` defaults to `FilesystemBackend(root)`.

# Template engines

## `engine="format"` (default)

Substitution via `str.format_map` / `string.Formatter`:
``` math
\begin{equation}
  T(x) \;=\; \mathrm{format}(T_0,\, x)
\end{equation}
```

| **Mode**       | **Behavior**                                          |
|:---------------|:------------------------------------------------------|
| `strict=True`  | Missing root keys $`\rightarrow`$ `PromptFormatError` |
| `strict=False` | Missing keys left as literal `{key}`                  |
| `raw=True`     | Skip formatting; return body after frontmatter strip  |

Format-engine modes. {#tab:format-modes}

Root keys are the field names before `.` / `[` indexing. Fail-closed strict mode prevents silent quality regressions from incomplete instantiation.

## `engine="jinja"` (optional `[jinja]` extra)

Rendering uses `jinja2.sandbox.SandboxedEnvironment` with `PromptIncludeLoader` rooted at $`R`$:

- Context variables: `{{ var }}`, control: `{% if %}`, macros, etc.

- Includes / extends resolve under the prompt root.

- `StrictUndefined` when `strict=True`; soft undefined preserves `{{ name }}` when not strict.

- Unsafe attributes (`__*__`, `mro`, frame/code attrs, etc.) blocked via custom `is_safe_attribute`.

- `SecurityError` / syntax / missing includes surface as `PromptFormatError` or `PromptNotFoundError`.

`compile_prompt` dry-runs parse validation without rendering (Jinja parse or `Formatter().parse` for format engine).

## Compile cache

`CompileCache(dir)` stores rendered strings under:
``` math
\begin{equation}
  k \;=\; \mathrm{SHA256}\!\bigl(
    \mathrm{canonical}(
      \textit{content},\, e,\, x_{\mathrm{sorted}},\, n,\, v
    )
  \bigr)
\end{equation}
```

`load(…, use_cache=True)` / `load_cached(…)` hit the cache when $`k`$ matches. Content edits change the hash $`\rightarrow`$ automatic invalidation (mtime alone is insufficient; bytes are authoritative). Default cache dir: `{root}/.promptconf/cache`.

## Usage logging

When `log=True`, appends JSONL under `{root}/.promptconf/usage.jsonl` with **keys only** (never values) — reduces PII/secret leakage into the audit trail. `log(name)` (VCS helper) filters that file by prompt name.

# A/B hashing

`ABRouter(experiments, root=…, seed=…)` holds per-prompt weight maps $`\{v_i \mapsto w_i\}`$ normalized to $`\sum_i w_i = 1`$.

## Deterministic assignment

When `user_id` is provided:
``` math
\begin{equation}
  b \;=\;
  \frac{\mathrm{int}_{16}\!\bigl(\mathrm{SHA256}(n{:}u)[:8]\bigr)}
       {2^{32}-1}
  \;\in\; [0,\,1)
\end{equation}
```
Then pick the first variant whose cumulative weight exceeds $`b`$ (last variant is the residual). Sticky assignment: same $`(n,\, u)`$ always maps to the same variant.

## Random assignment

Without `user_id`, draw $`b \sim U[0,1)`$ from an optional seeded `random.Random`.

`choose` may log an `ab_assignment` usage event; `load` chooses then calls `promptconf.loader.load` for that version.

# Closed-loop performance ledger

**Differentiator.** Pins, tags, and A/B logs describe *what ran*. The ledger answers *which prompt wins in production*.

Outcomes append to `{root}/.promptconf/outcomes.jsonl`:
``` math
\begin{equation}
  o_t \;=\; (n,\, v,\, m_k,\, m,\, u,\, \ldots)
\end{equation}
```
where $`m_k`$ defaults to `"reward"` and $`m \in \mathbb{R}`$ is an external metric (task success, thumbs-up, latency inverse, …).

## Aggregation

``` math
\begin{equation}
  \mathrm{best\_version}(n;\, m_k,\, s_{\min}) \;=\;
  \operatorname*{argmax}_{v\,:\, |O_{n,v,m_k}| \,\ge\, s_{\min}}
  \mathrm{mean}(O_{n,v,m_k})
\end{equation}
```
Ties break by larger sample count, then version label. Returns $`\emptyset`$ when no version meets $`s_{\min}`$.

## Recommend

``` math
\begin{equation}
  \mathrm{recommend}(n,\, u) \;=\;
  \begin{cases}
    \mathrm{best\_version}(n)
      & \text{if defined} \\[0.3em]
    \mathrm{ABRouter.choose}(n,\, u)
      & \text{otherwise}
  \end{cases}
\end{equation}
```

This closes the loop: ship weighted variants $`\rightarrow`$ ingest outcomes $`\rightarrow`$ promote winners without a cloud prompt hub.

Public surface: `record_outcome`, `best_version`, `recommend`, and bound helper `PerformanceLedger(root=…, router=…)`. Outcomes live at `{root}/.promptconf/outcomes.jsonl` (separate from `usage.jsonl`).

<figure id="fig:ledger-loop" data-latex-placement="htbp">

<figcaption>Closed-loop ledger: A/B cold-start, metric ingest, winner promotion.</figcaption>
</figure>

# Search: keyword vs semantic

- `search(query)` — substring / regex over bodies; `SearchHit.score` denser/earlier matches.

- `semantic_search(query, top_k=…)` — embed query $`+`$ bodies; rank by cosine similarity; same `SearchHit` shape with cosine `score`.

  - Default embedder: `HashEmbedder` (deterministic bag-of-words hashing; offline/tests).

  - Production: `OpenAIEmbedder` behind `[embeddings]`.

Keyword `search()` is unchanged.

# Lint as static analysis

Prompt lint is **static**: it inspects text without calling an LLM. `LintRules` / `lint_prompt` / `lint_all` emit `LintIssue` records (`rule`, `message`, `severity`, location).

| **Rule** | **Idea** |
|:---|:---|
| `max_chars` | Length budget (error) |
| `banned_phrases` | Case-insensitive substring denylist (error) |
| `require_placeholders` | Must contain `{name}` format fields (error) |
| `no_trailing_whitespace` | Line hygiene (warning) |
| `json_mode_hint` | Regex detect JSON-output language: warn / `require` / `forbid` |

Static lint rules. {#tab:lint-rules}

This is analogous to a linter AST pass: cheap, deterministic, CI-friendly. Schema validation (`validate_vars` / `load_validated`) is a related static check over declared variable contracts, separate from prose lint rules.

# Diff, CLI, and companions

Conceptual companions (same package):

- `diff_versions` — textual diff across versions for review.

- CLI: `diff` / `tag` / `freeze` / `log` / lint- oriented workflows.

These do not change resolution algebra; they operationalize it for humans and CI.

# Design invariants

1.  **Filesystem (or backend) is the registry** — Git distributes; no cloud hub required.

2.  **`latest` is an alias, not $`\max(vN)`$ when a latest file exists.**

3.  **Tags and locks are pointers** — resolve externally, then load by concrete version.

4.  **Strict formatting fails closed** by default.

5.  **Jinja is sandboxed** — treat templates as untrusted when variables or includes are attacker-influenced.

6.  **Usage logs never store variable values.**

7.  **Ledger promotes winners from production metrics** — A/B is the cold-start fallback.

8.  **Backends fail loud** when unavailable (`BackendUnavailableError`).

9.  **Oversized prompts fail loud** (`PromptSizeError` / `MAX_PROMPT_BYTES`).

10. **Invalid names/versions fail loud** (`ValidationError`, also a `ValueError`).

# Mapping to source

| **Concept** | **Module** |
|:---|:---|
| Root, load, resolve, compile, `MAX_PROMPT_BYTES` | `promptconf.loader` |
| Bound store | `promptconf.store.PromptStore` |
| Backends | `promptconf.backends` (`FilesystemBackend`, `GitStoreBackend`) |
| Compile cache | `promptconf.cache` (`CompileCache`, `load_cached`) |
| Performance ledger | `promptconf.ledger` (`record_outcome`, `best_version`, `recommend`) |
| Semantic search | `promptconf.semantic_search` |
| Exceptions | `promptconf.exceptions` (`ValidationError`, `BackendUnavailableError`, `PromptSizeError`, …) |
| Tags, freeze, usage log read | `promptconf.vcs` |
| Jinja sandbox | `promptconf.template` |
| Includes loader | `promptconf.includes` |
| A/B router | `promptconf.ab` |
| Lint | `promptconf.lint` |
| Frontmatter | `promptconf.meta` |
| Schema validation | `promptconf.schema` |

Concept-to-module mapping. {#tab:source-map}

# References

<div class="enumerate">

Liu, P., et al. (2021). *Pre-train, Prompt, and Predict.* <https://arxiv.org/abs/2107.13586>

Khattab, O., et al. (2023). *DSPy.* <https://arxiv.org/abs/2310.03714>

Schulhoff, S., et al. (2024). *The Prompt Report.* <https://arxiv.org/abs/2406.06608>

Jinja2 SandboxedEnvironment documentation (template isolation).

Python `string.Formatter` (format-engine field parsing).

OpenAI Embeddings API (optional semantic search).

</div>
