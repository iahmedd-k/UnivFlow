import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    # Accept "healthy" or "degraded" since external services (Piston, Kroki) may not be configured in test env
    assert data["status"] in ("healthy", "degraded")
    assert data["service"] == "Uniflow"
    assert data["checks"]["database"] == "healthy"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Welcome to Uniflow API"
    assert data["version"] == "1.0.0"