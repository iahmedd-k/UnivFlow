import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self):
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _cleanup_old_requests(self, key: str, window_seconds: float, now: float) -> list[float]:
        cutoff = now - window_seconds
        timestamps = [ts for ts in self._history[key] if ts > cutoff]
        self._history[key] = timestamps
        return timestamps

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """Check if request is allowed. Returns (is_allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            timestamps = self._cleanup_old_requests(key, window_seconds, now)
            if len(timestamps) >= max_requests:
                earliest = timestamps[0]
                retry_after = max(1, int(window_seconds - (now - earliest)))
                return False, retry_after

            self._history[key].append(now)
            return True, 0


limiter = SlidingWindowRateLimiter()


def get_client_identifier(request: Request) -> str:
    """Extract client identifier from proxy headers, auth header, or client IP."""
    # 1. Prefer Forwarded IP from reverse proxies (Render / Cloudflare)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    # 2. Fallback to client host
    if request.client and request.client.host:
        return request.client.host

    return "anonymous"


def rate_limit(
    max_requests: int = 60,
    window_seconds: int = 60,
    key_prefix: str = "general",
) -> Callable:
    """FastAPI Dependency for rate limiting endpoints."""

    async def dependency(request: Request):
        client_id = get_client_identifier(request)
        rate_key = f"{key_prefix}:{client_id}"

        allowed, retry_after = limiter.check_rate_limit(
            key=rate_key,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please wait {retry_after} seconds before trying again.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
