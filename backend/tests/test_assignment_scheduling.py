import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.db.models import Setting

assignment_router = importlib.import_module("app.assignments.router")


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.result


class FakeSession:
    def __init__(self, setting=None):
        self.setting = setting
        self.deleted = []
        self.commits = 0

    def query(self, model):
        assert model is Setting
        return FakeQuery(self.setting)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1


def test_requested_schedule_returns_non_success_without_persisting(monkeypatch):
    monkeypatch.setattr(
        assignment_router,
        "_find_assignment",
        lambda _db, _assignment_id: SimpleNamespace(id=27),
    )
    db = FakeSession()

    with pytest.raises(HTTPException) as error:
        assignment_router.schedule_assignment_turn_in(
            "27",
            assignment_router.ScheduleTurnInRequest(enabled=True),
            db,
        )

    assert error.value.status_code == 501
    assert "no schedule was saved" in error.value.detail
    assert "authenticated user" in error.value.detail
    assert db.commits == 0
    assert db.deleted == []


def test_cancellation_removes_existing_schedule(monkeypatch):
    monkeypatch.setattr(
        assignment_router,
        "_find_assignment",
        lambda _db, _assignment_id: SimpleNamespace(id=27),
    )
    existing = object()
    db = FakeSession(setting=existing)

    result = assignment_router.schedule_assignment_turn_in(
        "27",
        assignment_router.ScheduleTurnInRequest(enabled=False),
        db,
    )

    assert result["status"] == "cancelled"
    assert result["assignment_id"] == 27
    assert db.deleted == [existing]
    assert db.commits == 1


def test_cancellation_is_idempotent_when_no_schedule_exists(monkeypatch):
    monkeypatch.setattr(
        assignment_router,
        "_find_assignment",
        lambda _db, _assignment_id: SimpleNamespace(id=27),
    )
    db = FakeSession()

    result = assignment_router.schedule_assignment_turn_in(
        "27",
        assignment_router.ScheduleTurnInRequest(enabled=False),
        db,
    )

    assert result["status"] == "cancelled"
    assert db.deleted == []
    assert db.commits == 0
