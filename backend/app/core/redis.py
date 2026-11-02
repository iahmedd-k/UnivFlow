import json
from hashlib import sha256
from urllib.parse import quote

import httpx
from fastapi.encoders import jsonable_encoder

from app.core.config import settings
from app.core.logging import logger


class UpstashRedisError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.upstash_redis_rest_url and settings.upstash_redis_rest_token)


def _request(method: str, path: str):
    if not is_configured():
        raise UpstashRedisError("Upstash Redis REST is not configured.")

    url = settings.upstash_redis_rest_url.rstrip("/") + path
    try:
        response = httpx.request(
            method,
            url,
            headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
            timeout=5.0,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise UpstashRedisError("Upstash Redis REST request failed.") from error

    if not isinstance(result, dict) or (
        "result" not in result and "error" not in result
    ):
        raise UpstashRedisError("Upstash Redis REST returned an invalid response.")
    if "error" in result:
        raise UpstashRedisError(f"Upstash Redis command failed: {result['error']}")
    return result.get("result")


def get_json(key: str):
    if not is_configured():
        return None
    try:
        value = _request("GET", f"/get/{quote(key, safe='')}")
    except UpstashRedisError as error:
        logger.warning("Redis cache read skipped: %s", error)
        return None

    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        logger.warning("Redis cache entry %s is invalid JSON: %s", key, error)
        return None


def set_json(key: str, value, ttl_seconds: int) -> None:
    if not is_configured():
        return
    try:
        serialized = quote(
            json.dumps(jsonable_encoder(value), separators=(",", ":"), allow_nan=False),
            safe="",
        )
    except (TypeError, ValueError) as error:
        logger.warning("Redis cache value %s could not be serialized: %s", key, error)
        return
    if len(serialized) + len(key) + 100 > 6000:
        logger.warning("Redis cache value %s is too large for the REST cache request.", key)
        return
    try:
        _request("POST", f"/set/{quote(key, safe='')}/{serialized}?EX={int(ttl_seconds)}")
    except UpstashRedisError as error:
        logger.warning("Redis cache write skipped: %s", error)


def user_cache_key(namespace: str, user_id: str, variant: str = "default") -> str:
    user_hash = sha256(user_id.encode("utf-8")).hexdigest()
    variant_hash = sha256(variant.encode("utf-8")).hexdigest()[:16]
    return f"uniflow:cache:{namespace}:v1:{user_hash}:{variant_hash}"


def get_user_cache(namespace: str, user_id: str, variant: str = "default"):
    return get_json(user_cache_key(namespace, user_id, variant))


def set_user_cache(
    namespace: str,
    user_id: str,
    value,
    ttl_seconds: int,
    variant: str = "default",
) -> None:
    set_json(user_cache_key(namespace, user_id, variant), value, ttl_seconds)


def invalidate_user_cache(
    namespace: str,
    user_id: str,
    variant: str = "default",
) -> None:
    invalidate_user_caches(namespace, user_id, [variant])


def invalidate_user_caches(
    namespace: str,
    user_id: str,
    variants: list[str],
) -> None:
    if not is_configured():
        return
    keys = [user_cache_key(namespace, user_id, variant) for variant in variants]
    if not keys:
        return
    path = "/del/" + "/".join(quote(key, safe="") for key in keys)
    try:
        _request("POST", path)
    except UpstashRedisError as error:
        logger.warning("Redis cache invalidation skipped for %s: %s", namespace, error)


def invalidate_attendance_summary_cache(user_id: str) -> None:
    if not is_configured():
        return
    namespaces = (
        "dashboard:attendance-summary",
        "attendance:records",
        "timetable:classes",
    )
    keys = [user_cache_key(namespace, user_id) for namespace in namespaces]
    path = "/del/" + "/".join(quote(key, safe="") for key in keys)
    try:
        _request("POST", path)
    except UpstashRedisError as error:
        logger.warning("Redis academic cache invalidation skipped: %s", error)


def acquire_lock(key: str, owner_token: str, ttl_seconds: int) -> bool:
    result = _request(
        "POST",
        f"/set/{quote(key, safe='')}/{quote(owner_token, safe='')}?EX={int(ttl_seconds)}&NX",
    )
    return result == "OK"


def release_lock(key: str, owner_token: str) -> None:
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] "
        "then return redis.call('del', KEYS[1]) else return 0 end"
    )
    path = (
        f"/eval/{quote(script, safe='')}/1/"
        f"{quote(key, safe='')}/{quote(owner_token, safe='')}"
    )
    _request("POST", path)


