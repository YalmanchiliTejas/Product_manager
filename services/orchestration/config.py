"""
Centralised configuration.

All AI-provider choices are driven by environment variables so you can swap
providers (Claude → GPT-4o → Gemini → Mistral) with zero code changes.

LiteLLM model strings:
  Claude  → "claude-haiku-4-5-20251001", "claude-sonnet-4-5", "claude-opus-4-5"
  OpenAI  → "gpt-4o-mini", "gpt-4o"
  Gemini  → "gemini/gemini-2.0-flash", "gemini/gemini-2.5-pro"
  Mistral → "mistral/mistral-small-latest"
  Cohere  → "cohere/command-r-plus"

Embedding model strings:
  OpenAI  → "text-embedding-3-small"  (1536 dims)
  Voyage  → "voyage/voyage-3"          (1024 dims — must update pgvector schema)
  Cohere  → "cohere/embed-english-v3.0"
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── LLM tiers ───────────────────────────────────────────────────────────
    # MAP phase — fast & cheap, runs once per source document in parallel
    LLM_FAST: str = os.getenv("LLM_FAST_MODEL", "claude-haiku-4-5-20251001")
    # REDUCE / chat — solid reasoning, good throughput
    LLM_BALANCED: str = os.getenv("LLM_BALANCED_MODEL", "claude-sonnet-4-5")
    # SCORE phase — best reasoning, used once per synthesis run
    LLM_DEEP: str = os.getenv("LLM_DEEP_MODEL", "claude-opus-4-5")

    # ── Embedding model ──────────────────────────────────────────────────────
    # Must match the vector(N) dimension in your Supabase schema.
    # Default: text-embedding-3-small → 1536 dims
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMS: int = int(os.getenv("EMBEDDING_DIMS", "1536"))

    # ── Supabase ─────────────────────────────────────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # ── Service ──────────────────────────────────────────────────────────────
    PORT: int = int(os.getenv("ORCHESTRATION_PORT", "8000"))
    HOST: str = os.getenv("ORCHESTRATION_HOST", "0.0.0.0")


settings = Settings()
