"""Application settings — driven entirely by environment variables.

Minimal required .env (using default Anthropic + OpenAI providers):

    SUPABASE_URL=...
    SUPABASE_SERVICE_ROLE_KEY=...
    ANTHROPIC_API_KEY=...          # only if LLM_PROVIDER=anthropic (default)
    OPENAI_API_KEY=...             # only if EMBEDDING_PROVIDER=openai (default)

Switching providers:

    LLM_PROVIDER=openai
    OPENAI_API_KEY=...
    FAST_MODEL=gpt-4o-mini
    STRONG_MODEL=gpt-4o

    LLM_PROVIDER=ollama            # local — no API key needed
    OLLAMA_BASE_URL=http://localhost:11434
    FAST_MODEL=llama3.2
    STRONG_MODEL=llama3.1:70b

    LLM_PROVIDER=groq
    GROQ_API_KEY=...
    FAST_MODEL=llama-3.1-8b-instant
    STRONG_MODEL=llama-3.3-70b-versatile

    LLM_PROVIDER=azure_openai
    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
    FAST_MODEL=gpt-4o-mini          # must match your Azure deployment name
    STRONG_MODEL=gpt-4o

    EMBEDDING_PROVIDER=ollama       # local embeddings
    EMBEDDING_MODEL=nomic-embed-text

    EMBEDDING_PROVIDER=cohere
    COHERE_API_KEY=...
    EMBEDDING_MODEL=embed-english-v3.0

Persistent memory:

    DATABASE_URL=postgresql://user:pass@host:5432/dbname
    # Get from Supabase: Project Settings → Database → Connection string (URI)
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ------------------------------------------------------------------
    # Supabase (always required)
    # ------------------------------------------------------------------
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # ------------------------------------------------------------------
    # LLM provider selection
    # Supported: anthropic (default) | openai | ollama | groq | azure_openai
    # ------------------------------------------------------------------
    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic")

    # Model names — set these to match your chosen provider's model IDs
    fast_model: str = os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001")
    strong_model: str = os.getenv("STRONG_MODEL", "claude-sonnet-4-6")

    # ------------------------------------------------------------------
    # Embedding provider selection
    # Supported: openai (default) | ollama | cohere
    # ------------------------------------------------------------------
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "openai")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # ------------------------------------------------------------------
    # Provider API keys — only the key(s) for your chosen providers are needed
    # ------------------------------------------------------------------
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    cohere_api_key: str = os.getenv("COHERE_API_KEY", "")

    # Azure OpenAI
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")

    # Ollama (local — no API key needed)
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))

    # Ingestion concurrency
    embed_concurrency: int = int(os.getenv("EMBED_CONCURRENCY", "4"))

    # ------------------------------------------------------------------
    # Persistent memory (mem0 pgvector backend)
    # Full PostgreSQL connection string from Supabase:
    #   Project Settings → Database → Connection string (URI)
    # If unset, mem0 uses in-memory storage (lost on restart).
    # ------------------------------------------------------------------
    database_url: str = os.getenv("DATABASE_URL", "")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Check that all required env vars for the chosen providers are present."""
        import warnings

        # Supabase is always required
        missing = []
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        # LLM provider key check
        llm_key_checks = {
            "anthropic": ("ANTHROPIC_API_KEY", self.anthropic_api_key),
            "openai": ("OPENAI_API_KEY", self.openai_api_key),
            "groq": ("GROQ_API_KEY", self.groq_api_key),
            "azure_openai": ("AZURE_OPENAI_API_KEY", self.azure_openai_api_key),
        }
        if self.llm_provider in llm_key_checks:
            var_name, value = llm_key_checks[self.llm_provider]
            if not value:
                raise EnvironmentError(
                    f"{var_name} is required when LLM_PROVIDER={self.llm_provider}"
                )
        if self.llm_provider == "azure_openai" and not self.azure_openai_endpoint:
            raise EnvironmentError(
                "AZURE_OPENAI_ENDPOINT is required when LLM_PROVIDER=azure_openai"
            )

        # Embedding provider key check
        embed_key_checks = {
            "openai": ("OPENAI_API_KEY", self.openai_api_key),
            "cohere": ("COHERE_API_KEY", self.cohere_api_key),
        }
        if self.embedding_provider in embed_key_checks:
            var_name, value = embed_key_checks[self.embedding_provider]
            if not value:
                raise EnvironmentError(
                    f"{var_name} is required when EMBEDDING_PROVIDER={self.embedding_provider}"
                )

        # Non-fatal: persistent memory warning
        if not self.database_url:
            warnings.warn(
                "DATABASE_URL is not set. mem0 will use in-memory storage — "
                "memories will not persist across server restarts. "
                "Set DATABASE_URL to a PostgreSQL connection string for persistent memory.",
                RuntimeWarning,
                stacklevel=2,
            )


settings = Settings()
