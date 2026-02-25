"""Embedding provider factory — swap embedding models by changing EMBEDDING_PROVIDER.

Supported providers
-------------------
  openai   (default) — text-embedding-3-small / text-embedding-3-large via langchain-openai
  ollama             — any locally-served model via langchain-ollama (install separately)
  cohere             — Cohere embed models via langchain-cohere (install separately)

The public interface (create_embedding / to_pgvector_literal) is unchanged so
ingestion and semantic search work without modification.
"""

from functools import lru_cache

from langchain_core.embeddings import Embeddings

from backend.config import settings


@lru_cache(maxsize=1)
def _get_embedder() -> Embeddings:
    """Instantiate and cache the configured embedding model."""
    provider = settings.embedding_provider

    if provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "Install langchain-openai: pip install langchain-openai"
            )
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )

    if provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            raise ImportError(
                "Install langchain-ollama: pip install langchain-ollama"
            )
        return OllamaEmbeddings(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )

    if provider == "cohere":
        try:
            from langchain_cohere import CohereEmbeddings
        except ImportError:
            raise ImportError(
                "Install langchain-cohere: pip install langchain-cohere"
            )
        return CohereEmbeddings(
            model=settings.embedding_model,
            cohere_api_key=settings.cohere_api_key,
        )

    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER '{provider}'. "
        "Supported values: openai, ollama, cohere"
    )


def create_embedding(text: str) -> list[float]:
    """Embed a single text string using the configured embedding model.

    Returns a list of floats (dimension depends on model — 1536 for
    text-embedding-3-small, 3072 for text-embedding-3-large).
    Raises ValueError for empty input.
    """
    normalized = text.strip()
    if not normalized:
        raise ValueError("Cannot embed empty text.")
    return _get_embedder().embed_query(normalized)


def to_pgvector_literal(vector: list[float]) -> str:
    """Format a float list as a pgvector literal string, e.g. '[0.1,0.2,...]'."""
    return f"[{','.join(str(v) for v in vector)}]"