def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Check rate limit using sliding window algorithm.
    Returns True if allowed, False if rate limited.
    """
    if not is_configured():
        return True
    
    now = int(__import__("time").time())
    window_start = now - window_seconds
    
    try:
        pipeline = [
            ["ZREMRANGEBYSCORE", quote(key, safe=''), "0", str(window_start)],
            ["ZCARD", quote(key, safe='')],
            ["ZADD", quote(key, safe=''), str(now), f"{now}:{__import__('uuid').uuid4().hex[:8]}"],
            ["EXPIRE", quote(key, safe=''), str(window_seconds)],
        ]
        
        for cmd in pipeline:
            _request("POST", "/" + "/".join(quote(str(p), safe='') for p in cmd))
        
        count_result = _request("POST", f"/zcard/{quote(key, safe='')}")
        current_count = int(count_result) if count_result else 0
        
        if current_count > limit:
            _request("POST", f"/zrem/{quote(key, safe='')}/{str(now)}:*")
            return False
        
        return True
    except UpstashRedisError as error:
        logger.warning("Rate limit check failed, allowing request: %s", error)
        return True


def get_rate_limit_remaining(key: str, limit: int, window_seconds: int) -> int:
    """Get remaining requests in current window."""
    if not is_configured():
        return limit
    
    now = int(__import__("time").time())
    window_start = now - window_seconds
    
    try:
        _request("POST", f"/zremrangebyscore/{quote(key, safe='')}/0/{window_start}")
        count_result = _request("POST", f"/zcard/{quote(key, safe='')}")
        current_count = int(count_result) if count_result else 0
        return max(0, limit - current_count)
    except UpstashRedisError:
        return limit


import threading
import uuid

_in_memory_locks: dict[str, threading.Lock] = {}
_in_memory_lock_mutex = threading.Lock()


def _get_in_memory_lock(key: str) -> threading.Lock:
    with _in_memory_lock_mutex:
        if key not in _in_memory_locks:
            _in_memory_locks[key] = threading.Lock()
        return _in_memory_locks[key]


class DistributedLock:
    """Distributed lock that synchronizes across worker processes via Redis,
    falling back to in-memory threading.Lock when Redis is not available."""

    def __init__(self, key: str, ttl_seconds: int = 300):
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.token = uuid.uuid4().hex
        self.is_redis = False
        self._acquired = False

    def acquire(self, blocking: bool = True) -> bool:
        if is_configured():
            try:
                acquired = acquire_lock(self.key, self.token, self.ttl_seconds)
                if acquired:
                    self.is_redis = True
                    self._acquired = True
                    return True
                if not blocking:
                    return False
            except UpstashRedisError as err:
                logger.warning(f"Redis lock request failed, falling back to in-memory: {err}")

        # In-memory fallback
        mem_lock = _get_in_memory_lock(self.key)
        acquired = mem_lock.acquire(blocking=blocking)
        self._acquired = acquired
        return acquired

    def release(self) -> None:
        if not self._acquired:
            return
        if self.is_redis:
            try:
                release_lock(self.key, self.token)
            except UpstashRedisError as err:
                logger.warning(f"Failed to release Redis lock {self.key}: {err}")
        else:
            mem_lock = _get_in_memory_lock(self.key)
            if mem_lock.locked():
                try:
                    mem_lock.release()
                except RuntimeError:
                    pass
        self._acquired = False

    def locked(self) -> bool:
        return self._acquired

    def __enter__(self):
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def get_user_lock(resource: str, user_id: str, ttl_seconds: int = 300) -> DistributedLock:
    """Acquire a distributed lock across processes/workers with graceful in-memory fallback."""
    key = f"lock:{resource}:{user_id}"
    return DistributedLock(key, ttl_seconds=ttl_seconds)
