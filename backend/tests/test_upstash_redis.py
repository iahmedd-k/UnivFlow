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


def test_attendance_cache_keys_are_user_scoped_and_generation_invalidates(monkeypatch):
    configure_redis(monkeypatch)
    calls = []

    def fake_request(method, url, headers, timeout):
        calls.append((method, url))
        return FakeResponse("12" if method == "GET" else 13)

    monkeypatch.setattr(redis_client.httpx, "request", fake_request)

    assert redis_client.get_attendance_cache_generation() == "12"
    redis_client.invalidate_attendance_summary_cache()

    first_user_key = redis_client.attendance_summary_cache_key("user-a", "12")
    second_user_key = redis_client.attendance_summary_cache_key("user-b", "12")
    next_generation_key = redis_client.attendance_summary_cache_key("user-a", "13")
    assert first_user_key != second_user_key
    assert first_user_key != next_generation_key
    assert calls[1][1].endswith(
        "/incr/uniflow%3Acache%3Adashboard%3Aattendance-summary%3Av1%3Ageneration"
    )


def test_cache_generation_failure_disables_cache(monkeypatch):
    configure_redis(monkeypatch)

    def fail_request(*args, **kwargs):
        raise redis_client.httpx.ConnectError("offline")

    monkeypatch.setattr(redis_client.httpx, "request", fail_request)

    assert redis_client.get_attendance_cache_generation() is None


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

    assert redis_client.get_attendance_cache_generation() is None
