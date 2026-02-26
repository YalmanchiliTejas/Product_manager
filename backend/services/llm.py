"""LLM provider factory — swap models by changing LLM_PROVIDER in .env.

Supported providers
-------------------
  anthropic   (default) — Claude family via langchain-anthropic
  openai                — GPT family via langchain-openai
  ollama                — local models via langchain-ollama (install separately)
  groq                  — Groq-hosted models via langchain-groq (install separately)
  azure_openai          — Azure OpenAI via langchain-openai

All providers return a LangChain BaseChatModel so every downstream service
(synthesis, RAG, memory) uses the same .invoke([messages]) interface.

Usage
-----
    from backend.services.llm import get_fast_llm, get_strong_llm

    response = get_fast_llm().invoke([
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="Hello!"),
    ])
    text: str = response.content

Response shape
--------------
    response.content         → str   (the generated text)
    response.usage_metadata  → dict  {input_tokens, output_tokens}  (may be None)
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from backend.config import settings


def _build_llm(model: str, max_tokens: int) -> BaseChatModel:
    """Instantiate the configured LLM provider for the given model + token budget."""
    provider = settings.llm_provider

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "Install langchain-anthropic: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            max_tokens=max_tokens,
        )

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "Install langchain-openai: pip install langchain-openai"
            )
        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            max_tokens=max_tokens,
        )

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "Install langchain-ollama: pip install langchain-ollama"
            )
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            num_predict=max_tokens,   # Ollama's equivalent of max_tokens
        )

    if provider == "groq":
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise ImportError(
                "Install langchain-groq: pip install langchain-groq"
            )
        return ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            max_tokens=max_tokens,
        )

    if provider == "azure_openai":
        try:
            from langchain_openai import AzureChatOpenAI
        except ImportError:
            raise ImportError(
                "Install langchain-openai: pip install langchain-openai"
            )
        return AzureChatOpenAI(
            azure_deployment=model,
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            max_tokens=max_tokens,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        "Supported values: anthropic, openai, ollama, groq, azure_openai"
    )


@lru_cache(maxsize=1)
def get_fast_llm() -> BaseChatModel:
    """Return the cached fast/cheap LLM (theme extraction, memory extraction).

    Maps to FAST_MODEL env var (default: claude-haiku-4-5-20251001).
    """
    return _build_llm(settings.fast_model, max_tokens=4096)


@lru_cache(maxsize=1)
def get_strong_llm() -> BaseChatModel:
    """Return the cached powerful LLM (opportunity scoring, RAG generation).

    Maps to STRONG_MODEL env var (default: claude-sonnet-4-6).
    """
    return _build_llm(settings.strong_model, max_tokens=6144)
