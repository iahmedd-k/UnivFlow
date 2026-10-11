from urllib.parse import parse_qs, urlsplit

from app.auth import router


def test_oauth_redirect_returns_to_classroom_and_preserves_query(monkeypatch):
    monkeypatch.setattr(router.settings, "frontend_url", "https://uniflow.example")

    redirect_url = router._oauth_frontend_redirect(
        "/dashboard/classroom?tab=courses",
        google_connected="true",
        email="student+classroom@example.com",
    )
    parsed = urlsplit(redirect_url)

    assert parsed.scheme == "https"
    assert parsed.netloc == "uniflow.example"
    assert parsed.path == "/dashboard/classroom"
    assert parse_qs(parsed.query) == {
        "tab": ["courses"],
        "google_connected": ["true"],
        "email": ["student+classroom@example.com"],
    }


def test_oauth_redirect_rejects_external_destination(monkeypatch):
    monkeypatch.setattr(router.settings, "frontend_url", "https://uniflow.example")

    redirect_url = router._oauth_frontend_redirect(
        "https://attacker.example/steal",
        google_error="access_denied",
    )

    assert redirect_url == "https://uniflow.example?google_error=access_denied"
