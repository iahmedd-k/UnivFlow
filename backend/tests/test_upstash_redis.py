from urllib.parse import unquote, urlsplit

from app.core import redis as redis_client


class FakeResponse:
    def __init__(self, result):
        self._result = result

    def raise_for_status(self):
        return None

    def json(self):
        return {"result": self._result}


def configure_redis(monkeypatch):
    monkeypatch.setattr(
        redis_client.settings,
        "upstash_redis_rest_url",
        "https://redis.example.test",
    )
    monkeypatch.setattr(redis_client.settings, "upstash_redis_rest_token", "test-token")


def test_json_cache_reads_and_writes_with_expiration(monkeypatch):
    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url, headers, timeout))
        return FakeResponse('{"courses":3}')

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    assert redis_client.get_json("dashboard:attendance") == {"courses": 3}
    redis_client.set_json("dashboard:attendance", {"courses": 3}, ttl_seconds=20)

    assert calls[0][0] == "GET"
    assert urlsplit(calls[0][1]).path == "/get/dashboard%3Aattendance"
    assert calls[1][0] == "POST"
    assert calls[1][1].endswith("/set/dashboard%3Aattendance/%7B%22courses%22%3A3%7D?EX=20")
    assert calls[0][2]["Authorization"] == "Bearer test-token"


def test_distributed_lock_acquires_and_releases_only_its_owner(monkeypatch):
    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url))
        return FakeResponse("OK" if "/set/" in url else 1)

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    assert redis_client.acquire_lock("portal:sync:user", "owner", ttl_seconds=900)
    redis_client.release_lock("portal:sync:user", "owner")

    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/set/portal%3Async%3Auser/owner?EX=900&NX")
    assert calls[1][0] == "POST"
    assert "eval" in unquote(urlsplit(calls[1][1]).path)
    assert urlsplit(calls[1][1]).path.endswith("/1/portal%3Async%3Auser/owner")


def test_lock_conflict_returns_false(monkeypatch):
    configure_redis(monkeypatch)
    monkeypatch.setattr(
        redis_client.httpx,
        "request",
        lambda *args, **kwargs: FakeResponse(None),
    )

    assert not redis_client.acquire_lock("portal:sync:user", "other", ttl_seconds=900)


def test_attendance_cache_invalidation_is_user_scoped(monkeypatch):
    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url))
        return FakeResponse(1)

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    redis_client.invalidate_attendance_summary_cache("user-a")

    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert "user-a" not in calls[0][1]
    assert "dashboard%3Aattendance-summary" in calls[0][1]
    assert "attendance%3Arecords" in calls[0][1]
    assert "timetable%3Aclasses" in calls[0][1]


def test_malformed_rest_response_disables_cache(monkeypatch):
    configure_redis(monkeypatch)

    class MalformedResponse(FakeResponse):
        def json(self):
            return {}

    monkeypatch.setattr(
        redis_client.httpx,
        "request",
        lambda *args, **kwargs: MalformedResponse(None),
    )

    assert redis_client.get_json("cache:key") is None


def test_user_cache_keys_are_scoped_and_invalidation_deletes_only_that_key(monkeypatch):
    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url))
        return FakeResponse(1)

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    user_a_key = redis_client.user_cache_key("timetable:classes", "user-a")
    user_b_key = redis_client.user_cache_key("timetable:classes", "user-b")
    assert user_a_key != user_b_key

    redis_client.invalidate_user_cache("timetable:classes", "user-a")
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith(f"/del/{user_a_key.replace(':', '%3A')}")


def test_user_cache_serializes_datetime_fields(monkeypatch):
    from datetime import datetime, timezone

    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url))
        return FakeResponse("OK")

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    redis_client.set_user_cache(
        "attendance:records",
        "user-a",
        {"updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
        ttl_seconds=30,
    )

    assert calls[0][0] == "POST"
    assert "%222026-01-02T00%3A00%3A00%2B00%3A00%22" in calls[0][1]
