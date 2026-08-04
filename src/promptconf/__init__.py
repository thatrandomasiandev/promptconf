"""promptconf — git-like prompt version control for local AI engineering."""

from __future__ import annotations

from promptconf.ab import ABRouter
from promptconf.backends import FilesystemBackend, GitStoreBackend, PromptBackend
from promptconf.cache import CompileCache, load_cached
from promptconf.diff import diff_versions
from promptconf.exceptions import (
    BackendUnavailableError,
    PromptFormatError,
    PromptLintError,
    PromptNotFoundError,
    PromptSchemaError,
    PromptSizeError,
    PromptconfError,
    ValidationError,
)
from promptconf.ledger import (
    PerformanceLedger,
    best_version,
    recommend,
    record_outcome,
)
from promptconf.lint import LintIssue, LintRules, lint_all, lint_prompt
from promptconf.loader import (
    MAX_PROMPT_BYTES,
    compile_prompt,
    list_prompts,
    list_versions,
    load,
    resolve_root,
)
from promptconf.meta import parse_frontmatter
from promptconf.schema import load_schema_for, load_validated, validate_vars
from promptconf.search import SearchHit, search
from promptconf.semantic_search import (
    EmbeddingClient,
    HashEmbedder,
    OpenAIEmbedder,
    semantic_search,
)
from promptconf.store import PromptStore
from promptconf.vcs import freeze, log, resolve_tag, tag

__version__ = "0.3.0"

__all__ = [
    "ABRouter",
    "BackendUnavailableError",
    "CompileCache",
    "EmbeddingClient",
    "FilesystemBackend",
    "GitStoreBackend",
    "HashEmbedder",
    "LintIssue",
    "LintRules",
    "OpenAIEmbedder",
    "PerformanceLedger",
    "PromptBackend",
    "PromptFormatError",
    "PromptLintError",
    "PromptNotFoundError",
    "PromptSchemaError",
    "PromptSizeError",
    "PromptStore",
    "PromptconfError",
    "SearchHit",
    "ValidationError",
    "__version__",
    "best_version",
    "compile_prompt",
    "diff_versions",
    "freeze",
    "lint_all",
    "lint_prompt",
    "list_prompts",
    "list_versions",
    "load",
    "load_cached",
    "load_schema_for",
    "load_validated",
    "log",
    "MAX_PROMPT_BYTES",
    "parse_frontmatter",
    "recommend",
    "record_outcome",
    "resolve_root",
    "resolve_tag",
    "search",
    "semantic_search",
    "tag",
    "validate_vars",
]
