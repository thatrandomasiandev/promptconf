"""Custom exceptions for promptconf."""

from __future__ import annotations


class PromptconfError(Exception):
    """Base exception for all promptconf errors."""


class PromptNotFoundError(PromptconfError):
    """Raised when a prompt name or version cannot be resolved."""


class PromptFormatError(PromptconfError):
    """Raised when prompt variable substitution fails."""


class PromptSchemaError(PromptconfError):
    """Raised when prompt variables fail schema validation."""


class PromptLintError(PromptconfError):
    """Raised when lint finds error-severity issues (optional hard-fail)."""


class PromptSizeError(PromptconfError):
    """Raised when a prompt file exceeds the configured maximum size."""


class ValidationError(PromptconfError, ValueError):
    """Raised when caller input fails validation (empty name, bad version, …)."""


class BackendUnavailableError(PromptconfError):
    """Raised when a pluggable store backend cannot be used."""
