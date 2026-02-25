import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # LLM providers
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Models
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    # Fast model for theme extraction (Pass 1)
    fast_model: str = os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001")
    # Strong model for opportunity scoring (Pass 2) and RAG generation
    strong_model: str = os.getenv("STRONG_MODEL", "claude-sonnet-4-6")

    # Chunking
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))

    # Ingestion concurrency
    embed_concurrency: int = int(os.getenv("EMBED_CONCURRENCY", "4"))

    # Persistent memory (mem0 pgvector backend)
    # Set to a full PostgreSQL connection string: postgresql://user:pass@host:5432/dbname
    # Available from Supabase: Project Settings → Database → Connection string (URI)
    # If unset, mem0 falls back to local in-memory storage (memories lost on restart)
    database_url: str = os.getenv("DATABASE_URL", "")

    def validate(self) -> None:
        missing = []
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
        if not self.database_url:
            import warnings
            warnings.warn(
                "DATABASE_URL is not set. mem0 will use in-memory storage — "
                "memories will not persist across server restarts. "
                "Set DATABASE_URL to a PostgreSQL connection string for persistent memory.",
                RuntimeWarning,
                stacklevel=2,
            )


settings = Settings()
