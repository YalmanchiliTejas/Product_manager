from openai import OpenAI
from backend.config import settings

_openai_client: OpenAI | None = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not settings.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY must be set.")
        _openai_client = OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def create_embedding(text: str) -> list[float]:
    """Embed a single text string using the configured OpenAI embedding model.

    Returns a list of floats (1536-dim for text-embedding-3-small).
    Raises ValueError for empty input.
    """
    normalized = text.strip()
    if not normalized:
        raise ValueError("Cannot embed empty text.")

    client = _get_openai()
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=normalized,
    )
    embedding = response.data[0].embedding
    if not embedding:
        raise RuntimeError("OpenAI returned an empty embedding.")
    return embedding


def to_pgvector_literal(vector: list[float]) -> str:
    """Format a float list as a pgvector literal string, e.g. '[0.1,0.2,...]'."""
    return f"[{','.join(str(v) for v in vector)}]"
