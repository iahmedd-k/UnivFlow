from supabase import create_client, Client
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

supabase: Client = None


def get_supabase_client() -> Client:
    global supabase
    if supabase is None:
        if not settings.supabase_url or not settings.supabase_secret_key:
            logger.warning("Supabase URL or Secret Key not configured")
            return None
        try:
            supabase = create_client(settings.supabase_url, settings.supabase_secret_key)
            logger.info("Supabase client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            return None
    return supabase


def init_supabase():
    return get_supabase_client()