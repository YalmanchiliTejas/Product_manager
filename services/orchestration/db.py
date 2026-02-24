"""
Supabase client — single instance reused across requests.
Calls are synchronous and wrapped in asyncio.to_thread() at the call site
so they don't block the FastAPI event loop.
"""

import asyncio
from functools import partial
from typing import Any, Callable

from supabase import create_client, Client
from services.orchestration.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client


async def run_sync(fn: Callable[[], Any]) -> Any:
    """Run a synchronous (blocking) Supabase call in a thread pool."""
    return await asyncio.to_thread(fn)
