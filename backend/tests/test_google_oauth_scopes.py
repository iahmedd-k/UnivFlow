from app.core.config import settings


def test_google_oauth_scopes_validity():
    scopes = settings.google_scopes_list
    assert isinstance(scopes, list)
    assert len(scopes) > 0

    # Ensure no scope has the invalid typo with dot coursework.materials
    for s in scopes:
        assert "classroom.coursework.materials" not in s, f"Found invalid scope with dot: {s}"

    # Ensure valid courseworkmaterials scope is present
    assert "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly" in scopes
    assert "https://www.googleapis.com/auth/classroom.courseworkmaterials" in scopes
    assert "https://www.googleapis.com/auth/classroom.coursework.students" in scopes
    assert "https://www.googleapis.com/auth/classroom.coursework.me.readonly" in scopes
