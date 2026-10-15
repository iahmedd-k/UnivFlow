import json
from hashlib import sha256
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.logging import logger


ATTENDANCE_SUMMARY_CACHE_KEY = "uniflow:cache:dashboard:attendance-summary:v1"
ATTENDANCE_SUMMARY_CACHE_VERSION_KEY = f"{ATTENDANCE_SUMMARY_CACHE_KEY}:generation"


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
    serialized = quote(json.dumps(value, separators=(",", ":")), safe="")
    try:
        _request("POST", f"/set/{quote(key, safe='')}/{serialized}?EX={int(ttl_seconds)}")
    except UpstashRedisError as error:
        logger.warning("Redis cache write skipped: %s", error)


def attendance_summary_cache_key(user_id: str, generation: str) -> str:
    user_hash = sha256(user_id.encode("utf-8")).hexdigest()
    return f"{ATTENDANCE_SUMMARY_CACHE_KEY}:{user_hash}:{generation}"


def get_attendance_cache_generation() -> str | None:
    if not is_configured():
        return None
    try:
        generation = _request(
            "GET",
            f"/get/{quote(ATTENDANCE_SUMMARY_CACHE_VERSION_KEY, safe='')}",
        )
    except UpstashRedisError as error:
        logger.warning("Redis cache generation read skipped: %s", error)
        return None
    return str(generation) if generation is not None else "0"


def invalidate_attendance_summary_cache() -> None:
    if not is_configured():
        return
    try:
        _request(
            "POST",
            f"/incr/{quote(ATTENDANCE_SUMMARY_CACHE_VERSION_KEY, safe='')}",
        )
    except UpstashRedisError as error:
        logger.warning("Redis cache invalidation skipped: %s", error)


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
