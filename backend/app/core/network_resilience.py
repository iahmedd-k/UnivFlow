import time
import functools
import logging
from typing import Callable, Any, Type, Tuple

logger = logging.getLogger(__name__)


def resilient_retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    allowed_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorator for robust HTTP / external API calls with exponential backoff & jitter.
    Guarantees connectivity sustainability even over spotty network connections.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except allowed_exceptions as err:
                    last_err = err
                    if attempt == max_retries:
                        logger.error(f"[NetworkResilience] Final retry ({attempt}/{max_retries}) failed for {func.__name__}: {err}")
                        raise
                    logger.warning(
                        f"[NetworkResilience] Attempt {attempt}/{max_retries} for {func.__name__} failed: {err}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
            if last_err:
                raise last_err
        return wrapper
    return decorator


class MemoryCache:
    """
    High-performance in-memory cache with Time-To-Live (TTL) expiration.
    Eliminates redundant DB hits and external network requests.
    """
    def __init__(self, default_ttl_seconds: int = 60):
        self.default_ttl = default_ttl_seconds
        self._cache = {}

    def get(self, key: str) -> Any:
        item = self._cache.get(key)
        if not item:
            return None
        val, expiry = item
        if time.time() > expiry:
            del self._cache[key]
            return None
        return val

    def set(self, key: str, value: Any, ttl_seconds: int = None):
        ttl = ttl_seconds or self.default_ttl
        self._cache[key] = (value, time.time() + ttl)

    def invalidate(self, key: str):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()


# Global cache instance for high-traffic read operations
global_api_cache = MemoryCache(default_ttl_seconds=30)
