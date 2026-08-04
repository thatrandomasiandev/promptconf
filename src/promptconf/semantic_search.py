"""Embedding-based semantic search over prompt bodies."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from promptconf.loader import SUPPORTED_EXTENSIONS, list_prompts, resolve_root
from promptconf.search import SearchHit


@runtime_checkable
class EmbeddingClient(Protocol):
    """Minimal interface for embedding one or more texts."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder (stdlib only).

    Suitable for unit tests and offline demos. Not a substitute for
    learned embeddings in production semantic search.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim < 8:
            raise ValueError("dim must be >= 8")
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class OpenAIEmbedder:
    """Thin wrapper around the OpenAI Embeddings API (``[embeddings]`` extra)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIEmbedder requires the openai package. "
                "Install with: pip install 'promptconf[embeddings]'"
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY or pass api_key."
            )
        kwargs: dict[str, str] = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
        )
        by_index = {item.index: item.embedding for item in response.data}
        return [list(by_index[i]) for i in range(len(texts))]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity between two vectors."""
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def semantic_search(
    query: str,
    root: str | Path | None = None,
    *,
    top_k: int = 5,
    embedder: EmbeddingClient | None = None,
    names: Sequence[str] | None = None,
    context: int = 80,
) -> list[SearchHit]:
    """Rank prompt bodies by embedding cosine similarity to ``query``.

    Reuses :class:`~promptconf.search.SearchHit` with ``score`` set to the
    cosine similarity. Keyword/regex :func:`~promptconf.search.search` is
    unchanged.

    Parameters
    ----------
    query:
        Free-text query to embed and compare against prompt bodies.
    root:
        Prompts root directory.
    top_k:
        Maximum number of hits to return (best scores first).
    embedder:
        Embedding client. Defaults to :class:`HashEmbedder`.
    names:
        Optional subset of prompt names to search.
    context:
        Characters of surrounding context included in each snippet
        (centered on the start of the body).
    """
    if not query or not str(query).strip():
        return []
    if top_k < 1:
        return []

    root_path = resolve_root(root)
    target_names = list(names) if names is not None else list_prompts(root_path)
    client = embedder or HashEmbedder()

    docs: list[tuple[str, str, Path, str]] = []
    for name in target_names:
        prompt_dir = root_path / name
        if not prompt_dir.is_dir():
            continue
        for entry in sorted(prompt_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            text = entry.read_text(encoding="utf-8")
            docs.append((name, entry.stem, entry, text))

    if not docs:
        return []

    vectors = client.embed([query] + [text for *_, text in docs])
    if len(vectors) != len(docs) + 1:
        raise RuntimeError("EmbeddingClient must return one vector per text")

    query_vec = vectors[0]
    hits: list[SearchHit] = []
    for (name, version, path, text), vec in zip(docs, vectors[1:]):
        score = cosine_similarity(query_vec, vec)
        snippet = _make_snippet(text, context=context)
        hits.append(
            SearchHit(
                name=name,
                version=version,
                path=str(path),
                snippet=snippet,
                score=float(score),
                match_start=0,
                match_end=min(len(text), max(1, len(query))),
            )
        )

    hits.sort(key=lambda h: (-h.score, h.name, h.version))
    return hits[:top_k]


def _make_snippet(text: str, *, context: int) -> str:
    chunk = text[:context].replace("\n", " ")
    suffix = "…" if len(text) > context else ""
    return f"{chunk}{suffix}"
