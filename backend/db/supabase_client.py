from supabase import create_client, Client
from backend.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    """Return a singleton Supabase admin client."""
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set."
            )
        _client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _client
